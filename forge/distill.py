"""Fase 1b: destilar skills (estructura, metodología, estilo) a partir de las muestras.

Es el paso de "ingeniería inversa": para agentes que producen documentos (propuestas, informes,
emails) la metodología no sale de la entrevista sino de los ejemplos reales. Produce:
  - package/skills/<nombre>/SKILL.md por cada skill destilada
  - spec.json actualizado (criterios, límites, tools, methodology, notes)
  - distill.report.md con la valoración de cada muestra y las preguntas abiertas
"""

from __future__ import annotations

import json
from pathlib import Path

from .llm import LLM
from .package import AgentPackage, Workspace
from .schemas import ToolContract, dump_json

MAX_CHARS_FULL = 120_000         # una muestra "completa" va ENTERA hasta aquí (un deck de 60 slides ≈ 60-80k)
MAX_TOTAL_CHARS = 400_000        # presupuesto total de contexto (~100k tokens)
N_FULL_DEFAULT = 4               # cuántas muestras van enteras; el resto, solo esqueleto


def _skeleton(text: str, max_chars: int = 2_500) -> str:
    """Esqueleto de un documento: títulos de diapositiva/sección y primeras líneas de cada una.
    Sirve para ver el patrón de estructura de muchas muestras sin leerlas enteras."""
    out, cur = [], 0
    for line in text.splitlines():
        st = line.strip()
        if not st:
            continue
        if st.startswith("#") or (len(st) < 60 and st.isupper()) or st[:3] in {".01", ".02", ".03", ".04", ".05", ".06", ".07", ".08", ".09", ".10"}:
            out.append(st); cur = 0
        elif cur < 2:
            out.append("   " + st[:120]); cur += 1
    sk = "\n".join(out)
    return sk[:max_chars] + ("\n[...]" if len(sk) > max_chars else "")


def _pick_full(samples: list[dict], n: int) -> list[int]:
    """Elige n muestras para ir enteras, maximizando variedad: agrupa por palabras clave del nombre
    (plataforma, tipo) y toma una de cada grupo en round-robin; prioriza .good."""
    import re
    keys = ("shopify", "prestashop", "logicommerce", "wordpress", "woocommerce", "magento", "migraci", "b2b", "pim", "erp")
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(samples):
        name = s["file"].lower()
        k = next((k for k in keys if k in name), "otros")
        groups.setdefault(k, []).append(i)
    for g in groups.values():
        g.sort(key=lambda i: (samples[i]["label"] != "good", -len(samples[i]["content"])))
    chosen: list[int] = []
    while len(chosen) < n and any(groups.values()):
        for g in list(groups.values()):
            if g and len(chosen) < n:
                chosen.append(g.pop(0))
    return sorted(chosen)


