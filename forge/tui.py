"""Interfaz de consola (curses, sin dependencias): `forge ui <workspace>`.

Pestañas (F1-F4 o 1-4 con el cursor fuera del input; Tab cambia de pestaña):
  1 Chat       banco de pruebas: conversación a la izquierda, tool calls del turno a la derecha
  2 Casos      lista de casos (↑↓), detalle + resultado del último run a la derecha
  3 Versiones  historial (↑↓), diff de prompt con la versión anterior a la derecha
  4 Log        salida de las acciones largas (run / train), en vivo

Acciones: r = forge run (fit) | t = forge train | s = guardar último intercambio como caso | w = cargar mundo
          v = chatear con la versión seleccionada | q = salir
Chat: escribe y Enter envía; Ctrl+J o Alt+Enter = nueva línea; Esc limpia. PgUp/PgDn hacen scroll del panel.
"""

from __future__ import annotations

import curses
import difflib
import json
import locale
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from queue import Queue, Empty

from .chat import ChatSession
from .evals import load_cases, save_cases
from .package import AgentPackage, Workspace
from .schemas import Check, TestCase, ToolCall

locale.setlocale(locale.LC_ALL, "")

TABS = ["Chat", "Casos", "Versiones", "Log"]


class State:
    def __init__(self, ws: Workspace, model: str | None):
        self.ws = ws
        self.model = model
        self.pkg = ws.load_package()
        self.tab = 0
        self.status = "listo"
        self.busy = False
        # chat
        self.sess = ChatSession(ws, self.pkg, model, "current")
        self.chat_lines: list[tuple[str, str]] = []     # (role, text)
        self.input = ""
        self.chat_scroll = 0
        self.last_calls: list[ToolCall] = []
        # casos
        self.cases: list[TestCase] = []
        self.case_idx = 0
        self.case_scroll = 0
        self.last_run: dict = {}
        # versiones
        self.versions: list[str] = []
        self.ver_idx = 0
        self.ver_scroll = 0
        # log
        self.log: list[str] = []
        self.log_scroll = 0
        self.q: Queue = Queue()
        self.reload()

    def reload(self) -> None:
        self.cases = load_cases(self.ws) if self.ws.cases_path.exists() else []
        self.versions = sorted(p.name for p in self.ws.versions_dir.glob("v*") if p.is_dir())
        self.last_run = {}
        runs = sorted(self.ws.runs_dir.glob("*-fit.json"), key=lambda p: p.stat().st_mtime)
        if runs:
            try:
                d = json.loads(runs[-1].read_text(encoding="utf-8"))
                self.last_run = {"name": runs[-1].stem, "by_case": {}}
                for r in d["results"]:
                    self.last_run["by_case"].setdefault(r["case_id"], []).append(r)
            except Exception:  # noqa: BLE001
                pass

    def logln(self, s: str) -> None:
        for line in s.rstrip("\n").split("\n"):
            self.log.append(line)
        self.log = self.log[-2000:]


# ---------------------------------------------------------------- helpers de dibujo

def _wrap(text: str, width: int) -> list[str]:
    out = []
    for para in (text or "").split("\n"):
        out += textwrap.wrap(para, max(1, width), replace_whitespace=False, drop_whitespace=False) or [""]
    return out


def _box(win, y, x, h, w, title: str, active: bool = False):
    try:
        attr = curses.color_pair(2) | curses.A_BOLD if active else curses.color_pair(1)
        win.attron(attr)
        win.addch(y, x, curses.ACS_ULCORNER); win.addch(y, x + w - 1, curses.ACS_URCORNER)
        win.addch(y + h - 1, x, curses.ACS_LLCORNER); win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        win.hline(y, x + 1, curses.ACS_HLINE, w - 2); win.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2)
        win.vline(y + 1, x, curses.ACS_VLINE, h - 2); win.vline(y + 1, x + w - 1, curses.ACS_VLINE, h - 2)
        win.addstr(y, x + 2, f" {title} "[: w - 4])
        win.attroff(attr)
    except curses.error:
        pass


def _put(win, y, x, s: str, w: int, attr=0):
    try:
        win.addnstr(y, x, s, max(0, w), attr)
    except curses.error:
        pass


