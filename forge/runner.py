"""Fase 3: ejecutar el agente bajo prueba contra un caso y devolver una traza.

Backends:
  - api  : SDK `anthropic`, bucle de tool use manual. Las herramientas del contrato se simulan
           con `case.tool_responses`. Es el backend recomendado para afinar: barato, controlable
           y determinista en lo que devuelven las tools.
  - sdk  : `claude-agent-sdk` (motor de Claude Code). Las tools se exponen como servidor MCP
           en proceso. Útil cuando el agente final vivirá en Claude Code y quieres probarlo con
           el mismo harness (skills reales, Read/Grep, etc.).
           ⚠ Las firmas del SDK cambian; si falla, compara con la documentación actual.
  - mock : simula un agente que obedece reglas que encuentra en su system prompt. Sin red.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from .package import AgentPackage
from .schemas import TestCase, ToolCall, Trace, resolve_tool_response


class Runner:
    def __init__(self, backend: str = "api", model_override: str | None = None, retries: int = 2):
        self.backend = backend
        self.model_override = model_override
        self.retries = retries

    def run(self, pkg: AgentPackage, case: TestCase) -> Trace:
        """Ejecuta un caso. Los errores de infraestructura (red, 429, timeout, proceso caído)
        se reintentan hasta `retries` veces y, si persisten, se marcan `infra_error=True`
        para que el evaluador los excluya del cómputo en vez de contarlos como fallo del agente."""
        import time as _time

        last: Trace | None = None
        for attempt in range(self.retries + 1):
            try:
                if self.backend == "mock":
                    tr = _run_mock(pkg, case)
                elif self.backend == "api":
                    tr = _run_api(pkg, case, self.model_override)
                elif self.backend == "sdk":
                    tr = asyncio.run(_run_sdk(pkg, case, self.model_override))
                elif self.backend == "cli":
                    tr = _run_cli(pkg, case, self.model_override)
                else:
                    raise ValueError(f"backend desconocido: {self.backend}")
            except Exception as e:  # noqa: BLE001
                if not is_infra_exception(e):
                    raise                      # bug de configuración o de código: que se vea, no que se excluya
                tr = Trace(case_id=case.id, final_text="", error=f"{type(e).__name__}: {e}", raw={"infra": True})
            infra = bool(isinstance(tr.raw, dict) and tr.raw.get("infra"))
            tr.infra_error = infra
            if not infra:
                return tr
            last = tr
            if attempt < self.retries:
                _time.sleep(2 * (attempt + 1))
        return last  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# helpers comunes
# ---------------------------------------------------------------------------

# Texto de error que indica infraestructura (red, límites, auth), no un fallo del agente.
INFRA_MARKERS = ("rate limit", "rate_limit", "429", "overloaded", "529", "network", "econn", "timeout",
                 "usage limit", "limit reached", "authentication", "not logged in", "login", "unauthorized",
                 "503", "502", "internal server", "connection")
INFRA_EXCEPTIONS = ("TimeoutExpired", "ConnectionError", "APIConnectionError", "APITimeoutError", "RateLimitError",
                    "InternalServerError", "ServiceUnavailableError", "OverloadedError", "BrokenPipeError")


def is_infra_text(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in INFRA_MARKERS)


def is_infra_exception(e: BaseException) -> bool:
    return type(e).__name__ in INFRA_EXCEPTIONS or (isinstance(e, OSError) and not isinstance(e, FileNotFoundError))


def clean_env() -> dict[str, str]:
    """Entorno mínimo para `claude -p`: el agente bajo prueba no debe heredar variables de la sesión
    que lo lanza (CLAUDECODE, CLAUDE_CODE_*, etc.), solo lo necesario para ejecutarse y autenticarse."""
    import os
    keep_prefix = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
                   "SSL_CERT", "REQUESTS_CA", "NODE_EXTRA_CA", "CLAUDE_CONFIG_DIR", "ANTHROPIC_", "XDG_")
    keep = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR", "SHELL", "IS_SANDBOX"}
    return {k: v for k, v in os.environ.items() if k in keep or k.startswith(keep_prefix)}


def full_system_prompt(pkg: AgentPackage) -> str:
    """System prompt + skills inline (para backends sin noción de skill)."""
    parts = [pkg.system_prompt]
    for name, content in pkg.skills.items():
        parts.append(f"\n\n<skill name=\"{name}\">\n{content}\n</skill>")
    return "".join(parts)


def action_prompt(case: TestCase) -> str:
    ctx = json.dumps(case.context, ensure_ascii=False) if case.context else "{}"
    return f"{case.input}\n\n<contexto>\n{ctx}\n</contexto>"


def tools_as_json_schema(pkg: AgentPackage) -> list[dict[str, Any]]:
    out = []
    for t in pkg.tools:
        props = {}
        for k, v in (t.input_schema or {}).items():
            props[k] = v if isinstance(v, dict) else {"type": str(v) if v in ("string", "number", "integer", "boolean") else "string"}
        schema: dict[str, Any] = {"type": "object", "properties": props}
        if t.required:
            schema["required"] = [r for r in t.required if r in props]
        out.append({"name": t.name, "description": t.description, "input_schema": schema})
    return out


def simulate_tool(case: TestCase, name: str, inp: dict[str, Any]) -> Any:
    return resolve_tool_response(case.tool_responses, name, inp)[0]


# ---------------------------------------------------------------------------
# backend: api
# ---------------------------------------------------------------------------

def _run_api(pkg: AgentPackage, case: TestCase, model_override: str | None) -> Trace:
    import anthropic  # type: ignore

    client = anthropic.Anthropic()
    model = model_override or _resolve_model(pkg.config.get("model", "sonnet"))
    max_turns = int(pkg.config.get("max_turns", 12))
    tools = tools_as_json_schema(pkg)
    messages: list[dict[str, Any]] = [{"role": "user", "content": action_prompt(case)}]
    calls: list[ToolCall] = []
    final_text = ""

    for turn in range(1, max_turns + 1):
        kwargs: dict[str, Any] = dict(model=model, max_tokens=4000, system=full_system_prompt(pkg), messages=messages)
        if tools:
            kwargs["tools"] = tools
        resp = client.messages.create(**kwargs)
        if resp.stop_reason == "max_tokens":
            return Trace(case_id=case.id, final_text="", tool_calls=calls, turns=turn, error="respuesta del agente truncada (max_tokens=4000)")
        messages.append({"role": "assistant", "content": resp.content})
        text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if text_parts:
            final_text = "\n".join(text_parts)
        if resp.stop_reason != "tool_use" or not tool_uses:
            return Trace(case_id=case.id, final_text=final_text, tool_calls=calls, turns=turn)
        results = []
        for tu in tool_uses:
            out, is_err = resolve_tool_response(case.tool_responses, tu.name, dict(tu.input))
            calls.append(ToolCall(name=tu.name, input=dict(tu.input), output=out, is_error=is_err))
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out, ensure_ascii=False), "is_error": is_err})
        messages.append({"role": "user", "content": results})
    return Trace(case_id=case.id, final_text=final_text, tool_calls=calls, turns=max_turns, error="max_turns alcanzado")


def _resolve_model(alias: str) -> str:
    return {
        "haiku": "claude-haiku-4-5",
        "sonnet": "claude-sonnet-4-5",
        "opus": "claude-opus-4-1",
    }.get(alias, alias)


# ---------------------------------------------------------------------------
# backend: sdk (claude-agent-sdk)
# ---------------------------------------------------------------------------

async def _run_sdk(pkg: AgentPackage, case: TestCase, model_override: str | None) -> Trace:
    from claude_agent_sdk import (  # type: ignore
        query, ClaudeAgentOptions, AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
        create_sdk_mcp_server, tool,
    )

    calls: list[ToolCall] = []
    sdk_tools = []
    for t in pkg.tools:
        schema = {k: (v if isinstance(v, type) else str) for k, v in (t.input_schema or {}).items()}

        def make(tname: str):
            async def handler(args: dict[str, Any]) -> dict[str, Any]:
                out = simulate_tool(case, tname, args)
                calls.append(ToolCall(name=tname, input=dict(args), output=out))
                return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
            return handler

        sdk_tools.append(tool(t.name, t.description, schema)(make(t.name)))

    server = create_sdk_mcp_server(name="forge", version="1.0.0", tools=sdk_tools)
    options = ClaudeAgentOptions(
        system_prompt=full_system_prompt(pkg),
        mcp_servers={"forge": server},
        allowed_tools=[f"mcp__forge__{t.name}" for t in pkg.tools],
        max_turns=int(pkg.config.get("max_turns", 12)),
        model=model_override or pkg.config.get("model"),
        permission_mode="bypassPermissions",
    )

    final_text = ""
    turns = 0
    async for msg in query(prompt=action_prompt(case), options=options):
        if isinstance(msg, AssistantMessage):
            turns += 1
            for block in msg.content:
                if isinstance(block, TextBlock):
                    final_text = block.text
                elif isinstance(block, ToolUseBlock):
                    pass  # las llamadas se registran en el handler
        elif isinstance(msg, ResultMessage):
            if getattr(msg, "result", None):
                final_text = msg.result
    return Trace(case_id=case.id, final_text=final_text, tool_calls=calls, turns=turns)


# ---------------------------------------------------------------------------
# backend: cli (claude -p, modo headless de Claude Code; usa tu suscripción, no API key)
# ---------------------------------------------------------------------------

def _run_cli(pkg: AgentPackage, case: TestCase, model_override: str | None) -> Trace:
    """Lanza `claude -p` con el system prompt del paquete y las tools del contrato servidas
    por forge/mcp_sim.py como servidor MCP stdio. Las llamadas quedan en un log por caso."""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="forge-") as d:
        d = Path(d)
        log = d / "calls.jsonl"
        log.touch()
        case_file = d / "case.json"
        case_file.write_text(json.dumps({
            "tools": [t.__dict__ for t in pkg.tools],
            "tool_responses": case.tool_responses,
            "trace_log": str(log),
        }, ensure_ascii=False), encoding="utf-8")
        mcp_cfg = d / "mcp.json"
        mcp_cfg.write_text(json.dumps({"mcpServers": {"forge": {
            "command": sys.executable, "args": ["-m", "forge.mcp_sim", str(case_file)],
            "env": {"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        }}}), encoding="utf-8")

        # Skills como skills REALES de Claude Code (carga condicional, como en producción),
        # en un proyecto temporal vacío: sin tu CLAUDE.md, hooks ni plugins (--setting-sources project).
        tools_flag: list[str] = []
        if pkg.skills:
            for name, content in pkg.skills.items():
                sk = d / ".claude" / "skills" / name
                sk.mkdir(parents=True, exist_ok=True)
                (sk / "SKILL.md").write_text(content, encoding="utf-8")
            tools_flag = ["Skill"]
        system_prompt = pkg.system_prompt if pkg.skills else full_system_prompt(pkg)
        if pkg.skills:
            system_prompt += ("\n\n## Skills\nTienes skills disponibles (herramienta Skill). Cárgalas cuando su descripción "
                              "encaje con la tarea: " + ", ".join(f"`{n}`" for n in pkg.skills) + ".")
        if len(system_prompt.encode()) > 120_000:
            return Trace(case.id, "", [], 0, error="system prompt > 120 KB: no cabe en un argumento de línea de comandos; mueve contenido a skills")

        cmd = [
            "claude", "-p",                                  # el prompt de acción va por stdin
            "--system-prompt", system_prompt,
            "--output-format", "json",
            "--max-turns", str(int(pkg.config.get("max_turns", 12))),
            "--setting-sources", "project",                  # aislamiento: nada del usuario
            "--no-session-persistence",
            "--strict-mcp-config",
            "--tools", *(tools_flag or [""]),               # sin tools nativas salvo Skill
        ]
        # Sin bypassPermissions: en modo -p, las tools de --allowedTools se permiten sin preguntar y no
        # existe ninguna otra, así que no hace falta (y bypass falla como root sin IS_SANDBOX).
        allowed = [f"mcp__forge__{t.name}" for t in pkg.tools] + tools_flag
        if pkg.tools:                                        # sin tools no hay servidor MCP
            cmd += ["--mcp-config", str(mcp_cfg)]
        if allowed:
            cmd += ["--allowedTools", *allowed]
        model = model_override or pkg.config.get("model")
        if model:
            cmd += ["--model", str(model)]
        timeout_s = int(pkg.config.get("timeout_s", 300))

        def read_calls() -> list[ToolCall]:
            out = []
            for line in log.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    c = json.loads(line)
                    out.append(ToolCall(c["name"], c["input"], c.get("output"), bool(c.get("is_error"))))
            return out

        try:
            proc = subprocess.run(cmd, input=action_prompt(case), capture_output=True, text=True,
                                  timeout=timeout_s, cwd=str(d), env=clean_env())
        except subprocess.TimeoutExpired:
            return Trace(case.id, "", read_calls(), 0, error=f"timeout tras {timeout_s}s (config.timeout_s)", raw={"infra": True})

        calls = read_calls()
        if proc.returncode != 0 and not proc.stdout.strip():
            return Trace(case.id, "", calls, 0, error=f"claude -p salió con {proc.returncode}: {proc.stderr[-500:]}", raw={"infra": True})
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return Trace(case.id, proc.stdout.strip(), calls, 0, error="salida no JSON", raw={"infra": True, "stdout": proc.stdout[-1000:]})
        return parse_cli_result(case.id, data, calls)


def parse_cli_result(case_id: str, data: dict[str, Any], calls: list[ToolCall]) -> Trace:
    """Convierte el JSON de `claude -p --output-format json` en una traza."""
    err = None
    infra = False
    final_text = str(data.get("result", "") or "")
    if data.get("is_error"):
        err = final_text[:300]
        final_text = ""                        # el texto de un error nunca es "la respuesta del agente"
        infra = is_infra_text(err)
    elif data.get("subtype") not in (None, "success", "error_max_turns"):
        err = f"subtype={data.get('subtype')}"
        infra = True
    return Trace(case_id, final_text, calls, int(data.get("num_turns", 0)), error=err,
                 raw={"infra": infra, "cost_usd": data.get("total_cost_usd"), "subtype": data.get("subtype")})


# ---------------------------------------------------------------------------
# backend: mock — agente de juguete que obedece reglas del prompt
# ---------------------------------------------------------------------------

def _run_mock(pkg: AgentPackage, case: TestCase) -> Trace:
    """Simula un agente mediocre que mejora si el prompt contiene reglas explícitas.

    Reglas que 'entiende' (buscando frases en el system prompt):
      - 'llama a `buscar_ticket`'  -> siempre consulta el ticket primero
      - 'supera 100€'              -> escala reembolsos altos / amenazas legales
      - 'no indica número de pedido' -> pide el número antes de actuar
      - '100€ o menos'             -> responde a reembolsos bajos sin escalar
    Sin esas reglas, actúa por impulso y acierta a medias.
    """
    sp = full_system_prompt(pkg).lower()
    text = case.input.lower()
    calls: list[ToolCall] = []
    tid = case.context.get("ticket_id", "T-?")

    knows_lookup = "llama a `buscar_ticket`" in sp or "buscar el ticket" in sp
    knows_escalate = "supera 100€" in sp
    knows_ask = "no indica número de pedido" in sp
    knows_respond_low = "100€ o menos" in sp

    if knows_lookup:
        calls.append(ToolCall("buscar_ticket", {"ticket_id": tid}, simulate_tool(case, "buscar_ticket", {})))

    amount = _amount(text)
    legal = any(w in text for w in ("denunci", "demanda", "abogado"))
    no_order = "no da el número" in text or "sin número" in text

    if no_order:
        if knows_ask:
            return Trace(case.id, "Para poder ayudarte necesito tu número de pedido, ¿me lo indicas?", calls, 1)
        calls.append(ToolCall("escalar", {"ticket_id": tid, "motivo": "no sé qué hacer"}, simulate_tool(case, "escalar", {})))
        return Trace(case.id, "He escalado tu caso.", calls, 1)

    if (amount is not None and amount > 100) or legal:
        if knows_escalate:
            calls.append(ToolCall("escalar", {"ticket_id": tid, "motivo": f"reembolso {amount}€" if amount else "amenaza legal"}, simulate_tool(case, "escalar", {})))
            return Trace(case.id, "He pasado tu caso a un compañero que te contactará en breve.", calls, 1)
        calls.append(ToolCall("responder", {"ticket_id": tid, "texto": "Te garantizo el reembolso completo hoy mismo."}, simulate_tool(case, "responder", {})))
        return Trace(case.id, "Te garantizo el reembolso completo hoy mismo.", calls, 1)

    # reembolso bajo
    if knows_respond_low:
        calls.append(ToolCall("responder", {"ticket_id": tid, "texto": "Según nuestra política, tramitamos el reembolso en 5 días."}, simulate_tool(case, "responder", {})))
        return Trace(case.id, "Según nuestra política, tramitamos el reembolso en 5 días.", calls, 1)
    calls.append(ToolCall("escalar", {"ticket_id": tid, "motivo": "por si acaso"}, simulate_tool(case, "escalar", {})))
    return Trace(case.id, "He escalado tu caso por si acaso.", calls, 1)


def _amount(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*€", text)
    return float(m.group(1).replace(",", ".")) if m else None
