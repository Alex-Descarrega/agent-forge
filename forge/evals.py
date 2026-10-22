"""Fase 2: construir la batería de tests a partir de spec + muestras, y partirla en fit/validation."""

from __future__ import annotations

import json
import random

from .llm import LLM
from .package import Workspace
from .schemas import TestCase, dump_json, load_json


def build_cases(ws: Workspace, llm: LLM, n_cases: int | None = None, validation_ratio: float = 0.25,
                test_ratio: float = 0.15, seed: int = 7, batch_size: int = 15) -> list[TestCase]:
    spec = ws.load_spec()
    samples = ws.load_samples()

    prompt = ["ESPECIFICACIÓN:", json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), ""]
    if samples:
        prompt.append(f"MUESTRAS ({len(samples)}):")
        for s in samples:
            prompt += [f"--- {s['file']} [{s['label']}] ---", s["content"][:4000], ""]
    else:
        prompt.append("MUESTRAS: ninguna. Genera casos sintéticos variados y márcalo en uncovered si algún criterio queda débil.")
    n_cases = n_cases or 30
    cases: list[TestCase] = []
    uncovered: list[str] = []
    raw_dir = ws.cases_path.parent
    raw_dir.mkdir(parents=True, exist_ok=True)
    from .llm import extract_json
    # por lotes: una respuesta con 40 casos completos supera lo que cabe en una salida
    for lot, (start, size) in enumerate(_lots(n_cases, batch_size)):
        p = list(prompt)
        if cases:
            p += ["CASOS YA GENERADOS EN LOTES ANTERIORES (no los repitas; cubre lo que falte):"]
            p += [f"- [{c.id}] {c.input[:100]}" for c in cases]
        p.append(f"\nGenera exactamente {size} casos (lote {lot + 1}).")
        text = llm.complete("eval_builder", "\n".join(p))
        (raw_dir / f"raw_eval_builder_{lot + 1}.txt").write_text(text, encoding="utf-8")  # no se pierde si el parseo falla
        data = extract_json(text)
        if "cases" not in data:
            raise SystemExit(f"El constructor no devolvió 'cases' en el lote {lot + 1}. Respuesta cruda en {raw_dir}")
        got = [TestCase.from_dict({**c, "split": "fit"}) for c in data["cases"]]
        if len(got) < size * 0.6:
            print(f"[constructor] lote {lot + 1}: pidió {size} casos y devolvió {len(got)}")
        cases += got
        uncovered += data.get("uncovered") or []
    if uncovered:
        print("[constructor] criterios sin cobertura:", sorted(set(uncovered)))
    if len(cases) < n_cases * 0.7:
        print(f"[aviso] se pidieron {n_cases} casos y hay {len(cases)}")

    assign_splits(cases, validation_ratio, test_ratio, seed)
    save_cases(ws, cases)
    n_test = sum(1 for c in cases if c.split == "test")
    if test_ratio > 0 and n_test < 5:
        print(f"[aviso] solo {n_test} casos en test: la cifra final será poco fiable. Pide más casos (--n 40+).")
    return cases


def _lots(n: int, batch: int) -> list[tuple[int, int]]:
    out, start = [], 0
    while start < n:
        size = min(batch, n - start)
        out.append((start, size))
        start += size
    return out


def assign_splits(cases: list[TestCase], validation_ratio: float, test_ratio: float = 0.0, seed: int = 7) -> None:
    """Reparto en fit / validation / test por cuotas GLOBALES, equilibrando por tag primario.

    - fit: lo que ve el editor.
    - validation: decide si un parche se acepta (el editor solo recibe "empeoró", sin números).
    - test: nunca se usa en el bucle; solo en el informe final. Es la cifra honesta.

    Se baraja cada grupo de tag y se intercalan (round-robin) para que, al cortar por cuotas,
    cada split tenga de todo aunque los grupos sean pequeños.
    """
    rng = random.Random(seed)
    by_tag: dict[str, list[TestCase]] = {}
    for c in cases:
        by_tag.setdefault(c.tags[0] if c.tags else "_", []).append(c)
    groups = list(by_tag.values())
    for g in groups:
        rng.shuffle(g)
    rng.shuffle(groups)
    interleaved: list[TestCase] = []
    i = 0
    while any(groups):
        g = groups[i % len(groups)]
        if g:
            interleaved.append(g.pop())
        i += 1
    n = len(interleaved)
    k_test = round(n * test_ratio) if n >= 6 else 0
    k_val = max(1, round(n * validation_ratio)) if n > 1 else 0
    for idx, c in enumerate(interleaved):
        c.split = "test" if idx < k_test else "validation" if idx < k_test + k_val else "fit"


def save_cases(ws: Workspace, cases: list[TestCase]) -> None:
    seen: dict[str, int] = {}
    for c in cases:                                   # ids únicos, o los informes pisan casos
        base = c.id
        if base in seen:
            seen[base] += 1
            c.id = f"{base}_{seen[base]}"
        seen.setdefault(c.id, 0)
    dump_json(ws.cases_path, [c.to_dict() for c in cases])


def load_cases(ws: Workspace, split: str | None = None) -> list[TestCase]:
    cases = [TestCase.from_dict(c) for c in load_json(ws.cases_path)]
    return [c for c in cases if split is None or c.split == split]


def generate_holdout(ws: Workspace, llm: LLM, n: int = 10) -> list[TestCase]:
    """Casos nuevos a mitad de entrenamiento, para comprobar que la mejora generaliza."""
    existing = load_cases(ws)
    new = build_cases_raw(ws, llm, n, existing)
    round_no = 1 + sum(1 for c in existing if c.source == "generated-holdout") // max(1, n)
    fresh = []
    for i, c in enumerate(new, 1):
        c.id = f"{c.id}_h{round_no}"
        c.split = "validation"
        c.source = "generated-holdout"
        fresh.append(c)
    save_cases(ws, existing + fresh)
    return fresh


def build_cases_raw(ws: Workspace, llm: LLM, n: int, existing: list[TestCase]) -> list[TestCase]:
    spec = ws.load_spec()
    samples = ws.load_samples()
    prompt = ["ESPECIFICACIÓN:", json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), ""]
    if samples:
        prompt.append(f"MUESTRAS ({len(samples)}):")
        for s in samples:
            prompt += [f"--- {s['file']} [{s['label']}] ---", s["content"][:2000], ""]
    prompt += ["CASOS QUE YA EXISTEN (no los repitas ni los parafrasees; busca situaciones, redacciones y combinaciones que NO estén aquí):"]
    prompt += [f"- [{c.id}] {c.input[:120]}" for c in existing[:80]]
    prompt += ["", f"Genera exactamente {n} casos NUEVOS. Prioriza huecos: criterios o límites de la spec con pocos casos arriba, y situaciones límite."]
    data = llm.complete_json("eval_builder", "\n".join(prompt))
    return [TestCase.from_dict({**c, "split": "fit"}) for c in data["cases"][:n]]
