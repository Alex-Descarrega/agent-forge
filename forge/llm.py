"""Acceso a los modelos para los ROLES del entrenador (entrevistador, constructor, editor, juez).

Cada rol tiene contexto limpio: solo ve su system prompt (forge/roles/<rol>.md) y lo que le
pasamos en ese turno. Así el juez no sabe qué cambió el editor, y el editor no ve la rúbrica
del juez más de lo necesario.

Backends:
  - anthropic : usa el SDK `anthropic` (pip install anthropic). Necesita ANTHROPIC_API_KEY.
  - cli       : usa `claude -p` (Claude Code en modo headless). Tira de tu suscripción,
                no necesita API key. Cada llamada es un proceso: más lento, pero sin dependencias.
                No admite temperatura: el juez es más ruidoso que por API; compensa con --runs 3.
  - mock      : respuestas sintéticas para probar la tubería sin red.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ROLES_DIR = Path(__file__).parent / "roles"

DEFAULT_MODELS = {
    "interviewer": "claude-sonnet-4-5",
    "eval_builder": "claude-sonnet-4-5",
    "editor": "claude-opus-4-1",
    "judge": "claude-sonnet-4-5",
    "distiller": "claude-opus-4-1",
}

# Para el backend cli valen los alias de Claude Code ("sonnet", "opus", "haiku").
CLI_MODELS = {"interviewer": "sonnet", "eval_builder": "sonnet", "editor": "opus", "judge": "sonnet", "distiller": "opus"}

# Salida máxima por rol. El constructor devuelve decenas de casos y el editor el prompt completo:
# con 4k tokens se truncan y el JSON parcial falla después de haber pagado la llamada.
MAX_TOKENS = {"interviewer": 12000, "eval_builder": 32000, "editor": 16000, "judge": 800, "distiller": 24000}
TEMPERATURE = {"interviewer": 0.3, "eval_builder": 0.7, "editor": 0.3, "judge": 0.0, "distiller": 0.2}


class LLM:
    def __init__(self, backend: str = "anthropic", models: dict[str, str] | None = None, temperature: float = 0.2):
        self.backend = backend
        base = CLI_MODELS if backend == "cli" else DEFAULT_MODELS
        self.models = {**base, **(models or {})}
        self.temperature = temperature
        self._client = None
        if backend == "cli":
            import shutil
            if not shutil.which("claude"):
                raise SystemExit("No encuentro el comando `claude`. Instala Claude Code o usa --backend anthropic/mock.")
        if backend == "anthropic":
            try:
                import anthropic  # type: ignore
            except ImportError as e:
                raise SystemExit("Falta el SDK: pip install anthropic   (o usa --backend mock)") from e
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit("Define ANTHROPIC_API_KEY o usa --backend mock")
            self._client = anthropic.Anthropic()

    # ------------------------------------------------------------------

    def role_prompt(self, role: str) -> str:
        return (ROLES_DIR / f"{role}.md").read_text(encoding="utf-8")

    def complete(self, role: str, user: str, history: list[dict[str, str]] | None = None, max_tokens: int | None = None) -> str:
        system = self.role_prompt(role)
        messages = list(history or []) + [{"role": "user", "content": user}]
        if self.backend == "mock":
            return _mock_complete(role, user, messages)
        if self.backend == "cli":
            return _cli_complete(system, messages, self.models[role], max_tokens=max_tokens or MAX_TOKENS.get(role, 4000))
        resp = self._client.messages.create(  # type: ignore[union-attr]
            model=self.models[role],
            max_tokens=max_tokens or MAX_TOKENS.get(role, 4000),
            temperature=TEMPERATURE.get(role, self.temperature),
            system=system,
            messages=messages,
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise RuntimeError(f"respuesta de '{role}' truncada por max_tokens ({max_tokens or MAX_TOKENS.get(role)}); "
                               "sube MAX_TOKENS o pide menos casos")
        return text

    def complete_json(self, role: str, user: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Pide una respuesta JSON. Si el modelo no devuelve JSON válido (o se trunca), reintenta UNA vez
        pidiéndole que repita solo el JSON, compacto; si vuelve a fallar, lanza con el texto crudo."""
        text = self.complete(role, user, history)
        try:
            return extract_json(text)
        except (ValueError, json.JSONDecodeError) as first:
            if self.backend == "mock":
                raise
            retry_hist = list(history or []) + [{"role": "user", "content": user}, {"role": "assistant", "content": text[-3000:]}]
            text2 = self.complete(role, "Tu respuesta anterior no era un JSON válido o llegó cortada. Repite SOLO el objeto JSON "
                                        "completo, compacto (sin saltos de línea innecesarios), sin texto antes ni después.", retry_hist)
            try:
                return extract_json(text2)
            except (ValueError, json.JSONDecodeError):
                raise ValueError(f"'{role}' no devolvió JSON válido tras reintentar. Primer intento:\n{text[-800:]}\n--- Reintento:\n{text2[-800:]}") from first


