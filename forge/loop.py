"""Fase 5: el bucle de afinado (orquestador).

    evaluar(fit) ─► fallos ─► editor propone parche ─► candidato
        ▲                                                │
        │            rechazar si no mejora fit           ▼
        └──── aceptar y snapshot ◄── validar que no empeora validation

Criterios de parada: objetivo alcanzado, N iteraciones sin mejora, o máximo de iteraciones.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .evals import generate_holdout, load_cases
from .graders import grade
from .llm import LLM
from .package import AgentPackage, Workspace
from .report import write_report
from .runner import Runner
from .schemas import AgentSpec, CaseResult, EvalReport, TestCase, dump_json


@dataclass
class TrainConfig:
    max_iterations: int = 8
    patience: int = 3                 # iteraciones seguidas sin mejora antes de parar
    target_pass_rate: float = 0.95
    runs_per_case: int = 1            # >1 para medir variabilidad (recomendado 3 con API real)
    parallel: int = 4                 # ejecuciones simultáneas (api/cli); mock ignora
    min_delta: float = 0.01           # mejora mínima en fit para aceptar
    val_tolerance: float = 0.02       # caída máxima permitida en validation
    holdout_every: int = 0            # 0 = nunca; N = genera casos nuevos cada N aceptaciones
    holdout_n: int = 8
    ask_every: int = 0                # 0 = nunca; N = parar a pedir notas al humano cada N iteraciones
    use_judge: bool = True
    max_infra_error_rate: float = 0.1  # si más de esto falla por red/timeouts, abortar la evaluación


def _validate_patch(patch: Any, pkg: AgentPackage) -> str:
    """Devuelve '' si el parche es aplicable, o el motivo para descartarlo sin evaluar."""
    if not isinstance(patch, dict):
        return "no es un objeto JSON"
    if "tools" in patch:
        return "el editor no puede cambiar el contrato de herramientas"
    touched = any(k in patch for k in ("system_prompt", "skills", "config", "description"))
    if not touched:
        return "no cambia nada (sin system_prompt, skills ni config)"
    sp = patch.get("system_prompt")
    if sp is not None and (not isinstance(sp, str) or len(sp.strip()) < 50):
        return "system_prompt vacío o demasiado corto"
    skills = patch.get("skills")
    if skills is not None:
        if not isinstance(skills, dict):
            return "skills debe ser un objeto nombre -> contenido|null"
        for k, v in skills.items():
            if v is not None and (not isinstance(v, str) or len(v.strip()) < 20):
                return f"skill '{k}' vacía"
    # tamaño total (prompt + skills): mover contenido a una skill es legítimo; borrarlo, no
    new_sp = sp if isinstance(sp, str) else pkg.system_prompt
    new_skills = dict(pkg.skills)
    for k, v in (skills or {}).items():
        if v is None:
            new_skills.pop(k, None)
        else:
            new_skills[k] = v
    before = len(pkg.system_prompt) + sum(len(v) for v in pkg.skills.values())
    after = len(new_sp) + sum(len(v) for v in new_skills.values())
    if after < 0.4 * before:
        return (f"el parche recorta el contenido total (prompt + skills) a menos del 40% ({after} vs {before} chars); "
                "acortar está bien, borrar lo que funciona no")
    cfg = patch.get("config")
    if cfg is not None:
        if not isinstance(cfg, dict):
            return "config debe ser un objeto"
        forbidden = [k for k in cfg if k not in ALLOWED_CONFIG_KEYS]
        if forbidden:
            return f"config solo admite {sorted(ALLOWED_CONFIG_KEYS)}; el editor no puede cambiar {forbidden} (cambiar de modelo no es mejorar el prompt)"
    return ""


ALLOWED_CONFIG_KEYS = {"max_turns"}


def _only_diagnosis(patch: Any) -> bool:
    """El editor ha diagnosticado que el fallo no se arregla con prompt (falta conocimiento o falla una tool)
    y, como se le pide, no ha tocado nada."""
    return (isinstance(patch, dict)
            and not any(k in patch for k in ("system_prompt", "skills", "config", "description"))
            and bool(patch.get("needs_knowledge") or patch.get("tool_issues")))


def _noise(report: EvalReport) -> float:
    """Error estándar de la media del informe a partir de la variabilidad entre ejecuciones
    del mismo caso. Con una sola ejecución por caso devuelve 0 (no se puede estimar)."""
    per_case: dict[str, list[float]] = {}
    for r in report.results:
        per_case.setdefault(r.case_id, []).append(r.score)
    within = [statistics.pvariance(v) for v in per_case.values() if len(v) > 1]
    if not within or not report.scored:
        return 0.0
    mean_within = sum(within) / len(within)
    # la diferencia pareada cand - base suma las dos varianzas (factor 2); ~2 errores estándar
    return (2 * mean_within / len(report.scored)) ** 0.5 * 2


@dataclass
class IterationLog:
    iteration: int
    version: str
    accepted: bool
    fit_before: float
    fit_after: float
    val_before: float | None
    val_after: float | None
    rationale: str
    reason: str = ""


@dataclass
class Trainer:
    ws: Workspace
    llm: LLM
    runner: Runner
    cfg: TrainConfig = field(default_factory=TrainConfig)
    log: list[IterationLog] = field(default_factory=list)
    human_notes: list[str] = field(default_factory=list)
    _editor_calls: int = 0

    # ------------------------------------------------------------------ eval

    def evaluate(self, pkg: AgentPackage, version: str, split: str, save: bool = True) -> EvalReport:
        """Ejecuta y puntúa todos los casos del split. Paralelo si cfg.parallel > 1
        (los backends api/cli son procesos o peticiones independientes; mock no lo necesita)."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        spec = self.ws.load_spec()
        cases = load_cases(self.ws, split)
        judge_llm = self.llm if self.cfg.use_judge else None
        jobs = [(case, run) for case in cases for run in range(self.cfg.runs_per_case)]
        results: list[CaseResult] = []
        t0 = time.time()

        def one(case: TestCase, run: int) -> CaseResult:
            trace = self.runner.run(pkg, case)
            return grade(judge_llm, spec, case, trace, run)

        workers = max(1, self.cfg.parallel) if self.runner.backend != "mock" else 1
        if workers == 1:
            for i, (case, run) in enumerate(jobs, 1):
                results.append(one(case, run))
                print(f"\r  [{split}] {i}/{len(jobs)} ejecuciones", end="", flush=True)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(one, case, run) for case, run in jobs]
                for i, f in enumerate(as_completed(futs), 1):
                    results.append(f.result())
                    print(f"\r  [{split}] {i}/{len(jobs)} ejecuciones (x{workers})", end="", flush=True)
            results.sort(key=lambda r: (r.case_id, r.run))
        print(f"  ({time.time() - t0:.1f}s)")
        infra = [r for r in results if r.infra_error]
        agent_err = [r for r in results if r.trace and r.trace.error and not r.infra_error]
        if infra:
            print(f"  ⚠ {len(infra)} ejecuciones con error de infraestructura (EXCLUIDAS del cómputo): "
                  + "; ".join(sorted({r.trace.error[:60] for r in infra})[:3]))
        if agent_err:
            print(f"  ⚠ {len(agent_err)} ejecuciones con error del agente (cuentan como fallo): "
                  + "; ".join(sorted({r.trace.error[:60] for r in agent_err})[:3]))
        report = EvalReport(version=version, split=split, results=results)
        if save:
            dump_json(self.ws.runs_dir / f"{version}-{split}.json", report.to_dict())
        return report

    # ------------------------------------------------------------------ editor

    def propose(self, pkg: AgentPackage, spec: AgentSpec, report: EvalReport, rejected_hint: str = "",
                rejected_traces: list[CaseResult] | None = None) -> dict[str, Any]:
        """Construye el prompt del editor. Solo ve FIT: nunca números ni trazas de validation/test."""
        cases = {c.id: c for c in load_cases(self.ws)}
        per_case = report.per_case()
        failures = report.failures()                       # un resultado por caso, de peor a mejor
        flaky = {cid: f"falla {sum(1 for r in rs if not r.passed)}/{len(rs)} ejecuciones"
                 for cid, rs in per_case.items() if len(rs) > 1 and 0 < sum(1 for r in rs if not r.passed) < len(rs)}
        causes: Counter[str] = Counter()
        for r in failures:
            for c in r.checks:
                if not c.passed:
                    causes[f"{c.type}: {c.detail}"] += 1
        # rotación: cada iteración muestra una ventana distinta si hay más fallos de los que caben
        window = 12
        offset = (self._editor_calls * (window // 2)) % max(1, len(failures)) if len(failures) > window else 0
        self._editor_calls += 1
        shown = (failures[offset:] + failures[:offset])[:window]

        def trace_block(r: CaseResult, label: str) -> list[str]:
            case = cases.get(r.case_id)
            tr = r.trace
            calls = []
            for c in (tr.tool_calls if tr else []):
                inp = {k: (v[:600] + "…" if isinstance(v, str) and len(v) > 600 else v) for k, v in c.input.items()}
                calls.append(f"{c.name}({json.dumps(inp, ensure_ascii=False)}) -> "
                             f"{json.dumps(c.output, ensure_ascii=False)[:160]}" + (" [ERROR]" if c.is_error else ""))
            return [
                f"--- {label} {r.case_id} score={r.score:.2f} tags={case.tags if case else []}"
                + (f" [{flaky[r.case_id]}]" if r.case_id in flaky else "") + (" [CRÍTICO fallido]" if r.critical_failed else ""),
                f"input: {case.input if case else '?'}",
                f"contexto: {json.dumps(case.context, ensure_ascii=False) if case else ''}",
                "tools: " + ("; ".join(calls) or "(ninguna)"),
                f"respuesta final: {(tr.final_text if tr else '')[:400]}",
                "checks fallidos: " + "; ".join(f"{c.type} ({c.detail})" for c in r.checks if not c.passed),
                f"juez: {r.judge_score} {r.judge_reason}" if r.judge_score is not None else "",
                f"error: {tr.error}" if tr and tr.error else "",
            ]

        blocks = [
            "ESPECIFICACIÓN:", json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), "",
            "=== SYSTEM PROMPT ACTUAL:", pkg.system_prompt, "=== FIN SYSTEM PROMPT", "",
        ]
        for name, content in pkg.skills.items():
            blocks += [f"=== SKILL {name}:", content, "=== FIN SKILL", ""]
        blocks += [f"CONFIG: {json.dumps(pkg.config)}", "",
                   f"RESULTADO EN FIT: casos que pasan={report.case_pass_rate:.0%} media={report.mean_score:.2f} "
                   f"({len(failures)} casos fallan de {len(per_case)}; {self.cfg.runs_per_case} ejecución/es por caso)", "",
                   "CAUSAS DE FALLO (agregadas):"]
        blocks += [f"- x{n}  {k}" for k, n in causes.most_common(15)]
        if flaky:
            blocks += ["", "CASOS INESTABLES (fallan solo a veces; suele ser una regla ambigua o enterrada, no ausente):"]
            blocks += [f"- {cid}: {txt}" for cid, txt in flaky.items()]
        blocks += ["", f"TRAZAS DE FALLOS ({len(shown)} de {len(failures)}):"]
        for r in shown:
            blocks += trace_block(r, "caso")
        if rejected_traces:
            blocks += ["", "LO QUE HIZO TU ÚLTIMO PARCHE (rechazado) en algunos casos que fallaron con él:"]
            for r in rejected_traces[:4]:
                blocks += trace_block(r, "candidato")
        if self.human_notes:
            blocks += ["", "NOTAS DEL HUMANO (tienen prioridad sobre tu criterio):"] + [f"- {n}" for n in self.human_notes]
        if rejected_hint:
            blocks += ["", f"AVISO: {rejected_hint}"]
        return self.llm.complete_json("editor", "\n".join(blocks))

    # ------------------------------------------------------------------ decisión

    def _decide(self, base: EvalReport, cand: EvalReport, split: str) -> tuple[bool, str]:
        """¿El candidato es mejor que la base en este split? Comparación PAREADA por caso, sobre los
        casos que ambos informes puntuaron (los excluidos por infraestructura no cuentan en ninguno).

        Fit: la media de las diferencias debe superar el umbral (min_delta o ~2 SE del ruido entre
        ejecuciones, el mayor); con una sola ejecución por caso, además, al menos un caso debe cambiar
        de estado a mejor, porque la media sola la mueve el ruido del juez. La fracción de casos que
        pasan no puede bajar y ningún caso puede empezar a fallar un check crítico.
        Validation: no puede empeorar más que su propio umbral (val_tolerance o el ruido), ni perder
        más de un caso de los que pasaban.
        """
        bs, cs = base.case_scores(), cand.case_scores()
        common = sorted(set(bs) & set(cs))
        if not common:
            return False, "sin casos comparables"
        deltas = [cs[c] - bs[c] for c in common]
        mean_delta = sum(deltas) / len(deltas)
        worse = [c for c in common if cs[c] < bs[c] - 0.15]
        better = [c for c in common if cs[c] > bs[c] + 0.15]
        base_pass = {c for c, rs in base.per_case().items() if c in cs and all(r.passed for r in rs)}
        cand_pass = {c for c, rs in cand.per_case().items() if c in bs and all(r.passed for r in rs)}
        lost, gained = sorted(base_pass - cand_pass), sorted(cand_pass - base_pass)
        base_crit = {r.case_id for r in base.scored if r.critical_failed}
        cand_crit = {r.case_id for r in cand.scored if r.critical_failed}
        new_crit = sorted(cand_crit - base_crit)
        if new_crit:
            return False, f"nuevos fallos críticos en {new_crit[:5]}"
        noise = _noise(base) if self.cfg.runs_per_case > 1 else 0.0
        if split == "fit":
            threshold = max(self.cfg.min_delta, noise)
            if mean_delta < threshold:
                return False, f"media {base.mean_score:.3f} → {cand.mean_score:.3f} (Δ pareada {mean_delta:+.3f} < umbral {threshold:.3f})"
            if self.cfg.runs_per_case == 1 and not gained and not better:
                return False, f"Δ pareada {mean_delta:+.3f} pero ningún caso mejora de verdad (±0.15 o cambio de estado): con --runs 1 eso es ruido del juez"
            if len(cand_pass) < len(base_pass):
                return False, (f"sube la media pero bajan los casos que pasan ({len(base_pass)} → {len(cand_pass)} de {len(common)}); "
                               f"rompes {lost[:5]}")
            return True, f"Δ pareada {mean_delta:+.3f}; casos que pasan {len(base_pass)} → {len(cand_pass)} de {len(common)}; mejoran {len(better)}, empeoran {len(worse)}"
        # validation / test: no empeorar
        threshold = max(self.cfg.val_tolerance, noise)
        if mean_delta < -threshold:
            return False, f"empeora claramente (Δ pareada {mean_delta:+.3f} < -{threshold:.3f}; {len(worse)} casos peores: {worse[:5]})"
        if len(lost) > max(1, len(gained)):
            return False, f"pierde {len(lost)} casos que pasaban ({lost[:5]}) y solo gana {len(gained)}"
        return True, f"Δ pareada {mean_delta:+.3f}; mejoran {len(better)}, empeoran {len(worse)}"

    # ------------------------------------------------------------------ bucle

    def train(self) -> AgentPackage:
        spec = self.ws.load_spec()
        pkg = self.ws.load_package()
        version = self.ws.next_version()
        print(f"\n=== Afinando {spec.name} desde {version} ===\n{pkg.summary()}\n")
        has_val = bool(load_cases(self.ws, "validation"))
        has_test = bool(load_cases(self.ws, "test"))

        if self.cfg.runs_per_case == 1 and self.runner.backend != "mock":
            print("  [aviso] --runs 1: no se puede estimar el ruido entre ejecuciones; la aceptación exige que algún caso "
                  "cambie de estado, pero --runs 3 es mucho más fiable.")
        # reutiliza la última versión si package/ no ha cambiado desde ella
        last = sorted(p.name for p in self.ws.versions_dir.glob("v*"))
        if last and AgentPackage.load(self.ws.versions_dir / last[-1]) == pkg:
            version = last[-1]
            print(f"  package/ es idéntico a {version}; se reutiliza como base")
        else:
            self.ws.snapshot(pkg, version, {"rationale": "(inicial)"})
        fit = self.evaluate(pkg, version, "fit")
        val = self.evaluate(pkg, version, "validation") if has_val else None
        self._check_infra(fit, val)
        self._print_scores(version, fit, val)

        no_improve = 0
        accepted = 0
        confirmed = False
        diagnoses = 0
        rejected_hint = ""
        rejected_traces: list[CaseResult] = []
        for it in range(1, self.cfg.max_iterations + 1):
            if fit.case_pass_rate >= self.cfg.target_pass_rate and (val is None or val.case_pass_rate >= self.cfg.target_pass_rate):
                if self.cfg.runs_per_case == 1 and self.runner.backend != "mock" and not confirmed:
                    # la base aceptada hereda la "suerte" de su ejecución: confirmar con una pasada nueva
                    print("  objetivo alcanzado con --runs 1: confirmando con una re-evaluación...")
                    fit = self.evaluate(pkg, version + "-confirm", "fit")
                    val = self.evaluate(pkg, version + "-confirm", "validation") if val else None
                    confirmed = True
                    self._print_scores(version + " (confirm)", fit, val)
                    continue
                print(f"\nObjetivo alcanzado ({self.cfg.target_pass_rate:.0%} de casos pasan). Paro.")
                break
            if no_improve >= self.cfg.patience:
                print(f"\n{self.cfg.patience} iteraciones sin mejora. Paro.")
                break
            if self.cfg.ask_every and it % self.cfg.ask_every == 0:
                self._ask_human(fit)

            print(f"\n--- Iteración {it} ---")
            try:
                patch = self.propose(pkg, spec, fit, rejected_hint, rejected_traces)
                problem = _validate_patch(patch, pkg)
            except Exception as e:  # noqa: BLE001  (JSON inválido, fallo del modelo...)
                patch, problem = {}, f"el editor no devolvió un parche utilizable: {type(e).__name__}: {str(e)[:200]}"
            if not problem and _only_diagnosis(patch):
                diagnoses += 1
                print("  el editor no propone cambios: diagnostica que el fallo no se arregla con prompt")
                for k in ("needs_knowledge", "tool_issues"):
                    if patch.get(k):
                        print(f"    {k}: {patch[k]}")
                self.log.append(IterationLog(it, "-", False, fit.mean_score, fit.mean_score, None, None,
                                             patch.get("rationale", ""), "diagnóstico: falta conocimiento o falla una tool"))
                if diagnoses >= 2:
                    print("  dos diagnósticos seguidos: esto no lo arregla el bucle. Paro para que lo mires.")
                    break
                rejected_hint = "Tu diagnóstico se ha registrado para el humano. Si hay OTRA causa que sí dependa del prompt, propón ese cambio; si no, repite el diagnóstico."
                continue
            diagnoses = 0
            candidate = pkg.apply_patch(patch) if not problem else pkg
            if not problem and candidate == pkg:
                problem = "el parche no cambia nada respecto a la versión actual"
            if problem:
                no_improve += 1
                rejected_hint = f"Tu última respuesta se descartó sin evaluar: {problem}. Devuelve el JSON completo y válido con un cambio real."
                rejected_traces = []
                self.log.append(IterationLog(it, "-", False, fit.mean_score, fit.mean_score,
                                             None, None, patch.get("rationale", "") if isinstance(patch, dict) else "", f"parche inválido: {problem[:60]}"))
                print(f"  DESCARTADO sin evaluar: {problem}")
                continue
            rationale = patch.get("rationale", "")
            print(f"editor: {rationale}")
            for k in ("needs_knowledge", "tool_issues"):
                if patch.get(k):
                    print(f"  {k}: {patch[k]}")
            cand_version = self.ws.next_version()
            cand_label = f"{cand_version}-cand{it}"

            cand_fit = self.evaluate(candidate, cand_label, "fit")       # siempre se guarda en runs/
            self._check_infra(cand_fit, None)
            ok, why_fit = self._decide(fit, cand_fit, "fit")
            why = why_fit
            if not ok:
                no_improve += 1
                rejected_hint = f"Tu último parche ('{rationale}') se rechazó: {why}. Prueba otra causa o una regla más general."
                rejected_traces = cand_fit.failures()
                self.ws.snapshot(candidate, f"rejected/{cand_label}", {"rationale": rationale, "reason": why})
                self.log.append(IterationLog(it, cand_label, False, fit.mean_score, cand_fit.mean_score, None, None, rationale, why[:80]))
                print(f"  RECHAZADO (fit): {why}")
                continue

            cand_val = self.evaluate(candidate, cand_label, "validation") if val else None
            if cand_val:
                self._check_infra(cand_val, None)
                ok, why_val = self._decide(val, cand_val, "validation")  # type: ignore[arg-type]
                why = f"fit: {why_fit} | validation: {why_val}"
                if not ok:
                    no_improve += 1
                    # sin números de validation: el editor no debe optimizar contra ese conjunto
                    rejected_hint = (f"Tu último parche ('{rationale}') mejoró los casos que ves pero empeoró casos que no ves: "
                                     "puede ser sobreajuste. Busca la regla general detrás de los fallos, no la que encaja con estos ejemplos; "
                                     "si la regla es correcta pero demasiado estrecha, amplíala.")
                    rejected_traces = []
                    self.ws.snapshot(candidate, f"rejected/{cand_label}", {"rationale": rationale, "reason": "sobreajuste: " + why})
                    self.log.append(IterationLog(it, cand_label, False, fit.mean_score, cand_fit.mean_score,
                                                 val.mean_score, cand_val.mean_score, rationale, "sobreajuste"))  # type: ignore[union-attr]
                    print(f"  RECHAZADO (sobreajuste): {why_val}")
                    continue

            # aceptar
            prev_fit, prev_val = fit.mean_score, (val.mean_score if val else None)
            pkg, fit, val = candidate, cand_fit, cand_val
            version = cand_version
            no_improve = 0
            confirmed = False
            rejected_hint = ""
            rejected_traces = []
            accepted += 1
            self.ws.save_package(pkg)
            for split in ("fit", "validation"):            # el run del candidato pasa a ser el de la versión
                src = self.ws.runs_dir / f"{cand_label}-{split}.json"
                if src.exists():
                    src.replace(self.ws.runs_dir / f"{cand_version}-{split}.json")
            self.ws.snapshot(pkg, cand_version, {"rationale": rationale, "patch_next": patch.get("next", ""),
                                                 "decision_fit": why_fit, "decision_validation": why if cand_val else None})
            self.log.append(IterationLog(it, cand_version, True, prev_fit, fit.mean_score,
                                         prev_val, val.mean_score if val else None, rationale))
            print(f"  ACEPTADO como {cand_version} ({why_fit})")
            self._print_scores(cand_version, fit, val)

            if self.cfg.holdout_every and accepted % self.cfg.holdout_every == 0:
                print("  generando casos holdout nuevos...")
                fresh = generate_holdout(self.ws, self.llm, self.cfg.holdout_n)
                print(f"  +{len(fresh)} casos en validation")
                val = self.evaluate(pkg, cand_version, "validation")

        # test: intacto durante todo el bucle; solo se mira aquí
        test = self.evaluate(pkg, "final", "test") if has_test else None
        write_report(self.ws, spec, pkg, self.log, fit, val, test)
        print(f"\nInforme en {self.ws.root / 'report.md'}")
        if test:
            print(f"  test (nunca visto por el editor): casos que pasan={test.case_pass_rate:.0%} media={test.mean_score:.3f}")
        print(f"Paquete final en {self.ws.package_dir}  →  exporta con: forge export {self.ws.root}")
        return pkg

    # ------------------------------------------------------------------ util

    def _print_scores(self, version: str, fit: EvalReport, val: EvalReport | None) -> None:
        v = f" | val casos={val.case_pass_rate:.0%} media={val.mean_score:.3f}" if val else ""
        print(f"  {version}: fit casos={fit.case_pass_rate:.0%} media={fit.mean_score:.3f}{v}")

    def _check_infra(self, *reports: EvalReport | None) -> None:
        """Si demasiadas ejecuciones fallaron por infraestructura, la evaluación no es fiable: abortar."""
        for rep in reports:
            if rep is None or not rep.results:
                continue
            frac = rep.infra_errors / len(rep.results)
            if frac > self.cfg.max_infra_error_rate:
                raise SystemExit(f"{rep.infra_errors}/{len(rep.results)} ejecuciones de {rep.split} fallaron por infraestructura "
                                 f"(red, límites, timeouts). No se puede decidir con eso. Revisa y relanza.")

    def _ask_human(self, fit: EvalReport) -> None:
        cases = {c.id: c for c in load_cases(self.ws)}
        doubtful = sorted(fit.failures(), key=lambda r: r.score)[:5]
        if not doubtful:
            return
        print("\n[checkpoint humano] Estos casos siguen fallando. Si quieres, escribe una nota para el editor "
              "(qué sería lo correcto). Enter para seguir.")
        for r in doubtful:
            c = cases.get(r.case_id)
            print(f"  - {r.case_id} (score {r.score:.2f}): {c.input[:120] if c else ''}")
            if r.trace:
                print(f"      tools: {', '.join(c.name for c in r.trace.tool_calls) or '(ninguna)'}")
                print(f"      respuesta: {r.trace.final_text[:300]}")
                print(f"      fallos: " + "; ".join(c.detail for c in r.checks if not c.passed)[:300])
        try:
            note = input("nota> ").strip()
        except EOFError:
            note = ""
        if note:
            self.human_notes.append(note)