def run_distill(ws: Workspace, llm: LLM, max_samples: int | None = None, n_full: int = N_FULL_DEFAULT,
                focus: list[str] | None = None) -> dict:
    spec = ws.load_spec()
    samples = ws.load_samples()
    if not samples:
        raise SystemExit(f"No hay muestras en {ws.samples_dir}. Deja ahí tus documentos (.md/.txt) y repite.")
    if max_samples:
        samples = samples[:max_samples]

    # Estrategia: n_full muestras ENTERAS (variadas) + esqueleto del resto. Así se ven todas las secciones
    # de las completas (incluido el presupuesto, al final) y el patrón común de todas las demás.
    full_idx = _pick_full(samples, n_full)
    blocks, total = [], 0
    n_full_used = 0
    for i in full_idx:
        s = samples[i]
        content = s["content"]
        if len(content) > MAX_CHARS_FULL:
            # no recortamos por el centro: una muestra "completa" que no lo es engaña al destilador
            print(f"[destilador] {s['file'][:50]} tiene {len(content)//1000}k chars, demasiado para ir entera; pasa a esqueleto")
            continue
        if total + len(content) > MAX_TOTAL_CHARS:
            break
        blocks += [f"=== MUESTRA COMPLETA {s['file']} [{s['label']}] ===", content, ""]
        total += len(content); n_full_used += 1
    n_skel = 0
    for i, s in enumerate(samples):
        if i in full_idx[:n_full_used]:
            continue
        sk = _skeleton(s["content"])
        if total + len(sk) > MAX_TOTAL_CHARS:
            break
        blocks += [f"=== ESQUELETO {s['file']} [{s['label']}] (solo títulos y primeras líneas) ===", sk, ""]
        total += len(sk); n_skel += 1
    print(f"[destilador] {n_full_used} muestras completas + {n_skel} esqueletos de {len(samples)} ({total // 1000}k chars)")
    if n_full_used:
        print("   completas: " + ", ".join(samples[i]["file"][:50] for i in full_idx[:n_full_used]))

    prev_pkg = ws.load_package() if (ws.package_dir / "agent.md").exists() else None
    prev_block: list[str] = []
    if prev_pkg and prev_pkg.skills:
        prev_block = ["SKILLS DE UNA PASADA ANTERIOR (refínalas con lo que ahora veas; mantén los nombres):"]
        for name, content in prev_pkg.skills.items():
            prev_block += [f"--- {name} ---", content[:6000], ""]
        prev_report = ws.root / "distill.report.md"
        if prev_report.exists():
            prev_block += ["PREGUNTAS ABIERTAS DE LA PASADA ANTERIOR (no repitas las que ahora puedas resolver):",
                           prev_report.read_text(encoding="utf-8")[-3000:], ""]
    prompt = ["ESPECIFICACIÓN ACTUAL:", json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), "", *prev_block,
              f"MUESTRAS: {n_full_used} completas (léelas enteras, incluido el final) y {n_skel} esqueletos (solo para ver el patrón de secciones y su variación).",
              *blocks,
              "Extrae estructura, metodología y estilo. Devuelve el JSON del formato indicado."]
    from .llm import extract_json, salvage_json
    # Dos llamadas: (1) skills + spec_updates, que es lo que importa; (2) valoración de muestras y
    # preguntas abiertas. Juntas en un JSON se truncan con 40+ muestras.
    text = llm.complete("distiller", "\n".join(prompt + [
        "\nEN ESTA LLAMADA devuelve SOLO las claves `document_type`, `skills` y `spec_updates`. "
        "No incluyas `sample_quality` ni `open_questions` todavía."]))
    (ws.root / "distill.raw.txt").write_text(text, encoding="utf-8")
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        data = salvage_json(text)
        if not data.get("skills"):
            raise SystemExit(f"El destilador devolvió una salida cortada y no se pudo recuperar nada útil. "
                             f"Salida cruda en {ws.root / 'distill.raw.txt'}. Prueba con --full 4.")
        print(f"[destilador] salida cortada; recuperadas las claves completas: {sorted(data)}")
    try:
        text2 = llm.complete("distiller", "\n".join(prompt + [
            "\nYa has producido las skills en una llamada anterior. EN ESTA LLAMADA devuelve SOLO `sample_quality` "
            "(una frase por muestra, máximo 25 muestras: las completas y las más llamativas) y `open_questions` (máximo 15)."]))
        (ws.root / "distill.raw2.txt").write_text(text2, encoding="utf-8")
        try:
            data2 = extract_json(text2)
        except (ValueError, json.JSONDecodeError):
            data2 = salvage_json(text2)
        data.setdefault("sample_quality", data2.get("sample_quality") or {})
        data.setdefault("open_questions", data2.get("open_questions") or [])
    except Exception as e:  # noqa: BLE001
        print(f"[destilador] la valoración de muestras falló ({type(e).__name__}); las skills sí se han guardado")
        data.setdefault("sample_quality", {}); data.setdefault("open_questions", [])

    apply_distill_output(ws, data, n_full_used=n_full_used, n_skel=n_skel, samples=samples, full_idx=full_idx)
    if focus:
        refine_sections(ws, llm, focus, samples)
    return data


def _section_slices(text: str, keywords: list[str], window: int = 9_000) -> list[str]:
    """Trozos del documento alrededor de cada aparición de las palabras clave (títulos de sección)."""
    low = text.lower()
    out, used = [], []
    for kw in keywords:
        start = 0
        while True:
            i = low.find(kw.lower(), start)
            if i == -1:
                break
            if not any(a <= i <= b for a, b in used):
                a, b = max(0, i - 500), min(len(text), i + window)
                out.append(text[a:b]); used.append((a, b))
            start = i + len(kw)
    return out


