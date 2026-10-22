"""CLI: forge <comando> <workspace> [opciones]

  init        crea la estructura del workspace
  interview   entrevista interactiva → spec.json  (--resume para continuar una interrumpida)
  distill     ingeniería inversa de samples/ → skills de estructura/metodología/estilo + spec mejorada
  package     genera package/ v0 a partir de spec.json (y lo deja listo para afinar)
  build-evals construye evals/cases.json a partir de spec + samples/
  run         evalúa el package actual (sin modificar nada)
  train       bucle completo de afinado
  export      zip portátil del agente
  export-tools genera un servidor MCP REAL (stdio, sin dependencias) para el contrato de tools, sobre carpetas locales
  install     instala el paquete en el proyecto actual: .claude/agents/, .claude/skills/, servidor MCP y .mcp.json
  demo        todo lo anterior en modo mock, sin API, para ver la tubería
  ui          interfaz de consola: chat + casos + versiones + log, en pestañas (curses, sin dependencias)
  chat        banco de pruebas en texto plano: conversa con el agente; /save guarda un caso
  cases       lista los casos (revísalos antes de afinar)
  lint-cases  detecta checks propensos a falsos positivos (prohibiciones sin scope, regex rotas); --fix los corrige
  history     versiones aceptadas con motivo y puntuaciones
  diff        diff de prompt/skills entre dos versiones
  show        traza completa de un caso en un run
  compare     tabla caso a caso entre dos runs
  rollback    vuelve a una versión anterior
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evals import build_cases, load_cases, save_cases
from .interview import run_interview, run_interview_scripted
from .llm import LLM
from .loop import TrainConfig, Trainer
from .package import AgentPackage, Workspace
from .runner import Runner


def _llm(args) -> LLM:
    return LLM(backend=args.backend)


def _runner(args) -> Runner:
    rb = args.runner
    if args.backend == "mock" and rb != "mock":
        print(f"[aviso] --backend mock fuerza --runner mock (pediste {rb})")
        rb = "mock"
    return Runner(backend=rb, model_override=getattr(args, "model", None))


def cmd_init(args):
    ws = Workspace(args.workspace); ws.init()
    print(f"Workspace en {ws.root}. Siguiente: forge interview {ws.root}")


def cmd_interview(args):
    ws = Workspace(args.workspace)
    run_interview(ws, _llm(args), args.describe or "", resume=args.resume, max_turns=args.max_turns)


def cmd_distill(args):
    from .distill import run_distill, apply_distill_output
    ws = Workspace(args.workspace)
    if args.from_raw:
        from .llm import extract_json, salvage_json
        text = (ws.root / "distill.raw.txt").read_text(encoding="utf-8")
        try:
            data = extract_json(text)
        except (ValueError, Exception):
            data = salvage_json(text)
        print(f"recuperado de distill.raw.txt: {sorted(data)}")
        apply_distill_output(ws, data)
        return
    if args.sections and not args.full_pass:
        from .distill import refine_sections
        refine_sections(ws, _llm(args), [x.strip() for x in args.sections.split(",")], ws.load_samples())
        return
    run_distill(ws, _llm(args), max_samples=args.max_samples, n_full=args.full,
                focus=[x.strip() for x in args.sections.split(",")] if args.sections else None)


def cmd_package(args):
    ws = Workspace(args.workspace)
    spec = ws.load_spec()
    if ws.package_dir.joinpath("agent.md").exists() and not args.force:
        sys.exit("package/ ya existe (quizá lo creó `distill`). Usa --force para regenerarlo desde la spec (perderás los cambios).")
    old_skills = ws.load_package().skills if ws.package_dir.joinpath("agent.md").exists() else {}
    pkg = AgentPackage.initial_from_spec(spec)
    pkg.skills.update(old_skills)          # conserva las skills destiladas
    if old_skills and "## Skills" not in pkg.system_prompt:
        pkg.system_prompt += ("\n\n## Skills\nAntes de producir un documento carga las skills que correspondan: "
                              + ", ".join(f"`{n}`" for n in old_skills) + ". Sigue su estructura y metodología al pie de la letra.")
    ws.save_package(pkg)
    print(f"Paquete inicial creado: {pkg.summary()}\nEdita {ws.package_dir / 'agent.md'} si quieres partir de tu propio prompt.")


def cmd_build_evals(args):
    ws = Workspace(args.workspace)
    cases = build_cases(ws, _llm(args), n_cases=args.n, validation_ratio=args.val_ratio, test_ratio=args.test_ratio)
    counts = {s: sum(1 for c in cases if c.split == s) for s in ("fit", "validation", "test")}
    print(f"{len(cases)} casos ({counts['fit']} fit / {counts['validation']} validation / {counts['test']} test) → {ws.cases_path}")
    print("Revísalos: una batería mala afina hacia el sitio equivocado.")


def cmd_lint_cases(args):
    """Avisa de checks que suelen producir falsos positivos."""
    import re as _re
    ws = Workspace(args.workspace)
    cases = load_cases(ws)
    problems = 0
    risky = ("todo", "descuento", "enviado", "desarrollado", "%", "€", r"\d{3}")
    for c in cases:
        for ch in c.checks:
            v = ch.value; pat = v.get("text") if isinstance(v, dict) else v
            scope = v.get("scope") if isinstance(v, dict) else None
            if ch.type in ("not_contains", "regex_absent") and scope is None:
                print(f"[{c.id}] {ch.type}={str(pat)[:50]!r}: prohibición SIN scope → mira también el resumen al humano; añade scope:'tools'"); problems += 1
            if ch.type in ("regex", "regex_absent") and isinstance(pat, str):
                try: _re.compile(pat)
                except _re.error as e: print(f"[{c.id}] regex inválida {pat[:50]!r}: {e}"); problems += 1; continue
                if ch.type == "regex_absent" and _re.search(r"(?<!\\b)\bTODO\b|\\bTODO\\b", pat):
                    print(f"[{c.id}] regex_absent con TODO: con re.I casa 'todo' en castellano; usa 'TODO:' o quítalo"); problems += 1
            if ch.type == "regex_absent" and isinstance(pat, str) and any(r in pat.lower() for r in risky) and ch.critical:
                print(f"[{c.id}] crítico con patrón de riesgo {pat[:50]!r}: comprueba que no aparezca en el texto fijo de las skills")
    print(f"\n{len(cases)} casos revisados, {problems} problemas.")
    if args.fix:
        changed = 0
        for c in cases:
            for ch in c.checks:
                v = ch.value
                if ch.type in ("not_contains", "regex_absent") and not (isinstance(v, dict) and "scope" in v):
                    ch.value = {"text": v, "scope": "tools"} if not isinstance(v, dict) else {**v, "scope": "tools"}; changed += 1
                if ch.type == "regex_absent":
                    pat = ch.value.get("text") if isinstance(ch.value, dict) else ch.value
                    if isinstance(pat, str) and "TODO" in pat:
                        ch.value["text"] = pat.replace("|\\bTODO\\b", "").replace("\\bTODO\\b|", "").replace("|TODO", "").replace("TODO|", "")
        save_cases(ws, cases); print(f"--fix: {changed} prohibiciones ahora con scope:'tools'")


def cmd_cases(args):
    """Lista los casos para revisarlos antes de afinar."""
    ws = Workspace(args.workspace)
    cases = load_cases(ws, None if args.split == "all" else args.split)
    if args.tag:
        cases = [c for c in cases if args.tag in c.tags]
    for c in cases:
        print(f"[{c.split:10}] {c.id:28} tags={','.join(c.tags) or '-':20} src={c.source}")
        print(f"   input : {c.input[:140]}")
        if args.verbose:
            print(f"   checks: " + "; ".join(f"{ch.type}={ch.value!r}" + (f" (w{ch.weight})" if ch.weight != 1 else "") for ch in c.checks))
            if c.rubric:
                print(f"   rubric: {c.rubric[:140]}")
    print(f"\n{len(cases)} casos. Edita {ws.cases_path} para corregir o borrar los que no midan lo que quieres.")


def cmd_history(args):
    """Versiones aceptadas con su motivo y sus puntuaciones."""
    import json as _json
    ws = Workspace(args.workspace)
    versions = sorted(p for p in ws.versions_dir.glob("v*") if p.is_dir())
    if not versions:
        print("Sin versiones todavía."); return
    print(f"{'versión':8} {'fit':>14} {'validation':>14}  cambio   (casos que pasan / media)")
    for v in versions:
        meta = _json.loads((v / "meta.json").read_text()) if (v / "meta.json").exists() else {}
        def score(split):
            f = ws.runs_dir / f"{v.name}-{split}.json"
            if not f.exists():
                return "-"
            d = _json.loads(f.read_text())
            return f"{d.get('case_pass_rate', d['pass_rate']):.0%} / {d['mean_score']:.3f}"
        print(f"{v.name:8} {score('fit'):>14} {score('validation'):>14}  {meta.get('rationale', '(inicial)')[:70]}")
    print(f"\nCompara dos versiones con: forge diff {ws.root} v001 v002")


def cmd_diff(args):
    """Diff del system prompt y las skills entre dos versiones."""
    import difflib
    ws = Workspace(args.workspace)
    a = AgentPackage.load(ws.versions_dir / args.a)
    b = AgentPackage.load(ws.versions_dir / args.b) if args.b != "current" else ws.load_package()
    def show(title, ta, tb):
        d = list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), f"{args.a}/{title}", f"{args.b}/{title}", lineterm="", n=2))
        if d:
            print("\n".join(d)); print()
    show("system_prompt", a.system_prompt, b.system_prompt)
    for name in sorted(set(a.skills) | set(b.skills)):
        show(f"skills/{name}", a.skills.get(name, ""), b.skills.get(name, ""))
    if a.config != b.config:
        print(f"config: {a.config} → {b.config}")


def cmd_show(args):
    """Traza completa de un caso en un run."""
    import json as _json
    ws = Workspace(args.workspace)
    f = ws.runs_dir / f"{args.run}.json"
    if not f.exists():
        sys.exit(f"No existe {f}. Runs disponibles: " + ", ".join(p.stem for p in sorted(ws.runs_dir.glob('*.json'))))
    d = _json.loads(f.read_text())
    rs = [r for r in d["results"] if r["case_id"] == args.case] if args.case else d["results"]
    if not rs:
        sys.exit(f"Caso {args.case} no está en {args.run}")
    for r in rs:
        print(f"=== {r['case_id']} run {r['run']}  score={r['score']}  passed={r['passed']}"
              + ("  CRÍTICO" if r.get("critical_failed") else "") + ("  INFRA-ERROR" if r.get("infra_error") else ""))
        tr = r.get("trace") or {}
        for c in tr.get("tool_calls", []):
            print(f"  → {c['name']}({_json.dumps(c['input'], ensure_ascii=False)})")
            print(f"    ← {_json.dumps(c.get('output'), ensure_ascii=False)[:300]}" + ("  [ERROR]" if c.get("is_error") else ""))
        print(f"  respuesta final:\n    " + (tr.get("final_text") or "").replace("\n", "\n    "))
        if tr.get("error"):
            print(f"  error: {tr['error']}")
        for c in r["checks"]:
            print(f"  [{'✓' if c['passed'] else '✗'}] {c['type']}" + (f": {c['detail']}" if c["detail"] else "") + (" (crítico)" if c.get("critical") else ""))
        if r.get("judge_score") is not None:
            print(f"  juez: {r['judge_score']} — {r['judge_reason']}")
        print()


def cmd_compare(args):
    """Tabla caso a caso entre dos runs."""
    import json as _json
    ws = Workspace(args.workspace)
    def load(name):
        f = ws.runs_dir / f"{name}.json"
        if not f.exists():
            sys.exit(f"No existe {f}")
        d = _json.loads(f.read_text())
        agg: dict[str, list[float]] = {}
        for r in d["results"]:
            if not r.get("infra_error"):
                agg.setdefault(r["case_id"], []).append(r["score"])
        return {k: sum(v) / len(v) for k, v in agg.items()}
    a, b = load(args.a), load(args.b)
    common = sorted(set(a) & set(b))
    print(f"{'caso':30} {args.a[:14]:>14} {args.b[:14]:>14} {'Δ':>7}")
    for c in sorted(common, key=lambda c: b[c] - a[c]):
        d = b[c] - a[c]
        mark = " ✗ empeora" if d < -0.15 else " ✓ mejora" if d > 0.15 else ""
        print(f"{c:30} {a[c]:14.2f} {b[c]:14.2f} {d:+7.2f}{mark}")
    ma, mb = sum(a[c] for c in common) / len(common), sum(b[c] for c in common) / len(common)
    print(f"\n{'media':30} {ma:14.3f} {mb:14.3f} {mb - ma:+7.3f}   ({len(common)} casos comunes)")


def cmd_rollback(args):
    """Vuelve a una versión anterior como package/ actual."""
    import shutil
    ws = Workspace(args.workspace)
    src = ws.versions_dir / args.version
    if not (src / "agent.md").exists():
        sys.exit(f"No existe la versión {args.version}")
    pkg = AgentPackage.load(src)
    ws.save_package(pkg)
    v = ws.next_version()
    ws.snapshot(pkg, v, {"rationale": f"rollback a {args.version}"})
    print(f"package/ ahora es {args.version} (snapshot como {v})")


def cmd_ui(args):
    from .tui import run_ui
    run_ui(Workspace(args.workspace), model=args.model)


def cmd_chat(args):
    from .chat import run_chat
    run_chat(Workspace(args.workspace), model=args.model, version=args.version, world=args.world)


def cmd_run(args):
    ws = Workspace(args.workspace)
    cfg = TrainConfig(runs_per_case=args.runs, use_judge=not args.no_judge, parallel=args.parallel)
    tr = Trainer(ws, _llm(args), _runner(args), cfg)
    pkg = ws.load_package()
    import time as _time
    version = args.label or f"run-{_time.strftime('%Y%m%d-%H%M%S')}"
    for split in (["fit", "validation", "test"] if args.split == "all" else [args.split]):
        if not load_cases(ws, split):
            continue
        rep = tr.evaluate(pkg, version, split)
        print(f"  {split}: casos que pasan={rep.case_pass_rate:.0%} media={rep.mean_score:.3f}"
              + (f" (ejecuciones que pasan={rep.pass_rate:.0%})" if args.runs > 1 else ""))
        for r in rep.failures()[: args.show]:
            print(f"    ✗ {r.case_id} ({r.score:.2f}{', CRÍTICO' if r.critical_failed else ''}): "
                  + "; ".join(c.detail for c in r.checks if not c.passed)[:200])
    print(f"\nTrazas completas en {ws.runs_dir}/{version}-<split>.json  (forge show {ws.root} {version}-fit <caso>)")


def cmd_train(args):
    ws = Workspace(args.workspace)
    cfg = TrainConfig(
        max_iterations=args.iterations, patience=args.patience, target_pass_rate=args.target,
        runs_per_case=args.runs, holdout_every=args.holdout_every, ask_every=args.ask_every,
        use_judge=not args.no_judge, parallel=args.parallel,
    )
    Trainer(ws, _llm(args), _runner(args), cfg).train()


def cmd_export_tools(args):
    """Genera un servidor MCP stdio REAL para el contrato de tools del paquete, sobre carpetas locales.

    Sirve para probar el agente en Claude Code tal cual se evaluó: mismos nombres de tools.
    Implementa tools de archivo (listar/leer/guardar) de forma genérica; las demás quedan como
    stubs que devuelven 'no implementada' para que las completes.
    """
    ws = Workspace(args.workspace)
    pkg = ws.load_package()
    server = pkg.config.get("mcp_server", "forge")
    out_dir = Path(args.out or "mcp"); out_dir.mkdir(parents=True, exist_ok=True)
    py = out_dir / f"{server}_mcp.py"
    tools_json = json.dumps(json.dumps([t.__dict__ for t in pkg.tools], ensure_ascii=False))   # literal de cadena Python
    py.write_text(_MCP_TEMPLATE.replace("__TOOLS__", f"json.loads({tools_json})").replace("__SERVER__", server)
                  .replace("__IN__", args.input_dir).replace("__OUT__", args.output_dir), encoding="utf-8")
    cfg_path = Path(".mcp.json")
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {"mcpServers": {}}
    cfg.setdefault("mcpServers", {})[server] = {"command": "python3", "args": [str(py)]}
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Servidor MCP '{server}' en {py}; registrado en {cfg_path}.")
    print(f"Tools: {', '.join(t.name for t in pkg.tools)}. Fuentes: {args.input_dir}/  Salida: {args.output_dir}/")
    print("Revisa los stubs marcados TODO si alguna tool no es de archivo. Reinicia Claude Code para que cargue el servidor.")


_MCP_TEMPLATE = r'''"""Servidor MCP stdio para el contrato de tools de un agente afinado con Agent Forge.
Generado por `forge export-tools`. Sin dependencias. Solo lee de IN_DIR y escribe en OUT_DIR."""
import json, os, sys
from pathlib import Path

TOOLS = __TOOLS__
IN_DIR = Path("__IN__").resolve()
OUT_DIR = Path("__OUT__").resolve()


def _safe(base: Path, name: str) -> Path:
    p = (base / name).resolve()
    if base not in p.parents and p != base:
        raise ValueError("ruta fuera de la carpeta permitida")
    return p


def handle(name: str, args: dict):
    """Implementación genérica por nombre. Edita aquí lo que no encaje con tu caso."""
    low = name.lower()
    if low.startswith(("listar", "list")):
        IN_DIR.mkdir(parents=True, exist_ok=True)
        items = []
        for f in sorted(IN_DIR.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                import datetime
                items.append({"nombre": f.name, "fecha": datetime.date.fromtimestamp(f.stat().st_mtime).isoformat()})
        return items, False
    if low.startswith(("leer", "read", "get")):
        key = next((k for k in ("nombre", "name", "ruta", "path", "id") if k in args), None)
        if key is None:
            return {"error": "falta el nombre"}, True
        try:
            p = _safe(IN_DIR, str(args[key]))
            if not p.exists():
                return {"error": "fuente no encontrada", "nombre": args[key]}, True
            return {"nombre": p.name, "texto": p.read_text(encoding="utf-8", errors="replace")}, False
        except ValueError as e:
            return {"error": str(e)}, True
    if low.startswith(("guardar", "save", "write", "export")):
        fname = next((args[k] for k in ("nombre_archivo", "nombre", "filename", "name") if k in args), None)
        content = next((args[k] for k in ("contenido", "content", "texto", "text") if k in args), None)
        if not fname or content is None:
            return {"error": "faltan nombre_archivo o contenido"}, True
        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            p = _safe(OUT_DIR, str(fname))
            if p.exists():
                return {"error": "el archivo ya existe; usa una versión nueva", "ruta": str(p)}, True
            p.write_text(str(content), encoding="utf-8")
            return {"ok": True, "ruta": str(p)}, False
        except ValueError as e:
            return {"error": str(e)}, True
    return {"error": f"TODO: tool '{name}' no implementada en este servidor"}, True


def _schema(t):
    props = {}
    for k, v in (t.get("input_schema") or {}).items():
        props[k] = v if isinstance(v, dict) else {"type": v if v in ("string", "number", "integer", "boolean") else "string"}
    out = {"type": "object", "properties": props}
    if t.get("required"):
        out["required"] = [r for r in t["required"] if r in props]
    return out


def main():
    def send(o):
        sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n"); sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        m, rid = req.get("method"), req.get("id")
        if m == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "__SERVER__", "version": "1.0.0"}}})
        elif m == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": t["name"], "description": t.get("description", ""), "inputSchema": _schema(t)} for t in TOOLS]}})
        elif m == "tools/call":
            p = req.get("params", {}); out, err = handle(p.get("name"), p.get("arguments") or {})
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}], "isError": err}})
        elif m == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"no soportado: {m}"}})


if __name__ == "__main__":
    main()
'''


def cmd_install(args):
    """Instala el paquete como subagente de Claude Code en el proyecto actual (+ skills + servidor MCP)."""
    import shutil
    ws = Workspace(args.workspace)
    pkg = ws.load_package()
    agents = Path(".claude/agents"); skills = Path(".claude/skills")
    agents.mkdir(parents=True, exist_ok=True); skills.mkdir(parents=True, exist_ok=True)
    (agents / f"{pkg.name}.md").write_text(pkg.render_agent_md(), encoding="utf-8")
    for name, content in pkg.skills.items():
        d = skills / name; d.mkdir(parents=True, exist_ok=True); (d / "SKILL.md").write_text(content, encoding="utf-8")
    print(f"Agente en {agents / (pkg.name + '.md')}; {len(pkg.skills)} skills en {skills}/")
    if pkg.tools:
        args.out = args.out or "mcp"
        cmd_export_tools(args)
    print(f"\nReinicia Claude Code y prueba:  > usa el subagente {pkg.name}: …")


def cmd_export(args):
    ws = Workspace(args.workspace)
    out = ws.export(Path(args.out or f"{ws.root.name}-agent.zip"))
    print(f"Exportado: {out}")


def cmd_demo(args):
    """Tubería completa en mock: entrevista guionizada → spec → package → evals → train → export."""
    args.backend = "mock"
    ws = Workspace(args.workspace); ws.init()
    llm = LLM(backend="mock")
    print("1) entrevista (guionizada)")
    run_interview_scripted(ws, llm, ["Quiero un agente de customer care", "r2", "r3", "r4"])
    print("2) paquete inicial")
    ws.save_package(AgentPackage.initial_from_spec(ws.load_spec()))
    print("3) evals")
    cases = build_cases(ws, llm)
    print(f"   {len(cases)} casos")
    print("4) afinado")
    Trainer(ws, llm, Runner("mock"), TrainConfig(max_iterations=6, use_judge=True)).train()
    print("5) export")
    print("   ", ws.export(ws.root.parent / f"{ws.root.name}-agent.zip"))


def main(argv=None):
    p = argparse.ArgumentParser(prog="forge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", choices=["anthropic", "cli", "mock"], default="anthropic", help="backend para los ROLES del entrenador")
    p.add_argument("--runner", choices=["api", "sdk", "cli", "mock"], default="api", help="backend para ejecutar el AGENTE bajo prueba")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("workspace"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("interview"); s.add_argument("workspace"); s.add_argument("--describe", help="frase inicial")
    s.add_argument("--resume", action="store_true", help="continuar una entrevista interrumpida"); s.add_argument("--max-turns", type=int, default=8); s.set_defaults(fn=cmd_interview)
    s = sub.add_parser("distill"); s.add_argument("workspace"); s.add_argument("--max-samples", type=int)
    s.add_argument("--full", type=int, default=6, help="cuántas muestras van completas (el resto, solo esqueleto)")
    s.add_argument("--from-raw", action="store_true", help="no llama al modelo: aplica lo recuperable de distill.raw.txt")
    s.add_argument("--sections", help="pasada focalizada SOLO en estas secciones (títulos separados por coma), p.ej. 'Presupuesto,Soporte,Software'")
    s.add_argument("--full-pass", action="store_true", help="con --sections: hacer también la pasada general antes"); s.set_defaults(fn=cmd_distill)
    s = sub.add_parser("package"); s.add_argument("workspace"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_package)
    s = sub.add_parser("build-evals"); s.add_argument("workspace"); s.add_argument("--n", type=int)
    s.add_argument("--val-ratio", type=float, default=0.25); s.add_argument("--test-ratio", type=float, default=0.15); s.set_defaults(fn=cmd_build_evals)
    s = sub.add_parser("run"); s.add_argument("workspace"); s.add_argument("--split", choices=["fit", "validation", "test", "all"], default="all")
    s.add_argument("--runs", type=int, default=1); s.add_argument("--no-judge", action="store_true"); s.add_argument("--show", type=int, default=10)
    s.add_argument("--parallel", type=int, default=4); s.add_argument("--label"); s.add_argument("--model"); s.set_defaults(fn=cmd_run)
    s = sub.add_parser("train"); s.add_argument("workspace")
    s.add_argument("--iterations", type=int, default=8); s.add_argument("--patience", type=int, default=3)
    s.add_argument("--target", type=float, default=0.95); s.add_argument("--runs", type=int, default=1)
    s.add_argument("--holdout-every", type=int, default=0); s.add_argument("--ask-every", type=int, default=0)
    s.add_argument("--parallel", type=int, default=4)
    s.add_argument("--no-judge", action="store_true"); s.add_argument("--model"); s.set_defaults(fn=cmd_train)
    s = sub.add_parser("cases"); s.add_argument("workspace"); s.add_argument("--split", choices=["fit", "validation", "test", "all"], default="all")
    s.add_argument("--tag"); s.add_argument("-v", "--verbose", action="store_true"); s.set_defaults(fn=cmd_cases)
    s = sub.add_parser("lint-cases"); s.add_argument("workspace"); s.add_argument("--fix", action="store_true", help="pone scope:'tools' a las prohibiciones sin scope"); s.set_defaults(fn=cmd_lint_cases)
    s = sub.add_parser("history"); s.add_argument("workspace"); s.set_defaults(fn=cmd_history)
    s = sub.add_parser("show"); s.add_argument("workspace"); s.add_argument("run", help="nombre del run sin .json, p.ej. v002-fit")
    s.add_argument("case", nargs="?"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("compare"); s.add_argument("workspace"); s.add_argument("a"); s.add_argument("b"); s.set_defaults(fn=cmd_compare)
    s = sub.add_parser("rollback"); s.add_argument("workspace"); s.add_argument("version"); s.set_defaults(fn=cmd_rollback)
    s = sub.add_parser("diff"); s.add_argument("workspace"); s.add_argument("a"); s.add_argument("b", nargs="?", default="current"); s.set_defaults(fn=cmd_diff)
    s = sub.add_parser("ui"); s.add_argument("workspace"); s.add_argument("--model"); s.set_defaults(fn=cmd_ui)
    s = sub.add_parser("chat"); s.add_argument("workspace"); s.add_argument("--model"); s.add_argument("--version", help="hablar con una versión concreta (vNNN)")
    s.add_argument("--world", help="JSON con respuestas simuladas para las tools"); s.set_defaults(fn=cmd_chat)
    s = sub.add_parser("export"); s.add_argument("workspace"); s.add_argument("--out"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("export-tools"); s.add_argument("workspace"); s.add_argument("--out", help="carpeta del servidor (por defecto mcp/)")
    s.add_argument("--input-dir", default="fuentes", help="carpeta que leen las tools de lectura"); s.add_argument("--output-dir", default="prp", help="carpeta donde escriben las tools de guardado"); s.set_defaults(fn=cmd_export_tools)
    s = sub.add_parser("install"); s.add_argument("workspace"); s.add_argument("--out"); s.add_argument("--input-dir", default="fuentes"); s.add_argument("--output-dir", default="prp"); s.set_defaults(fn=cmd_install)
    s = sub.add_parser("demo"); s.add_argument("workspace"); s.set_defaults(fn=cmd_demo)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
