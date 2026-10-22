"""Estructuras de datos del sistema. Solo librería estándar (dataclasses + JSON).

Las tres piezas que viajan con el agente son:
  - AgentSpec      : lo que el entrevistador extrae de ti (el ancla de todo).
  - AgentPackage   : lo que se afina (system prompt + skills + contrato de tools + config).
  - TestCase       : lo que define "funciona bien".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any

PASS_THRESHOLD = 0.8


def _only_known(cls, d: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separa las claves que la dataclass conoce de las que el modelo haya inventado."""
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in known}, {k: v for k, v in d.items() if k not in known}


# ---------------------------------------------------------------------------
# Especificación (salida de la entrevista)
# ---------------------------------------------------------------------------

@dataclass
class ToolContract:
    """Herramienta abstracta que el agente NECESITA, sin decir cómo se implementa.

    El entorno de destino (ticketing, dev, ...) la cubre con su propio conector MCP.
    `input_schema` acepta {"campo": "string"} o {"campo": {"type": "string", ...}}.
    """
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    side_effects: bool = False       # True si modifica algo (enviar, cerrar, escalar)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolContract":
        known, _ = _only_known(cls, d)
        return cls(**known)


@dataclass
class AgentSpec:
    name: str
    kind: str                        # "specialist" | "orchestrator"
    objective: str                   # qué debe conseguir, en una frase
    audience: str = ""               # con quién habla / para quién trabaja
    success_criteria: list[str] = field(default_factory=list)   # medibles
    never_do: list[str] = field(default_factory=list)           # límites duros
    edge_cases: list[str] = field(default_factory=list)
    tone: str = ""
    language: str = "es"
    tools: list[ToolContract] = field(default_factory=list)
    knowledge_sources: list[str] = field(default_factory=list)  # docs/RAG que necesita
    methodology: str = ""            # cómo trabajáis vosotros (para skills)
    notes: str = ""
    meta: dict[str, Any] = field(default_factory=dict)          # claves extra que devolvió el modelo

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentSpec":
        known, extra = _only_known(cls, d)
        known["tools"] = [ToolContract.from_dict(t) for t in known.get("tools", []) or []]
        if extra:
            known["meta"] = {**known.get("meta", {}), **extra}
        return cls(**known)


# ---------------------------------------------------------------------------
# Casos de prueba
# ---------------------------------------------------------------------------

@dataclass
class Check:
    """Una comprobación determinista sobre la traza. Ver graders.py para los tipos.

    `critical=True` significa "si esto falla, el caso falla" (score 0), sea cual sea el resto.
    Úsalo para los `never_do` de la spec.
    """
    type: str
    value: Any = None
    weight: float = 1.0
    critical: bool = False
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Check":
        known, _ = _only_known(cls, d)
        return cls(**known)


@dataclass
class TestCase:
    id: str
    input: str                                   # prompt de acción que recibe el agente
    context: dict[str, Any] = field(default_factory=dict)   # estado del "mundo" (ticket, cliente...)
    tool_responses: dict[str, Any] = field(default_factory=dict)
    # tool_responses[name] puede ser:
    #   - un valor fijo: lo que devuelve la tool siempre
    #   - una lista de {"match": {"campo": valor}, "response": ..., "is_error": bool}: se usa la primera
    #     cuyo match coincida con el input (match vacío = comodín). Permite "not_found" para un id
    #     y datos para otro, o simular que una tool falla.
    checks: list[Check] = field(default_factory=list)       # deterministas
    rubric: str = ""                             # para el juez (subjetivo)
    tags: list[str] = field(default_factory=list)
    split: str = "fit"                           # "fit" | "validation" | "test"
    source: str = "generated"                    # "sample" | "generated" | "manual"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TestCase":
        known, extra = _only_known(cls, d)
        known["checks"] = [Check.from_dict(c) for c in known.get("checks", []) or []]
        if extra:
            known["meta"] = {**known.get("meta", {}), **extra}
        return cls(**known)


def resolve_tool_response(tool_responses: dict[str, Any], name: str, inp: dict[str, Any]) -> tuple[Any, bool]:
    """Devuelve (respuesta, is_error) para una llamada, según las reglas de arriba."""
    if name not in tool_responses:
        return {"ok": True, "simulated": True, "received": inp}, False
    spec = tool_responses[name]
    if isinstance(spec, list) and spec and all(isinstance(x, dict) and "response" in x for x in spec):
        for rule in spec:
            match = rule.get("match") or {}
            if all(str(inp.get(k, "")).strip().lower() == str(v).strip().lower() for k, v in match.items()):
                return rule["response"], bool(rule.get("is_error", False))
        return {"ok": False, "simulated": True, "error": "sin respuesta simulada para este input", "received": inp}, True
    return spec, False