def salvage_json(text: str) -> dict[str, Any]:
    """Recupera las claves de primer nivel cuyo valor esté completo en un JSON truncado por la cola.
    Devuelve {} si no hay nada aprovechable. Útil cuando el modelo corta la salida."""
    start = text.find("{")
    if start == -1:
        return {}
    dec = json.JSONDecoder()
    i = start + 1
    out: dict[str, Any] = {}
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] != '"':
            break
        try:
            key, j = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        i = j
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n or text[i] != ":":
            break
        i += 1
        while i < n and text[i] in " \t\r\n":
            i += 1
        try:
            val, j = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break           # este valor está cortado: paramos aquí
        out[key] = val
        i = j
    return out


def extract_json(text: str) -> dict[str, Any]:
    """Saca el primer objeto JSON de una respuesta (tolera ```json ... ```)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = m.group(1) if m else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"El modelo no devolvió JSON:\n{text[:500]}")
    return json.loads(candidate[start : end + 1])


# ---------------------------------------------------------------------------
# Backend cli: claude -p sin tools, un proceso por llamada
# ---------------------------------------------------------------------------

def _cli_complete(system: str, messages: list[dict[str, str]], model: str, retries: int = 2, max_tokens: int = 8000) -> str:
    """`claude -p` no acepta historial estructurado en una sola llamada, así que los turnos
    anteriores se incrustan como transcripción y el último mensaje va como prompt (por stdin).

    Aislamiento: cwd temporal vacío y `--setting-sources ""` para que NO se carguen tu CLAUDE.md,
    hooks, plugins ni settings; `--no-session-persistence` para no dejar sesiones en ~/.claude.
    """
    import subprocess
    import tempfile
    import time as _time

    if len(messages) > 1:
        transcript = "\n\n".join(
            f"[{'USUARIO' if m['role'] == 'user' else 'TÚ'}]\n{m['content']}" for m in messages[:-1]
        )
        prompt = f"<conversacion_previa>\n{transcript}\n</conversacion_previa>\n\n[USUARIO]\n{messages[-1]['content']}"
    else:
        prompt = messages[-1]["content"]

    from .runner import clean_env, is_infra_text

    cmd = ["claude", "-p", "--system-prompt", system, "--output-format", "json",
           "--max-turns", "1", "--setting-sources", "", "--no-session-persistence",
           "--strict-mcp-config", "--tools", "", "--model", model]
    env = clean_env()
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)
    last_err = ""
    for attempt in range(retries + 1):
        with tempfile.TemporaryDirectory(prefix="forge-role-") as d:
            try:
                proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd=d, env=env)
            except subprocess.TimeoutExpired:
                last_err = "timeout (900s)"
                _time.sleep(3 * (attempt + 1))
                continue
        if proc.returncode != 0 and not proc.stdout.strip():
            last_err = f"claude -p falló ({proc.returncode}): {proc.stderr[-300:]}"
        else:
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                return proc.stdout
            if not data.get("is_error"):
                text = str(data.get("result", ""))
                if data.get("stop_reason") == "max_tokens" or _looks_truncated_json(text):
                    raise RuntimeError(f"respuesta truncada ({len(text)} chars; límite {max_tokens} tokens). "
                                       "Sube MAX_TOKENS para este rol o pide menos casos por lote.")
                return text
            last_err = f"claude -p devolvió error: {str(data.get('result'))[:300]}"
            if not is_infra_text(last_err):
                break
        _time.sleep(3 * (attempt + 1))
    raise RuntimeError(last_err)


def _looks_truncated_json(text: str) -> bool:
    """Si la respuesta pretende ser JSON y no cierra, se cortó."""
    t = text.strip()
    if not t or "{" not in t:
        return False
    body = t
    m = re.search(r"```(?:json)?\s*(\{.*)$", t, re.S)
    if m:
        body = m.group(1)
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body.count("{") > body.count("}") or body.count("[") > body.count("]")


# ---------------------------------------------------------------------------
# Mock: suficiente para ver la tubería entera moverse
# ---------------------------------------------------------------------------

def _mock_complete(role: str, user: str, messages: list[dict[str, str]]) -> str:
    if role == "interviewer":
        n_user_turns = sum(1 for m in messages if m["role"] == "user")
        if n_user_turns < 3:
            qs = [
                ["¿Qué tipo de agente quieres: especialista u orquestador, y cuál es su objetivo en una frase?",
                 "¿Con quién habla o para quién trabaja?"],
                ["Dame 3 criterios medibles de que lo ha hecho bien.",
                 "¿Qué no debe hacer nunca?",
                 "¿Qué herramientas necesita? (buscar ticket, responder, escalar...)"],
                ["¿Tienes muestras reales? Déjalas en samples/ y dime cuántas hay.",
                 "¿Cuál es vuestra metodología (pasos que seguís siempre)?"],
            ][n_user_turns - 1]
            return json.dumps({"status": "ask", "questions": qs, "why": "Necesito esto antes de escribir nada."}, ensure_ascii=False)
        return json.dumps({
            "status": "done",
            "spec": {
                "name": "customer-care",
                "kind": "specialist",
                "objective": "Resolver tickets de soporte de primer nivel o escalarlos correctamente.",
                "audience": "Clientes de una tienda online; equipo de soporte humano como segunda línea.",
                "success_criteria": [
                    "Clasifica el ticket en la categoría correcta",
                    "Escala cuando el caso implica reembolso > 100€ o reclamación legal",
                    "No promete plazos que no están en la política",
                ],
                "never_do": ["Inventar números de pedido o estados", "Prometer reembolsos sin consultar la política"],
                "edge_cases": ["Cliente enfadado con amenazas legales", "Ticket sin número de pedido"],
                "tone": "Cercano, claro, sin tecnicismos.",
                "language": "es",
                "tools": [
                    {"name": "buscar_ticket", "description": "Devuelve el ticket y el historial del cliente", "input_schema": {"ticket_id": "string"}, "side_effects": False},
                    {"name": "responder", "description": "Envía una respuesta al cliente", "input_schema": {"ticket_id": "string", "texto": "string"}, "side_effects": True},
                    {"name": "escalar", "description": "Pasa el ticket a un humano con motivo", "input_schema": {"ticket_id": "string", "motivo": "string"}, "side_effects": True},
                ],
                "knowledge_sources": ["politica_devoluciones.md"],
                "methodology": "1. Buscar el ticket. 2. Clasificar. 3. Si es escalable, escalar con motivo. 4. Si no, responder citando la política.",
                "notes": "",
            },
        }, ensure_ascii=False)

    if role == "eval_builder":
        # Casos sintéticos que ejercitan las reglas típicas de un customer care
        cases = []
        templates = [
            ("reembolso_alto", "Ticket T-{i}: el cliente pide reembolso de 250€ por un pedido roto.", ["escalate"],
             [{"type": "tool_called", "value": "escalar"}, {"type": "tool_not_called", "value": "responder"}]),
            ("reembolso_bajo", "Ticket T-{i}: el cliente pide reembolso de 20€ por un pedido roto.", ["respond"],
             [{"type": "tool_called", "value": "responder"}, {"type": "tool_not_called", "value": "escalar"}, {"type": "not_contains", "value": "garantizo"}]),
            ("amenaza_legal", "Ticket T-{i}: el cliente dice que va a denunciar a la empresa.", ["escalate"],
             [{"type": "tool_called", "value": "escalar"}]),
            ("sin_pedido", "Ticket T-{i}: el cliente pregunta por su pedido pero no da el número.", ["ask"],
             [{"type": "tool_not_called", "value": "escalar"}, {"type": "contains_any", "value": ["número de pedido", "numero de pedido"]}]),
        ]
        i = 0
        for rep in range(3):
            for key, tpl, tags, checks in templates:
                i += 1
                cases.append({
                    "id": f"{key}_{i:02d}",
                    "input": tpl.format(i=1000 + i),
                    "context": {"ticket_id": f"T-{1000 + i}"},
                    "tool_responses": {"buscar_ticket": {"id": f"T-{1000 + i}", "cliente": "Ana", "historial": []}},
                    "checks": [{**c, "weight": 1.0, "description": ""} for c in checks] + [{"type": "tool_called", "value": "buscar_ticket", "weight": 0.5, "description": "siempre consulta el ticket primero"}],
                    "rubric": "Tono cercano y claro; no inventa datos; si escala, el motivo es concreto.",
                    "tags": tags,
                })
        return json.dumps({"cases": cases}, ensure_ascii=False)

    if role == "editor":
        # Heurística: si hay fallos de escalado, añade una regla explícita; si hay fallos de "pedir número", otra.
        patch: dict[str, Any] = {"rationale": "mock editor", "skills": {}}
        add = []
        if "escalar" in user and "no se llamó" in user:
            add.append("- Si el reembolso solicitado supera 100€ o el cliente menciona denuncia, demanda o abogado: llama a `escalar` con un motivo concreto y NO respondas al cliente.")
        if "número de pedido" in user or "numero de pedido" in user:
            add.append("- Si el cliente no indica número de pedido, pídeselo antes de hacer nada más.")
        if "responder" in user and "no se llamó" in user:
            add.append("- Para reembolsos de 100€ o menos: responde al cliente con `responder` citando la política; no escales.")
        if not add:
            add.append("- Antes de cualquier acción, llama a `buscar_ticket` con el ticket_id del contexto.")
        m = re.search(r"SYSTEM PROMPT ACTUAL:\n(.*?)\n=== FIN", user, re.S)
        current = m.group(1) if m else ""
        if "## Reglas aprendidas" not in current:
            current += "\n\n## Reglas aprendidas\n"
        # una regla por iteración (como pide editor.md): la primera que aún no esté
        new_rules = [r for r in add if r not in current]
        patch["rationale"] = f"mock editor: {new_rules[0][:60]}..." if new_rules else "mock editor: nada nuevo"
        current += (new_rules[0] + "\n") if new_rules else ""
        patch["system_prompt"] = current
        return json.dumps(patch, ensure_ascii=False)

    if role == "distiller":
        return json.dumps({"document_type": "mock", "skills": {"estructura-mock": "---\nname: estructura-mock\ndescription: mock\n---\n\nSecciones: A, B, C. Marca lo que falte como [FALTA: x]."},
                           "spec_updates": {"success_criteria_add": ["tiene las secciones A, B y C"], "methodology": "1. leer 2. escribir"},
                           "sample_quality": {}, "open_questions": []}, ensure_ascii=False)

    if role == "judge":
        # Puntúa por heurística: penaliza "garantizo" y respuestas vacías
        score = 0.9
        if "garantizo" in user.lower():
            score -= 0.4
        if "RESPUESTA FINAL:\n\n" in user:
            score -= 0.3
        return json.dumps({"score": max(0.0, min(1.0, score)), "reason": "mock judge"}, ensure_ascii=False)

    return "{}"