def _draw_lines(win, y, x, h, w, lines: list[str], scroll: int, attrs: list[int] | None = None) -> int:
    """Dibuja líneas con scroll desde el final (scroll=0 muestra las últimas). Devuelve scroll máximo."""
    maxs = max(0, len(lines) - h)
    scroll = min(scroll, maxs)
    start = max(0, len(lines) - h - scroll)
    for i, line in enumerate(lines[start:start + h]):
        _put(win, y + i, x, line, w, (attrs[start + i] if attrs else 0))
    return maxs


# ---------------------------------------------------------------- pestañas

def draw_chat(win, st: State, y, x, h, w):
    side = max(28, w // 3)
    main_w = w - side - 1
    _box(win, y, x, h - 4, main_w, f"Chat con {st.pkg.name} [{st.sess.label}]", st.tab == 0)
    lines, attrs = [], []
    for role, text in st.chat_lines:
        prefix = "tú> " if role == "user" else f"{st.pkg.name}> " if role == "agent" else "  · "
        color = curses.color_pair(3) if role == "user" else curses.color_pair(4) if role == "agent" else curses.color_pair(5)
        for j, l in enumerate(_wrap(text, main_w - 4 - len(prefix))):
            lines.append((prefix if j == 0 else " " * len(prefix)) + l); attrs.append(color)
        lines.append(""); attrs.append(0)
    st.chat_scroll = _draw_lines(win, y + 1, x + 2, h - 6, main_w - 4, lines, st.chat_scroll, attrs) if lines else 0
    # input
    _box(win, y + h - 4, x, 4, main_w, "mensaje (Enter envía · Ctrl+J nueva línea · Esc limpia)")
    inp = _wrap(st.input + "▏", main_w - 4)[-2:]
    for i, l in enumerate(inp):
        _put(win, y + h - 3 + i, x + 2, l, main_w - 4)
    # tools
    _box(win, y, x + main_w + 1, h, side, f"tool calls ({len(st.last_calls)})")
    tl = []
    for c in st.last_calls:
        tl += _wrap(f"→ {c.name}({json.dumps(c.input, ensure_ascii=False)})", side - 4)
        tl += _wrap(f"  ← {json.dumps(c.output, ensure_ascii=False)[:300]}" + (" [ERROR]" if c.is_error else ""), side - 4)
        tl.append("")
    if not tl:
        tl = ["(sin llamadas en el último turno)"]
    _draw_lines(win, y + 1, x + main_w + 3, h - 2, side - 4, tl, 0)


def draw_cases(win, st: State, y, x, h, w):
    lw = max(34, w // 3)
    _box(win, y, x, h, lw, f"casos ({len(st.cases)})", st.tab == 1)
    if not st.cases:
        _put(win, y + 2, x + 2, "sin casos: forge build-evals", lw - 4)
    else:
        vis = h - 2
        top = max(0, min(st.case_idx - vis // 2, len(st.cases) - vis))
        for i, c in enumerate(st.cases[top:top + vis]):
            idx = top + i
            res = st.last_run.get("by_case", {}).get(c.id)
            mark = "  "
            if res:
                sc = sum(r["score"] for r in res) / len(res)
                mark = "✓ " if all(r["passed"] for r in res) else "✗ "
                color = curses.color_pair(4) if mark == "✓ " else curses.color_pair(6)
            else:
                color = 0
            attr = curses.A_REVERSE if idx == st.case_idx else color
            _put(win, y + 1 + i, x + 1, f"{mark}{c.split[:3]} {c.id}", lw - 2, attr)
    # detalle
    dw = w - lw - 1
    _box(win, y, x + lw + 1, h, dw, "detalle")
    if st.cases:
        c = st.cases[st.case_idx]
        d = [f"id: {c.id}   split: {c.split}   source: {c.source}   tags: {', '.join(c.tags)}", ""]
        d += ["INPUT:"] + _wrap(c.input, dw - 4) + [""]
        if c.context:
            d += ["CONTEXTO:"] + _wrap(json.dumps(c.context, ensure_ascii=False), dw - 4) + [""]
        d += ["CHECKS:"]
        for ch in c.checks:
            d += _wrap(f"  [{'!' if ch.critical else ' '}] {ch.type} = {json.dumps(ch.value, ensure_ascii=False)}" + (f"  (w{ch.weight})" if ch.weight != 1 else "") + (f"  — {ch.description}" if ch.description else ""), dw - 4)
        if c.rubric:
            d += ["", "RÚBRICA:"] + _wrap(c.rubric, dw - 4)
        res = st.last_run.get("by_case", {}).get(c.id)
        if res:
            d += ["", f"ÚLTIMO RUN ({st.last_run.get('name')}):"]
            for r in res:
                d.append(f"  run {r['run']}: score {r['score']}  {'PASA' if r['passed'] else 'FALLA'}" + ("  CRÍTICO" if r.get("critical_failed") else ""))
                for ch in r["checks"]:
                    if not ch["passed"]:
                        d += _wrap(f"    ✗ {ch['type']}: {ch['detail']}", dw - 4)
                tr = r.get("trace") or {}
                if tr.get("tool_calls"):
                    d.append("    tools: " + ", ".join(tc["name"] for tc in tr["tool_calls"]))
                if tr.get("final_text"):
                    d += ["    respuesta:"] + ["      " + l for l in _wrap(tr["final_text"][:800], dw - 10)]
                if r.get("judge_score") is not None:
                    d += _wrap(f"    juez {r['judge_score']}: {r['judge_reason']}", dw - 4)
        st.case_scroll = _draw_lines(win, y + 1, x + lw + 3, h - 2, dw - 4, d, st.case_scroll) if len(d) > h - 2 else (_draw_lines(win, y + 1, x + lw + 3, h - 2, dw - 4, d, 0) and 0)


def draw_versions(win, st: State, y, x, h, w):
    lw = max(44, w // 3)
    _box(win, y, x, h, lw, f"versiones ({len(st.versions)})", st.tab == 2)
    if not st.versions:
        _put(win, y + 2, x + 2, "sin versiones: forge train", lw - 4)
    for i, v in enumerate(st.versions[-(h - 2):]):
        idx = len(st.versions) - min(len(st.versions), h - 2) + i
        score = ""
        f = st.ws.runs_dir / f"{v}-fit.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                score = f"{d.get('case_pass_rate', d['pass_rate']):.0%} {d['mean_score']:.3f}"
            except Exception:  # noqa: BLE001
                pass
        meta = st.ws.versions_dir / v / "meta.json"
        rat = ""
        if meta.exists():
            try:
                rat = json.loads(meta.read_text(encoding="utf-8")).get("rationale", "")
            except Exception:  # noqa: BLE001
                pass
        _put(win, y + 1 + i, x + 1, f"{v} {score:>12}  {rat}", lw - 2, curses.A_REVERSE if idx == st.ver_idx else 0)
    dw = w - lw - 1
    _box(win, y, x + lw + 1, h, dw, "diff con la versión anterior (v = chatear con esta)")
    if st.versions:
        cur = st.versions[st.ver_idx]
        prev = st.versions[st.ver_idx - 1] if st.ver_idx > 0 else None
        try:
            b = AgentPackage.load(st.ws.versions_dir / cur)
            a = AgentPackage.load(st.ws.versions_dir / prev) if prev else AgentPackage(b.name, "", "")
            d = list(difflib.unified_diff(a.system_prompt.splitlines(), b.system_prompt.splitlines(), prev or "(nada)", cur, lineterm="", n=2))
            for name in sorted(set(a.skills) | set(b.skills)):
                d += list(difflib.unified_diff(a.skills.get(name, "").splitlines(), b.skills.get(name, "").splitlines(), f"{prev}/{name}", f"{cur}/{name}", lineterm="", n=2))
            if not d:
                d = ["(sin cambios de prompt ni skills respecto a la anterior)"]
            attrs = [curses.color_pair(4) if l.startswith("+") and not l.startswith("+++") else curses.color_pair(6) if l.startswith("-") and not l.startswith("---") else curses.color_pair(5) if l.startswith("@@") else 0 for l in d]
            lines = []
            flat_attrs = []
            for l, a_ in zip(d, attrs):
                for wl in _wrap(l, dw - 4):
                    lines.append(wl); flat_attrs.append(a_)
            maxs = max(0, len(lines) - (h - 2))
            st.ver_scroll = min(st.ver_scroll, maxs)
            start = st.ver_scroll
            for i, l in enumerate(lines[start:start + h - 2]):
                _put(win, y + 1 + i, x + lw + 3, l, dw - 4, flat_attrs[start + i])
        except Exception as e:  # noqa: BLE001
            _put(win, y + 2, x + lw + 3, f"error: {e}", dw - 4)


def draw_log(win, st: State, y, x, h, w):
    _box(win, y, x, h, w, "log de acciones (r = run, t = train)", st.tab == 3)
    lines = []
    for l in st.log:
        lines += _wrap(l, w - 4)
    st.log_scroll = _draw_lines(win, y + 1, x + 2, h - 2, w - 4, lines, st.log_scroll)


# ---------------------------------------------------------------- acciones en segundo plano

def run_forge_cmd(st: State, args: list[str], label: str) -> None:
    if st.busy:
        st.status = "ya hay una acción en curso"; return
    st.busy = True
    st.status = f"{label} en curso…"
    st.tab = 3

    def worker():
        st.logln(f"$ forge {' '.join(args)}")
        try:
            proc = subprocess.Popen([sys.executable, "-m", "forge.cli", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, cwd=str(Path(__file__).resolve().parents[1]))
            for line in proc.stdout:  # type: ignore[union-attr]
                st.logln(line.replace("\r", "\n"))
            proc.wait()
            st.logln(f"[fin, código {proc.returncode}]")
        except Exception as e:  # noqa: BLE001
            st.logln(f"[error lanzando: {e}]")
        st.q.put(("done", label))

    threading.Thread(target=worker, daemon=True).start()


def send_chat(st: State, text: str) -> None:
    if st.busy:
        st.status = "espera a que termine la acción en curso"; return
    st.busy = True
    st.status = "el agente está pensando…"
    st.chat_lines.append(("user", text))
    st.chat_scroll = 0

    def worker():
        reply, calls, err = st.sess.send(text)
        st.q.put(("chat", (reply, calls, err)))

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------- bucle principal

def main(stdscr, ws: Workspace, model: str | None):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_RED, -1)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    st = State(ws, model)
    st.logln(f"workspace {ws.root} · paquete {st.pkg.summary()}")

    while True:
        # eventos de hilos
        try:
            while True:
                kind, payload = st.q.get_nowait()
                if kind == "chat":
                    reply, calls, err = payload
                    st.last_calls = calls
                    if calls:
                        st.chat_lines.append(("meta", f"{len(calls)} tool call(s): {', '.join(c.name for c in calls)}"))
                    if err:
                        st.chat_lines.append(("meta", f"error: {err}"))
                    st.chat_lines.append(("agent", reply or "(sin respuesta)"))
                    st.busy = False; st.status = "listo"
                elif kind == "done":
                    st.busy = False; st.status = f"{payload} terminado"; st.reload()
        except Empty:
            pass

        stdscr.erase()
        H, W = stdscr.getmaxyx()
        # barra de pestañas
        xx = 1
        for i, t in enumerate(TABS):
            label = f" {i + 1}:{t} "
            _put(stdscr, 0, xx, label, W - xx, curses.A_REVERSE | curses.A_BOLD if i == st.tab else curses.color_pair(2))
            xx += len(label) + 1
        _put(stdscr, 0, min(W - 1, xx + 2), f"{ws.root.name}", W - xx - 3, curses.A_DIM)
        body_y, body_h = 1, H - 2
        if st.tab == 0:
            draw_chat(stdscr, st, body_y, 0, body_h, W)
        elif st.tab == 1:
            draw_cases(stdscr, st, body_y, 0, body_h, W)
        elif st.tab == 2:
            draw_versions(stdscr, st, body_y, 0, body_h, W)
        else:
            draw_log(stdscr, st, body_y, 0, body_h, W)
        # barra de estado
        spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(time.time() * 8) % 10] if st.busy else "●"
        help_ = "Tab/F1-F4 pestañas · r run · t train · s guardar caso · w mundo · v chat con versión · PgUp/PgDn scroll · q salir"
        _put(stdscr, H - 1, 0, f" {spin} {st.status}  │  {help_}", W - 1, curses.A_REVERSE)
        stdscr.refresh()

        try:
            k = stdscr.get_wch()
        except curses.error:
            time.sleep(0.05); continue

        # teclas globales
        if k in (curses.KEY_F1, curses.KEY_F2, curses.KEY_F3, curses.KEY_F4):
            st.tab = {curses.KEY_F1: 0, curses.KEY_F2: 1, curses.KEY_F3: 2, curses.KEY_F4: 3}[k]; continue
        if k == "\t":
            st.tab = (st.tab + 1) % len(TABS); continue
        if k == curses.KEY_PPAGE:
            if st.tab == 0: st.chat_scroll += 5
            elif st.tab == 1: st.case_scroll += 5
            elif st.tab == 2: st.ver_scroll = max(0, st.ver_scroll - 5)
            else: st.log_scroll += 5
            continue
        if k == curses.KEY_NPAGE:
            if st.tab == 0: st.chat_scroll = max(0, st.chat_scroll - 5)
            elif st.tab == 1: st.case_scroll = max(0, st.case_scroll - 5)
            elif st.tab == 2: st.ver_scroll += 5
            else: st.log_scroll = max(0, st.log_scroll - 5)
            continue

        if st.tab == 0:
            # el chat captura el teclado para escribir
            if k == "\x1b":
                st.input = ""
            elif k in ("\n", "\r", curses.KEY_ENTER):
                text = st.input.strip()
                st.input = ""
                if text == "/salir":
                    break
                if text:
                    send_chat(st, text)
            elif k == "\x0a" or k == "\x0b":
                st.input += "\n"
            elif k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                st.input = st.input[:-1]
            elif isinstance(k, str) and k.isprintable():
                st.input += k
            continue

        # pestañas sin input: teclas de acción
        if k in ("q", "Q"):
            break
        if k in ("1", "2", "3", "4"):
            st.tab = int(k) - 1; continue
        if k == "r":
            run_forge_cmd(st, ["--backend", "cli", "--runner", "cli", "run", str(ws.root), "--split", "fit", "--label", f"ui-{time.strftime('%H%M%S')}"] + (["--model", model] if model else []), "run")
        elif k == "t":
            run_forge_cmd(st, ["--backend", "cli", "--runner", "cli", "train", str(ws.root), "--runs", "2"] + (["--model", model] if model else []), "train")
        elif k == "s":
            if st.sess.turns:
                last = st.sess.turns[-1]
                cid = f"chat_{time.strftime('%m%d_%H%M%S')}"
                checks = [Check("tool_called", n, 1.0, False, "pasó en el chat; revisa") for n in sorted({c['name'] for c in last['tools']})]
                cases = load_cases(ws) if ws.cases_path.exists() else []
                cases.append(TestCase(cid, last["user"], {}, dict(st.sess.world), checks, "", ["chat"], "fit", "manual"))
                save_cases(ws, cases); st.reload(); st.status = f"guardado caso {cid} (edita sus checks)"; st.tab = 1; st.case_idx = len(st.cases) - 1
            else:
                st.status = "no hay intercambio que guardar"
        elif k == "w":
            cand = sorted(ws.root.glob("*.world.json")) + sorted(ws.root.glob("worlds/*.json"))
            if cand:
                try:
                    st.sess.world = json.loads(cand[0].read_text(encoding="utf-8")); st.sess._write_world()
                    st.status = f"mundo cargado: {cand[0].name} ({', '.join(sorted(st.sess.world))})"
                except Exception as e:  # noqa: BLE001
                    st.status = f"mundo inválido: {e}"
            else:
                st.status = "pon un <nombre>.world.json en el workspace (formato tool_responses)"
        elif st.tab == 1 and st.cases:
            if k == curses.KEY_UP: st.case_idx = max(0, st.case_idx - 1); st.case_scroll = 0
            elif k == curses.KEY_DOWN: st.case_idx = min(len(st.cases) - 1, st.case_idx + 1); st.case_scroll = 0
        elif st.tab == 2 and st.versions:
            if k == curses.KEY_UP: st.ver_idx = max(0, st.ver_idx - 1); st.ver_scroll = 0
            elif k == curses.KEY_DOWN: st.ver_idx = min(len(st.versions) - 1, st.ver_idx + 1); st.ver_scroll = 0
            elif k == "v":
                v = st.versions[st.ver_idx]
                st.sess.close(); st.pkg = AgentPackage.load(ws.versions_dir / v); st.sess = ChatSession(ws, st.pkg, model, v)
                st.chat_lines = [("meta", f"ahora hablas con {v}: {st.pkg.summary()}")]; st.last_calls = []; st.tab = 0

    st.sess.close()


def run_ui(ws: Workspace, model: str | None = None) -> None:
    import shutil
    if not shutil.which("claude"):
        raise SystemExit("La UI usa Claude Code (`claude -p`). Instálalo y haz login.")
    if not (ws.package_dir / "agent.md").exists():
        raise SystemExit(f"No hay package/ en {ws.root}. Ejecuta antes: forge package {ws.root}")
    curses.wrapper(main, ws, model)