# ---------------------------------------------------------------------------
# Trazas y resultados
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: Any = None
    is_error: bool = False


@dataclass
class Trace:
    case_id: str
    final_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    turns: int = 0
    error: str | None = None
    infra_error: bool = False                    # red, 429, timeout, proceso caído: no es culpa del agente
    raw: Any = None                              # lo que devuelva el backend, por si acaso

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        raw = d.pop("raw", None)
        if isinstance(raw, dict):
            d["cost_usd"] = raw.get("cost_usd")
        return d


@dataclass
class CheckResult:
    type: str
    passed: bool
    weight: float
    critical: bool = False
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    run: int
    checks: list[CheckResult]
    judge_score: float | None = None             # 0..1
    judge_reason: str = ""
    trace: Trace | None = None

    @property
    def infra_error(self) -> bool:
        return bool(self.trace and self.trace.infra_error)

    @property
    def critical_failed(self) -> bool:
        return any(c.critical and not c.passed for c in self.checks)

    @property
    def deterministic_score(self) -> float:
        if self.critical_failed:
            return 0.0
        total = sum(c.weight for c in self.checks)
        if total == 0:
            return 1.0
        return sum(c.weight for c in self.checks if c.passed) / total

    @property
    def score(self) -> float:
        """Media ponderada: deterministas pesan 0.7, juez 0.3 (si hay juez). Crítico fallido = 0."""
        if self.critical_failed:
            return 0.0
        if self.judge_score is None:
            return self.deterministic_score
        return 0.7 * self.deterministic_score + 0.3 * self.judge_score

    @property
    def passed(self) -> bool:
        return self.score >= PASS_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "run": self.run,
            "checks": [asdict(c) for c in self.checks],
            "judge_score": self.judge_score,
            "judge_reason": self.judge_reason,
            "score": round(self.score, 4),
            "passed": self.passed,
            "critical_failed": self.critical_failed,
            "infra_error": self.infra_error,
            "trace": self.trace.to_dict() if self.trace else None,
        }


@dataclass
class EvalReport:
    version: str
    split: str
    results: list[CaseResult]

    @property
    def scored(self) -> list[CaseResult]:
        """Resultados que cuentan: los de infraestructura fallida se excluyen."""
        return [r for r in self.results if not r.infra_error]

    @property
    def infra_errors(self) -> int:
        return len(self.results) - len(self.scored)

    @property
    def mean_score(self) -> float:
        s = self.scored
        return sum(r.score for r in s) / len(s) if s else 0.0

    @property
    def pass_rate(self) -> float:
        """Fracción de EJECUCIONES que pasan."""
        s = self.scored
        return sum(1 for r in s if r.passed) / len(s) if s else 0.0

    def per_case(self) -> dict[str, list[CaseResult]]:
        out: dict[str, list[CaseResult]] = {}
        for r in self.scored:
            out.setdefault(r.case_id, []).append(r)
        return out

    @property
    def case_pass_rate(self) -> float:
        """Fracción de CASOS en que TODAS sus ejecuciones pasan. Con runs>1 es la métrica honesta:
        un límite duro que se respeta 2 de 3 veces es un límite que no se respeta."""
        pc = self.per_case()
        return sum(1 for rs in pc.values() if all(r.passed for r in rs)) / len(pc) if pc else 0.0

    def case_scores(self) -> dict[str, float]:
        return {cid: sum(r.score for r in rs) / len(rs) for cid, rs in self.per_case().items()}

    def failures(self) -> list[CaseResult]:
        """Un resultado por caso fallido (el peor), ordenado de peor a mejor."""
        out = []
        for rs in self.per_case().values():
            failed = [r for r in rs if not r.passed]
            if failed:
                out.append(min(failed, key=lambda r: r.score))
        return sorted(out, key=lambda r: r.score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "split": self.split,
            "mean_score": round(self.mean_score, 4),
            "pass_rate": round(self.pass_rate, 4),
            "case_pass_rate": round(self.case_pass_rate, 4),
            "n_runs": len(self.results),
            "n_cases": len(self.per_case()),
            "infra_errors": self.infra_errors,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Utilidades JSON
# ---------------------------------------------------------------------------

def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
