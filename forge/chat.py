"""Banco de pruebas conversacional: habla con el agente del paquete actual.

Usa `claude -p --resume` para mantener la conversación entre turnos, con el mismo aislamiento que el
runner (cwd temporal, --setting-sources project, skills reales en .claude/skills/, tools del contrato
servidas por mcp_sim). Las respuestas de las tools se simulan: por defecto devuelven un eco, o puedes
cargar un "mundo" (JSON con tool_responses) para que respondan datos concretos.

Comandos dentro del chat:
  /tools                 llamadas a tools del último turno (input y output)
  /world <ruta.json>     carga respuestas simuladas para las tools ({"buscar_ticket": {...}, ...})
  /save <id> [tags]      guarda el último intercambio como caso de prueba en evals/cases.json
  /version <vNNN>        cambia a otra versión del paquete (reinicia la conversación)
  /reset                 reinicia la conversación con el mismo paquete
  /system                muestra el system prompt en uso
  /help                  esta ayuda
  /salir
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .evals import load_cases, save_cases
from .package import AgentPackage, Workspace
from .runner import clean_env, parse_cli_result
from .schemas import Check, TestCase, ToolCall, Trace


class ChatSession:
    def __init__(self, ws: Workspace, pkg: AgentPackage, model: str | None = None, label: str = "current"):
        self.ws = ws
        self.pkg = pkg
        self.model = model or pkg.config.get("model")
        self.label = label
        self.world: dict = {}
        self.session_id: str | None = None
        self.turns: list[dict] = []          # {"user":..., "assistant":..., "tools":[...]}
        self.dir = Path(tempfile.mkdtemp(prefix="forge-chat-"))
        self.log = self.dir / "calls.jsonl"
        self._prepare_dir()

    def _prepare_dir(self) -> None:
        if self.pkg.skills:
            for name, content in self.pkg.skills.items():
                d = self.dir / ".claude" / "skills" / name
                d.mkdir(parents=True, exist_ok=True)
                (d / "SKILL.md").write_text(content, encoding="utf-8")
        self._write_world()

    def _write_world(self) -> None:
        self.log.touch()
        (self.dir / "case.json").write_text(json.dumps({
            "tools": [t.__dict__ for t in self.pkg.tools],
            "tool_responses": self.world,
            "trace_log": str(self.log),
        }, ensure_ascii=False), encoding="utf-8")
        (self.dir / "mcp.json").write_text(json.dumps({"mcpServers": {"forge": {
            "command": sys.executable, "args": ["-m", "forge.mcp_sim", str(self.dir / "case.json")],
            "env": {"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        }}}), encoding="utf-8")

    def system_prompt(self) -> str:
        sp = self.pkg.system_prompt
        if self.pkg.skills:
            sp += ("\n\n## Skills\nTienes skills disponibles (herramienta Skill). Cárgalas cuando su descripción "
                   "encaje con la tarea: " + ", ".join(f"`{n}`" for n in self.pkg.skills) + ".")
        return sp

    def send(self, text: str) -> tuple[str, list[ToolCall], str | None]:
        before = len(self.log.read_text(encoding="utf-8").splitlines()) if self.log.exists() else 0
        cmd = ["claude", "-p", "--system-prompt", self.system_prompt(), "--output-format", "json",
               "--max-turns", str(int(self.pkg.config.get("max_turns", 12)) * 2),
               "--setting-sources", "project", "--strict-mcp-config",
               "--tools", *(["Skill"] if self.pkg.skills else [""])]
        allowed = [f"mcp__forge__{t.name}" for t in self.pkg.tools] + (["Skill"] if self.pkg.skills else [])
        if self.pkg.tools:
            cmd += ["--mcp-config", str(self.dir / "mcp.json")]
        if allowed:
            cmd += ["--allowedTools", *allowed]
        if self.model:
            cmd += ["--model", str(self.model)]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        else:
            self.session_id = str(uuid.uuid4())
            cmd += ["--session-id", self.session_id]
        try:
            proc = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=600,
                                  cwd=str(self.dir), env=clean_env())
        except subprocess.TimeoutExpired:
            return "", [], "timeout (600s)"
        calls = []
        for line in self.log.read_text(encoding="utf-8").splitlines()[before:]:
            if line.strip():
                c = json.loads(line)
                calls.append(ToolCall(c["name"], c["input"], c.get("output"), bool(c.get("is_error"))))
        if proc.returncode != 0 and not proc.stdout.strip():
            return "", calls, f"claude -p salió con {proc.returncode}: {proc.stderr[-400:]}"
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.stdout.strip(), calls, "salida no JSON"
        if data.get("session_id"):
            self.session_id = data["session_id"]
        tr = parse_cli_result("chat", data, calls)
        self.turns.append({"user": text, "assistant": tr.final_text, "tools": [c.__dict__ for c in calls],
                           "error": tr.error, "cost": (tr.raw or {}).get("cost_usd")})
        return tr.final_text, calls, tr.error

    def reset(self) -> None:
        self.session_id = None
        self.turns = []
        self.log.write_text("", encoding="utf-8")

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def _print_tools(calls: list[ToolCall]) -> None:
    if not calls:
        print("  (sin llamadas a tools)")
    for c in calls:
        print(f"  → {c.name}({json.dumps(c.input, ensure_ascii=False)[:400]})")
        print(f"    ← {json.dumps(c.output, ensure_ascii=False)[:300]}" + ("  [ERROR]" if c.is_error else ""))


def _save_case(ws: Workspace, sess: ChatSession, case_id: str, tags: list[str]) -> None:
    if not sess.turns:
        print("No hay ningún intercambio que guardar."); return
    last = sess.turns[-1]
    # el input del caso es el último mensaje; si hubo turnos previos, van como contexto
    ctx = {"conversacion_previa": [{"user": t["user"], "assistant": t["assistant"][:600]} for t in sess.turns[:-1]]} if len(sess.turns) > 1 else {}
    checks = []
    for name in sorted({c["name"] for c in last["tools"]}):
        checks.append(Check("tool_called", name, 1.0, False, "se llamó en el chat; revisa si es lo que debe pasar"))
    print("\nRevisa el caso: ¿qué DEBERÍA pasar? Los checks de abajo describen lo que pasó, no lo que debe pasar.")
    print("  Edítalos luego en evals/cases.json. Rúbrica para el juez (Enter para ninguna):")
    try:
        rubric = input("  rúbrica> ").strip()
    except EOFError:
        rubric = ""
    case = TestCase(id=case_id, input=last["user"], context=ctx, tool_responses=dict(sess.world),
                    checks=checks, rubric=rubric, tags=tags or ["chat"], split="fit", source="manual")
    cases = load_cases(ws) if ws.cases_path.exists() else []
    cases.append(case)
    save_cases(ws, cases)
    print(f"Guardado como '{case.id}' en {ws.cases_path} (split fit). Añade checks de lo que DEBE pasar y, si quieres, critical: true.")


def run_chat(ws: Workspace, model: str | None = None, version: str | None = None, world: str | None = None) -> None:
    if not shutil.which("claude"):
        raise SystemExit("El chat usa Claude Code (`claude -p --resume`). Instálalo y haz login.")
    pkg = AgentPackage.load(ws.versions_dir / version) if version else ws.load_package()
    sess = ChatSession(ws, pkg, model, version or "current")
    if world:
        sess.world = json.loads(Path(world).read_text(encoding="utf-8"))
        sess._write_world()
    print(f"\n=== Chat con {pkg.name} [{sess.label}] | modelo {sess.model} | skills: {', '.join(pkg.skills) or '-'} | "
          f"tools: {', '.join(t.name for t in pkg.tools) or '-'} ===")
    print("Las tools devuelven datos simulados (eco, o los de /world). /help para comandos. Respuestas multilínea: termina con línea vacía.\n")
    try:
        while True:
            try:
                print("tú> ", end="", flush=True)
                lines = []
                while True:
                    line = input()
                    if not line.strip() and lines:
                        break
                    if not line.strip():
                        continue
                    lines.append(line)
                    if line.startswith("/") and len(lines) == 1:
                        break
                text = "\n".join(lines).strip()
            except EOFError:
                break
            if not text:
                continue
            if text.startswith("/"):
                parts = text.split()
                cmd, args = parts[0].lower(), parts[1:]
                if cmd in {"/salir", "/exit", "/quit"}:
                    break
                elif cmd == "/help":
                    print(__doc__)
                elif cmd == "/tools":
                    _print_tools([ToolCall(**c) for c in (sess.turns[-1]["tools"] if sess.turns else [])])
                elif cmd == "/system":
                    print(sess.system_prompt())
                elif cmd == "/reset":
                    sess.reset(); print("conversación reiniciada")
                elif cmd == "/world" and args:
                    try:
                        sess.world = json.loads(Path(args[0]).read_text(encoding="utf-8"))
                        sess._write_world(); print(f"mundo cargado: tools con respuesta fija: {sorted(sess.world)}")
                    except Exception as e:  # noqa: BLE001
                        print(f"no se pudo cargar: {e}")
                elif cmd == "/save" and args:
                    _save_case(ws, sess, args[0], args[1:])
                elif cmd == "/version" and args:
                    try:
                        pkg = AgentPackage.load(ws.versions_dir / args[0]) if args[0] != "current" else ws.load_package()
                    except Exception as e:  # noqa: BLE001
                        print(f"no existe: {e}"); continue
                    sess.close(); sess = ChatSession(ws, pkg, model, args[0]); print(f"ahora hablas con {args[0]} ({pkg.summary()})")
                else:
                    print("comando desconocido; /help")
                continue
            reply, calls, err = sess.send(text)
            if calls:
                print(f"  [{len(calls)} tool call{'s' if len(calls) > 1 else ''}: {', '.join(c.name for c in calls)}]  (/tools para ver)")
            if err:
                print(f"  [error: {err}]")
            print(f"\n{pkg.name}> {reply}\n")
    finally:
        if sess.turns:
            out = ws.root / "chats"
            out.mkdir(exist_ok=True)
            import time as _time
            f = out / f"chat-{sess.label}-{_time.strftime('%Y%m%d-%H%M%S')}.json"
            f.write_text(json.dumps({"version": sess.label, "model": sess.model, "world": sess.world, "turns": sess.turns},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
            cost = sum((t.get("cost") or 0) for t in sess.turns)
            print(f"\nTranscripción guardada en {f}" + (f"  (coste aprox. {cost:.3f} USD)" if cost else ""))
        sess.close()
