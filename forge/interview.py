"""Fase 1: entrevista interactiva que produce spec.json."""

from __future__ import annotations

import json

from .llm import LLM
from .package import Workspace
from .schemas import AgentSpec


def _log_path(ws: Workspace):
    return ws.root / "interview.log.json"


def _read_answer() -> str:
    """Lee una respuesta que puede ocupar varias líneas (pegada desde otro sitio).

    Termina con una línea vacía tras texto, o con una línea que sea solo `.` o `fin`.
    Una primera línea vacía envía respuesta vacía (sigue sin contestar)."""
    print("\n> (pega tu respuesta; línea vacía o '.' para enviar)")
    lines: list[str] = []
    while True:
        try:
            line = input("> " if not lines else "  ")
        except EOFError:
            break
        if line.strip() in {".", "fin"}:
            break
        if not line.strip():
            if lines:
                break
            return ""
        lines.append(line)
    return "\n".join(lines).strip()


def run_interview(ws: Workspace, llm: LLM, seed_description: str = "", resume: bool = False, max_turns: int = 8) -> AgentSpec:
    """Entrevista interactiva. El historial se guarda tras cada turno en interview.log.json;
    con resume=True se continúa desde ahí (p. ej. tras un fallo del modelo)."""
    ws.init()
    history: list[dict[str, str]] = []
    log = _log_path(ws)
    if resume and log.exists():
        history = json.loads(log.read_text(encoding="utf-8"))
        print(f"\n=== Entrevista reanudada ({len(history) // 2} turnos previos; escribe 'salir' para abortar, 'cerrar' para forzar la spec) ===\n")
        user_msg = "Continuemos. Si ya tienes suficiente, devuelve la especificación; si no, pregunta lo que falte."
    else:
        samples = ws.load_samples()
        opening = seed_description.strip() or "Quiero afinar un agente. Pregúntame lo que necesites."
        if samples:
            names = ", ".join(s["file"] for s in samples[:12]) + (" …" if len(samples) > 12 else "")
            opening += (f"\n\n[Contexto del sistema: en samples/ hay {len(samples)} muestras ya cargadas ({names}). "
                        "La metodología y la estructura se extraerán de ellas en el paso `distill`; no hace falta pedirlas.]")
        print("\n=== Entrevista (escribe 'salir' para abortar, 'cerrar' para forzar la spec con lo que haya) ===\n")
        user_msg = opening

    while True:
        n_turns = len(history) // 2
        if n_turns >= max_turns:
            user_msg += ("\n\n[Sistema: se ha alcanzado el máximo de turnos. Devuelve ahora la especificación con lo que tengas; "
                         "rellena lo que falte con tu mejor propuesta y anótalo en notes.]")
        try:
            data = llm.complete_json("interviewer", user_msg, history)
        except Exception as e:  # noqa: BLE001
            log.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
            raise SystemExit(f"El entrevistador falló ({type(e).__name__}: {str(e)[:300]}).\n"
                             f"Tu progreso está en {log}. Reanuda con:  forge interview {ws.root} --resume")
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        log.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")

        if data.get("status") == "done":
            spec = AgentSpec.from_dict(data["spec"])
            ws.save_spec(spec)
            print("\n--- Especificación generada ---")
            print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
            print(f"\nGuardada en {ws.spec_path}. Revísala y edítala a mano si hace falta.")
            if ws.load_samples():
                print(f"Siguiente: forge distill {ws.root}   (extrae metodología y estructura de tus muestras)")
            else:
                print(f"Deja tus muestras en {ws.samples_dir} y luego: forge distill {ws.root}")
            return spec

        if data.get("why"):
            print(f"[entrevistador] {data['why']}")
        for q in data.get("questions", []):
            print(f"  ? {q}")
        answer = _read_answer()
        if answer.lower() in {"salir", "exit", "quit"}:
            raise SystemExit(f"Entrevista abortada. Progreso en {log} (forge interview {ws.root} --resume).")
        if answer.lower() in {"cerrar", "done", "fin"}:
            answer = "[Sistema: el usuario pide cerrar. Devuelve ahora la especificación con lo que tengas; rellena lo que falte con tu mejor propuesta y anótalo en notes.]"
        elif not answer:
            answer = "(sin respuesta; sigue con lo que tengas o propón tú un valor)"
        user_msg = answer


def run_interview_scripted(ws: Workspace, llm: LLM, answers: list[str]) -> AgentSpec:
    """Igual que run_interview pero con respuestas precargadas (tests / mock)."""
    ws.init()
    history: list[dict[str, str]] = []
    user_msg = answers[0]
    for nxt in answers[1:] + [None]:  # type: ignore[list-item]
        data = llm.complete_json("interviewer", user_msg, history)
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        if data.get("status") == "done":
            spec = AgentSpec.from_dict(data["spec"])
            ws.save_spec(spec)
            return spec
        if nxt is None:
            raise RuntimeError("Se agotaron las respuestas y la entrevista no terminó.")
        user_msg = nxt
    raise RuntimeError("unreachable")
