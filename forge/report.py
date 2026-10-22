"""Informe final en Markdown."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .evals import load_cases
from .package import AgentPackage, Workspace
from .schemas import AgentSpec, EvalReport

if TYPE_CHECKING:
    from .loop import IterationLog


def write_report(ws: Workspace, spec: AgentSpec, pkg: AgentPackage, log: list["IterationLog"],
                 fit: EvalReport, val: EvalReport | None, test: EvalReport | None = None) -> None:
    cases = {c.id: c for c in load_cases(ws)}
    lines = [f"# Informe de afinado: {spec.name}", "",
             f"**Tipo:** {spec.kind}  ", f"**Objetivo:** {spec.objective}", "",
             "## Resultado final", "",
             "| conjunto | casos | ejecuciones | casos que pasan | media | errores infra |", "|---|---|---|---|---|---|"]
    def row(name, r):
        return f"| {name} | {len(r.per_case())} | {len(r.results)} | {r.case_pass_rate:.0%} | {r.mean_score:.3f} | {r.infra_errors} |"
    lines.append(row("fit (lo ve el editor)", fit))
    if val:
        lines.append(row("validation (decide aceptaciones)", val))
    if test:
        lines.append(row("test (nunca visto, solo al final)", test))
    lines += ["", "La cifra que importa es **test**; si no hay, validation. Fit es optimista por construcción."]
    lines += ["", "## Iteraciones", "", "| # | versión | fit antes → después | validation | aceptado | cambio |", "|---|---|---|---|---|---|"]
    for it in log:
        v = f"{it.val_before:.3f} → {it.val_after:.3f}" if it.val_before is not None and it.val_after is not None else (f"{it.val_after:.3f}" if it.val_after is not None else "-")
        rat = (it.rationale or "").replace("|", "/")[:90]
        lines.append(f"| {it.iteration} | {it.version} | {it.fit_before:.3f} → {it.fit_after:.3f} | {v} | {'sí' if it.accepted else 'no: ' + it.reason.replace('|', '/')} | {rat} |")

    fails = fit.failures() + (val.failures() if val else []) + (test.failures() if test else [])
    if fails:
        causes: Counter[str] = Counter()
        for r in fails:
            for c in r.checks:
                if not c.passed:
                    causes[f"{c.type}: {c.detail}"] += 1
        lines += ["", "## Lo que sigue fallando", ""]
        lines += [f"- x{n} {k}" for k, n in causes.most_common(10)]
        lines += ["", "Casos:"]
        for r in fails[:15]:
            c = cases.get(r.case_id)
            lines.append(f"- `{r.case_id}` ({r.score:.2f}{', CRÍTICO' if r.critical_failed else ''}): {c.input[:100] if c else ''}")
    else:
        lines += ["", "## Lo que sigue fallando", "", "Nada en los conjuntos actuales. Añade casos nuevos antes de fiarte."]

    lines += ["", "## Paquete final", "", f"- {pkg.summary()}",
              f"- Skills: {', '.join(pkg.skills) or 'ninguna'}",
              f"- Tools (contrato): {', '.join(t.name for t in pkg.tools) or 'ninguna'}", "",
              "## Cómo trasladarlo", "",
              "1. `forge export <workspace>` genera un zip con `package/`, `evals/` y `spec.json`.",
              "2. En el entorno destino, implementa cada tool del contrato (conector MCP o tool propia) con el mismo nombre.",
              "3. Pon el nombre real de tu servidor MCP en `package/config.json` (`mcp_server`) y copia `package/agent.md` a `.claude/agents/` y `package/skills/*` a `.claude/skills/` (o usa el system prompt con el SDK).",
              "4. Vuelve a ejecutar `forge run` allí con las tools reales para confirmar que nada se rompe.", ""]
    (ws.root / "report.md").write_text("\n".join(lines), encoding="utf-8")