def refine_sections(ws: Workspace, llm: LLM, keywords: list[str], samples: list[dict]) -> None:
    """Pasada focalizada: solo los trozos de MUCHAS muestras donde aparecen unas secciones concretas
    (p. ej. presupuesto, soporte), para extraer su formato exacto y actualizar la skill de estructura."""
    from .llm import extract_json, salvage_json
    pkg = ws.load_package()
    blocks, total = [], 0
    n = 0
    for s in samples:
        for sl in _section_slices(s["content"], keywords):
            if total + len(sl) > MAX_TOTAL_CHARS:
                break
            blocks += [f"=== {s['file']} (fragmento) ===", sl, ""]
            total += len(sl); n += 1
    if not blocks:
        print(f"[destilador] no se encontraron las secciones {keywords} en las muestras")
        return
    print(f"[destilador] pasada focalizada en {keywords}: {n} fragmentos de {len({b for b in blocks if b.startswith('===')})} muestras ({total//1000}k chars)")
    struct_name = next((k for k in pkg.skills if k.startswith("estructura")), None)
    prompt = ["Esta es una pasada FOCALIZADA. Ya existe una skill de estructura; su texto actual es:", "",
              pkg.skills.get(struct_name, "(ninguna)") if struct_name else "(ninguna)", "",
              f"Las secciones {keywords} estaban marcadas como no vistas o incompletas. Abajo tienes fragmentos de muchas muestras "
              "centrados en esas secciones. Extrae su formato EXACTO: títulos, tablas (columnas y filas típicas), planes o tarifas "
              "que aparecen, qué es texto fijo y qué varía, IVA, condiciones y forma de pago si constan, y qué datos de entrada necesita cada una.",
              "Devuelve JSON: {\"skills\": {\"<nombre de la skill de estructura>\": \"texto COMPLETO actualizado con esas secciones ya detalladas\"}, "
              "\"spec_updates\": {\"success_criteria_add\": [...], \"never_do_add\": [...]}, \"open_questions\": [...]}", "",
              *blocks]
    text = llm.complete("distiller", "\n".join(prompt))
    (ws.root / "distill.raw.sections.txt").write_text(text, encoding="utf-8")
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        data = salvage_json(text)
    if not data.get("skills"):
        print(f"[destilador] la pasada focalizada no devolvió skills; salida en distill.raw.sections.txt")
        return
    apply_distill_output(ws, {**data, "document_type": "(pasada focalizada)", "sample_quality": {}}, samples=samples)


def apply_distill_output(ws: Workspace, data: dict, n_full_used: int = 0, n_skel: int = 0, samples: list | None = None, full_idx: list | None = None) -> None:
    """Vuelca skills a package/, actualiza spec.json y escribe distill.report.md."""
    spec = ws.load_spec()
    samples = samples or []
    full_idx = full_idx or []
    # skills → package/ (crea el paquete si no existe)
    pkg = ws.load_package() if (ws.package_dir / "agent.md").exists() else AgentPackage.initial_from_spec(spec)
    skills = data.get("skills") or {}
    for name, content in skills.items():
        if isinstance(content, str) and content.strip():
            pkg.skills[name] = content.strip() + "\n"
    # spec updates
    upd = data.get("spec_updates") or {}
    for c in upd.get("success_criteria_add") or []:
        if c not in spec.success_criteria:
            spec.success_criteria.append(c)
    for c in upd.get("never_do_add") or []:
        if c not in spec.never_do:
            spec.never_do.append(c)
    existing_tools = {t.name for t in spec.tools}
    for t in upd.get("tools_add") or []:
        if isinstance(t, dict) and t.get("name") and t["name"] not in existing_tools:
            tc = ToolContract.from_dict(t)
            spec.tools.append(tc)
            pkg.tools.append(tc)
    if upd.get("methodology") and not spec.methodology.strip():
        spec.methodology = upd["methodology"]
    if upd.get("notes_add"):
        spec.notes = (spec.notes + "\n" if spec.notes else "") + "[destilador] " + upd["notes_add"]
    ws.save_spec(spec)
    # el prompt v0 debe decir al agente que cargue las skills
    if skills and "## Skills" not in pkg.system_prompt:
        pkg.system_prompt += ("\n\n## Skills\nAntes de producir un documento carga las skills que correspondan: "
                              + ", ".join(f"`{n}`" for n in skills) + ". Sigue su estructura y metodología al pie de la letra.")
    ws.save_package(pkg)

    # informe
    lines = [f"# Destilado de muestras: {data.get('document_type', '')}", "",
             f"Muestras: {n_full_used} completas + {n_skel} esqueletos de {len(samples)}. Skills generadas: {', '.join(skills) or 'ninguna'}.", "",
             "Completas: " + ", ".join(samples[i]["file"] for i in full_idx[:n_full_used]), "",
             "## Calidad de las muestras", ""]
    for k, v in (data.get("sample_quality") or {}).items():
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## Preguntas abiertas (responde editando spec.json o las skills)", ""]
    lines += [f"- {q}" for q in (data.get("open_questions") or [])] or ["- ninguna"]
    lines += ["", "## Cambios en la spec", "", f"- criterios añadidos: {upd.get('success_criteria_add') or []}",
              f"- límites añadidos: {upd.get('never_do_add') or []}", f"- tools añadidas: {[t.get('name') for t in (upd.get('tools_add') or [])]}"]
    rpt = ws.root / "distill.report.md"
    if data.get("document_type") == "(pasada focalizada)" and rpt.exists():
        rpt.write_text(rpt.read_text(encoding="utf-8") + "\n\n---\n\n" + "\n".join(lines), encoding="utf-8")
    else:
        rpt.write_text("\n".join(lines), encoding="utf-8")
    print(f"Skills en {ws.package_dir / 'skills'}: {', '.join(skills) or 'ninguna'}")
    print(f"Spec actualizada. Informe en {ws.root / 'distill.report.md'}")
    if data.get("open_questions"):
        print("Preguntas abiertas:")
        for q in data["open_questions"]:
            print(f"  - {q}")
