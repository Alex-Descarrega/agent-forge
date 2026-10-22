"""Fase 4: puntuar una traza. Deterministas primero, juez (LLM) después."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .llm import LLM
from .schemas import AgentSpec, CaseResult, Check, CheckResult, TestCase, Trace


# ---------------------------------------------------------------------------
# comprobaciones deterministas
# ---------------------------------------------------------------------------

def _tool_names(t: Trace) -> list[str]:
    return [c.name for c in t.tool_calls]


def _all_text(t: Trace) -> str:
    """Respuesta final + todo texto que el agente escribió en inputs de tools.

    Importante: en agentes que actúan vía tools (responder, enviar_email...), el texto que ve
    el cliente está en el input de la tool, no en la respuesta final. Los checks de texto
    miran ambos sitios por defecto; `{"text": "...", "scope": "final"}` restringe a la final.
    """
    parts = [t.final_text]
    for c in t.tool_calls:
        parts.append(json.dumps(c.input, ensure_ascii=False))
    return "\n".join(parts)


def _text_and_value(t: Trace, v: Any) -> tuple[str, Any]:
    """Permite value simple o {"text"/"values": ..., "scope": "all"|"final"|"tools"}."""
    if isinstance(v, dict) and "scope" in v:
        scope = v.get("scope", "all")
        val = v.get("text", v.get("values", v.get("value")))
        if scope == "final":
            return t.final_text, val
        if scope == "tools":
            return "\n".join(json.dumps(c.input, ensure_ascii=False) for c in t.tool_calls), val
        return _all_text(t), val
    return _all_text(t), v


def _c_contains(t: Trace, v: Any) -> tuple[bool, str]:
    text, v = _text_and_value(t, v)
    ok = str(v).lower() in text.lower()
    return ok, "" if ok else f"'{v}' no aparece (ni en la respuesta ni en los inputs de tools)"


def _c_contains_any(t: Trace, v: Any) -> tuple[bool, str]:
    text, v = _text_and_value(t, v)
    low = text.lower()
    ok = any(str(x).lower() in low for x in v)
    return ok, "" if ok else f"ninguno de {v} aparece"


def _c_not_contains(t: Trace, v: Any) -> tuple[bool, str]:
    text, v = _text_and_value(t, v)
    ok = str(v).lower() not in text.lower()
    return ok, "" if ok else f"'{v}' aparece y no debería"


def _c_regex(t: Trace, v: Any) -> tuple[bool, str]:
    text, v = _text_and_value(t, v)
    ok = re.search(str(v), text, re.I) is not None
    return ok, "" if ok else f"regex {v} no coincide"


def _c_tool_called(t: Trace, v: Any) -> tuple[bool, str]:
    ok = v in _tool_names(t)
    return ok, "" if ok else f"no se llamó `{v}` (llamadas: {_tool_names(t)})"


def _c_tool_not_called(t: Trace, v: Any) -> tuple[bool, str]:
    ok = v not in _tool_names(t)
    return ok, "" if ok else f"se llamó `{v}` y no debía"


def _c_tool_called_before(t: Trace, v: Any) -> tuple[bool, str]:
    a, b = v
    names = _tool_names(t)
    if a not in names:
        return False, f"no se llamó `{a}`"
    if b not in names:
        return True, ""
    ok = names.index(a) < names.index(b)
    return ok, "" if ok else f"`{a}` debía ir antes que `{b}`"


def _c_tool_input_contains(t: Trace, v: Any) -> tuple[bool, str]:
    for c in t.tool_calls:
        if c.name == v["tool"] and str(v["value"]).lower() in str(c.input.get(v["field"], "")).lower():
            return True, ""
    return False, f"ninguna llamada a `{v['tool']}` tiene {v['field']} con '{v['value']}'"


def _c_tool_input_not_contains(t: Trace, v: Any) -> tuple[bool, str]:
    for c in t.tool_calls:
        if c.name == v["tool"] and str(v["value"]).lower() in str(c.input.get(v["field"], "")).lower():
            return False, f"`{v['tool']}.{v['field']}` contiene '{v['value']}' y no debería"
    return True, ""


def _c_tool_input_equals(t: Trace, v: Any) -> tuple[bool, str]:
    """Igualdad exacta (normalizada) de un campo: `ticket_id == "T-1"` no acepta "T-1001"."""
    for c in t.tool_calls:
        if c.name == v["tool"] and str(c.input.get(v["field"], "")).strip().lower() == str(v["value"]).strip().lower():
            return True, ""
    seen = [str(c.input.get(v["field"])) for c in t.tool_calls if c.name == v["tool"]]
    return False, f"ninguna llamada a `{v['tool']}` tiene {v['field']} == '{v['value']}' (vistos: {seen})"


def _c_tool_call_count(t: Trace, v: Any) -> tuple[bool, str]:
    """{"tool": n, "count": k} exactamente k veces; o {"tool": n, "min": a, "max": b}."""
    n = sum(1 for c in t.tool_calls if c.name == v["tool"])
    if "count" in v:
        ok = n == int(v["count"])
        return ok, "" if ok else f"`{v['tool']}` llamada {n} veces, se esperaban {v['count']}"
    lo, hi = int(v.get("min", 0)), int(v.get("max", 10**9))
    ok = lo <= n <= hi
    return ok, "" if ok else f"`{v['tool']}` llamada {n} veces, fuera de [{lo}, {hi}]"


def _c_tool_calls_max(t: Trace, v: Any) -> tuple[bool, str]:
    ok = len(t.tool_calls) <= int(v)
    return ok, "" if ok else f"{len(t.tool_calls)} llamadas > {v}"


def _c_turns_max(t: Trace, v: Any) -> tuple[bool, str]:
    """Turnos = llamadas a tools + 1, calculado desde la traza para que sea igual en todos los backends
    (Claude Code y la API cuentan turnos de forma distinta)."""
    turns = len(t.tool_calls) + 1
    ok = turns <= int(v)
    return ok, "" if ok else f"{turns} turnos (tools+1) > {v}"


def _first_json_object(text: str) -> dict[str, Any] | None:
    """Primer objeto JSON parseable: bloques ```json primero, luego raw_decode desde cada '{'."""
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def _c_json_has_keys(t: Trace, v: Any) -> tuple[bool, str]:
    obj = _first_json_object(t.final_text)
    if obj is None:
        return False, "no hay JSON válido en la respuesta"
    missing = [k for k in v if k not in obj]
    return not missing, "" if not missing else f"faltan claves {missing}"


def _c_asks_question(t: Trace, v: Any) -> tuple[bool, str]:
    """La respuesta pide información: su última línea con contenido contiene '?' (o '¿')."""
    lines = [l.strip(" \t*_)>-") for l in t.final_text.strip().splitlines() if l.strip(" \t*_)>-")]
    last = lines[-1] if lines else ""
    ok = "?" in last or "¿" in last
    return ok, "" if ok else "la última línea de la respuesta no es una pregunta"


CHECKS: dict[str, Callable[[Trace, Any], tuple[bool, str]]] = {
    "contains": _c_contains,
    "contains_any": _c_contains_any,
    "not_contains": _c_not_contains,
    "regex": _c_regex,
    "tool_called": _c_tool_called,
    "tool_not_called": _c_tool_not_called,
    "tool_called_before": _c_tool_called_before,
    "tool_input_contains": _c_tool_input_contains,
    "tool_input_not_contains": _c_tool_input_not_contains,
    "tool_input_equals": _c_tool_input_equals,
    "tool_call_count": _c_tool_call_count,
    "tool_calls_max": _c_tool_calls_max,
    "turns_max": _c_turns_max,
    "json_has_keys": _c_json_has_keys,
    "asks_question": _c_asks_question,
}


def run_checks(trace: Trace, checks: list[Check]) -> list[CheckResult]:
    out = []
    for ch in checks:
        fn = CHECKS.get(ch.type)
        if fn is None:
            out.append(CheckResult(ch.type, False, ch.weight, ch.critical, f"check desconocido: {ch.type}"))
            continue
        if trace.error and not trace.final_text and not trace.tool_calls:
            out.append(CheckResult(ch.type, False, ch.weight, ch.critical, f"error de ejecución: {trace.error}"))
            continue
        try:
            ok, detail = fn(trace, ch.value)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"check lanzó excepción: {e}"
        out.append(CheckResult(ch.type, ok, ch.weight, ch.critical, detail))
    return out


# ---------------------------------------------------------------------------
# juez
# ---------------------------------------------------------------------------

def judge(llm: LLM, spec: AgentSpec, case: TestCase, trace: Trace) -> tuple[float, str]:
    if not case.rubric.strip():
        return None, ""  # type: ignore[return-value]
    calls = "\n".join(
        f"- {c.name}({json.dumps(c.input, ensure_ascii=False)}) -> {json.dumps(c.output, ensure_ascii=False)[:300]}"
        + (" [ERROR]" if c.is_error else "")
        for c in trace.tool_calls) or "(ninguna)"
    prompt = (
        f"ESPECIFICACIÓN:\nObjetivo: {spec.objective}\nCriterios de éxito: {spec.success_criteria}\n"
        f"Nunca: {spec.never_do}\nTono: {spec.tone}\nMetodología: {spec.methodology}\n"
        f"(Lo que está en la especificación o en la metodología NO cuenta como dato inventado.)\n\n"
        f"CASO:\n{case.input}\nContexto: {json.dumps(case.context, ensure_ascii=False)}\n"
        f"Respuestas simuladas de tools: {json.dumps(case.tool_responses, ensure_ascii=False)}\n\n"
        f"RÚBRICA:\n{case.rubric}\n\n"
        f"LLAMADAS A HERRAMIENTAS:\n{calls}\n\n"
        f"RESPUESTA FINAL:\n{trace.final_text}\n"
    )
    try:
        data = llm.complete_json("judge", prompt)
        score = data.get("score") if isinstance(data, dict) else None
        if score is None:
            return None, f"juez sin score: {str(data)[:120]}"  # type: ignore[return-value]
        return max(0.0, min(1.0, float(score))), str(data.get("reason", ""))
    except Exception as e:  # noqa: BLE001
        return None, f"juez falló: {type(e).__name__}: {str(e)[:120]}"  # type: ignore[return-value]


def grade(llm: LLM | None, spec: AgentSpec, case: TestCase, trace: Trace, run: int = 0) -> CaseResult:
    checks = run_checks(trace, case.checks)
    score, reason = (None, "")
    if llm is not None and case.rubric.strip() and not trace.infra_error:
        score, reason = judge(llm, spec, case, trace)
        if score is None:
            # sin juez la fórmula cambia (solo deterministas) y la comparación pareada se sesga:
            # se trata como fallo de infraestructura y se excluye del cómputo
            trace.infra_error = True
            trace.error = (trace.error + "; " if trace.error else "") + reason
    return CaseResult(case_id=case.id, run=run, checks=checks, judge_score=score, judge_reason=reason, trace=trace)
