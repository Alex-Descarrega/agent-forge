"""Tests unitarios de la lógica que no debe depender de ningún modelo.
python -m pytest tests  (o python tests/test_units.py)"""
import json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forge.schemas import (Trace, ToolCall, Check, CheckResult, CaseResult, EvalReport, TestCase,
                           resolve_tool_response, AgentSpec)
from forge.graders import run_checks, _first_json_object
from forge.llm import extract_json
from forge.package import AgentPackage, Workspace, _split_frontmatter
from forge.loop import Trainer, TrainConfig, _validate_patch, _noise
from forge.evals import assign_splits, save_cases, load_cases
from forge.runner import Runner


# ---------------------------------------------------------------- helpers

def cr(cid, score, run=0, critical=False, infra=False):
    """CaseResult sintético con un score dado (vía un único check ponderado)."""
    checks = [CheckResult("x", score >= 0.8, 1.0, critical, "")] if not critical else [CheckResult("x", False, 1.0, True, "")]
    r = CaseResult(cid, run, checks, judge_score=None, trace=Trace(cid, "", infra_error=infra))
    # forzamos score exacto sobreescribiendo deterministic_score
    if not critical:
        r.checks = [CheckResult("a", True, score, False, ""), CheckResult("b", False, 1 - score, False, "")]
    return r


def report(scores: dict, version="v", split="fit", runs=1):
    return EvalReport(version, split, [cr(c, s, run=k) for c, s in scores.items() for k in range(runs)])


def trainer(**cfg):
    ws = Workspace(Path(tempfile.mkdtemp()))
    ws.init()
    ws.save_spec(AgentSpec("a", "specialist", "obj"))
    save_cases(ws, [])
    return Trainer(ws, None, Runner("mock"), TrainConfig(**cfg))


# ---------------------------------------------------------------- decisión

def test_decide_accepts_real_improvement():
    t = trainer()
    ok, why = t._decide(report({"a": 0.5, "b": 0.5, "c": 0.9}), report({"a": 0.9, "b": 0.9, "c": 0.9}), "fit")
    assert ok, why


def test_decide_rejects_tiny_delta():
    t = trainer(min_delta=0.05)
    ok, why = t._decide(report({"a": 0.5, "b": 0.5}), report({"a": 0.52, "b": 0.51}), "fit")
    assert not ok and "umbral" in why


def test_decide_rejects_mean_up_but_passrate_down():
    t = trainer()
    base = report({"a": 0.85, "b": 0.85, "c": 0.3, "d": 0.3})
    cand = report({"a": 0.7, "b": 0.7, "c": 0.75, "d": 0.75})   # media sube, pasan 0 en vez de 2
    ok, why = t._decide(base, cand, "fit")
    assert not ok and "bajan los casos que pasan" in why


def test_decide_rejects_new_critical_failure():
    t = trainer()
    base = report({"a": 0.5, "b": 0.5})
    cand = EvalReport("v", "fit", [cr("a", 0.95), cr("b", 0.0, critical=True)])
    ok, why = t._decide(base, cand, "fit")
    assert not ok and "crítico" in why


def test_decide_validation_tolerates_small_drop_but_not_big():
    t = trainer(val_tolerance=0.02)
    assert t._decide(report({"a": 0.9, "b": 0.9}), report({"a": 0.89, "b": 0.9}), "validation")[0]
    assert not t._decide(report({"a": 0.9, "b": 0.9}), report({"a": 0.6, "b": 0.9}), "validation")[0]


def test_noise_grows_with_variance_and_is_zero_for_single_runs():
    assert _noise(report({"a": 0.5, "b": 0.7})) == 0.0
    noisy = EvalReport("v", "fit", [cr("a", 0.2, 0), cr("a", 0.9, 1), cr("b", 0.3, 0), cr("b", 0.95, 1)])
    stable = EvalReport("v", "fit", [cr("a", 0.5, 0), cr("a", 0.52, 1), cr("b", 0.5, 0), cr("b", 0.51, 1)])
    assert _noise(noisy) > _noise(stable) > 0


# ---------------------------------------------------------------- report

def test_infra_errors_excluded_and_case_pass_rate():
    rep = EvalReport("v", "fit", [cr("a", 0.9, 0), cr("a", 0.3, 1), cr("b", 0.9), cr("c", 0.0, infra=True)])
    assert rep.infra_errors == 1
    assert len(rep.scored) == 3
    assert rep.pass_rate == 2 / 3                 # ejecuciones
    assert rep.case_pass_rate == 0.5              # a falla 1 de 2, b pasa
    assert [r.case_id for r in rep.failures()] == ["a"]


def test_critical_check_zeroes_score():
    r = CaseResult("x", 0, [CheckResult("a", True, 5.0), CheckResult("never", False, 0.1, True)], judge_score=1.0)
    assert r.score == 0.0 and r.critical_failed


# ---------------------------------------------------------------- parches

def test_validate_patch():
    pkg = AgentPackage("n", "d", "x" * 400)
    assert _validate_patch({"system_prompt": "y" * 400}, pkg) == ""
    assert "nada" in _validate_patch({"rationale": "solo texto"}, pkg)
    assert "corto" in _validate_patch({"system_prompt": ""}, pkg)
    assert "40%" in _validate_patch({"system_prompt": "y" * 100}, pkg)
    assert "objeto" in _validate_patch({"skills": []}, pkg)
    assert "contrato" in _validate_patch({"tools": []}, pkg)
    assert _validate_patch("no json", pkg)


def test_apply_patch_null_safe_and_noop_detection():
    pkg = AgentPackage("n", "d", "prompt " * 20, skills={"s": "contenido"})
    same = pkg.apply_patch({"skills": None, "config": None})
    assert same == pkg
    changed = pkg.apply_patch({"skills": {"s": None}})
    assert changed != pkg and "s" not in changed.skills


def test_frontmatter_roundtrip_with_colon_in_description():
    pkg = AgentPackage("n", "specialist: hace cosas, con: dos puntos", "cuerpo del prompt", config={"mcp_server": "zendesk"})
    md = pkg.render_agent_md()
    fm, body = _split_frontmatter(md)
    assert fm["description"] == "specialist: hace cosas, con: dos puntos"
    assert "mcp__zendesk__" in md or fm["tools"] == "Read"
    assert body.strip() == "cuerpo del prompt"


# ---------------------------------------------------------------- graders

def test_text_checks_see_tool_inputs():
    t = Trace("c", "He respondido al cliente.", [ToolCall("responder", {"texto": "Te garantizo el reembolso"})])
    res = run_checks(t, [Check("not_contains", "garantizo"), Check("not_contains", {"text": "garantizo", "scope": "final"})])
    assert res[0].passed is False and res[1].passed is True


def test_new_tool_checks():
    t = Trace("c", "", [ToolCall("buscar", {"id": "T-1001"}), ToolCall("responder", {"texto": "hola"}), ToolCall("responder", {"texto": "adiós"})])
    res = run_checks(t, [
        Check("tool_input_equals", {"tool": "buscar", "field": "id", "value": "T-1"}),       # no: T-1001 != T-1
        Check("tool_input_contains", {"tool": "buscar", "field": "id", "value": "T-1"}),     # sí: substring
        Check("tool_call_count", {"tool": "responder", "count": 2}),
        Check("tool_call_count", {"tool": "responder", "max": 1}),
        Check("tool_input_not_contains", {"tool": "responder", "field": "texto", "value": "adiós"}),
    ])
    assert [r.passed for r in res] == [False, True, True, False, False]


def test_asks_question_and_json_robust():
    t = Trace("c", "Claro.\n\n¿Me pasas el número de pedido? ", [])
    assert run_checks(t, [Check("asks_question")])[0].passed
    t2 = Trace("c", 'Resumen: {"a": 1} y también {"b": 2}', [])
    assert run_checks(t2, [Check("json_has_keys", ["a"])])[0].passed
    assert _first_json_object("```json\n{\"k\": [1,2]}\n```") == {"k": [1, 2]}


def test_extract_json_with_braces_in_prompt_text():
    txt = 'Aquí va:\n```json\n{"rationale": "x", "system_prompt": "usa {placeholders} y } raros"}\n```\ngracias'
    assert extract_json(txt)["system_prompt"].endswith("raros")


def test_resolve_tool_response_rules():
    tr = {"buscar": [{"match": {"id": "T-1"}, "response": {"ok": 1}}, {"match": {}, "response": {"error": "nf"}, "is_error": True}]}
    assert resolve_tool_response(tr, "buscar", {"id": "t-1 "}) == ({"ok": 1}, False)
    assert resolve_tool_response(tr, "buscar", {"id": "T-2"}) == ({"error": "nf"}, True)
    assert resolve_tool_response({"x": {"fijo": 1}}, "x", {})[0] == {"fijo": 1}
    assert resolve_tool_response({}, "y", {"a": 1})[0]["simulated"]


def test_from_dict_ignores_unknown_keys():
    c = TestCase.from_dict({"id": "a", "input": "x", "expected": "algo que inventó el modelo", "checks": [{"type": "contains", "value": "y", "foo": 1}]})
    assert c.meta["expected"] and c.checks[0].value == "y"
    s = AgentSpec.from_dict({"name": "n", "kind": "specialist", "objective": "o", "tools": [{"name": "t", "description": "d", "extra": 1}], "nuevo": 2})
    assert s.tools[0].name == "t" and s.meta["nuevo"] == 2


# ---------------------------------------------------------------- splits

def test_three_way_split_and_unique_ids():
    cases = [TestCase(f"c{i}", "x", tags=["t" if i % 2 else "u"]) for i in range(20)]
    assign_splits(cases, 0.25, 0.15, seed=1)
    splits = {c.split for c in cases}
    assert splits == {"fit", "validation", "test"}
    ws = Workspace(Path(tempfile.mkdtemp())); ws.init()
    dup = [TestCase("same", "a"), TestCase("same", "b"), TestCase("same", "c")]
    save_cases(ws, dup)
    assert sorted(c.id for c in load_cases(ws)) == ["same", "same_1", "same_2"]


# ---------------------------------------------------------------- mcp_sim

def test_mcp_sim_protocol():
    d = Path(tempfile.mkdtemp())
    log = d / "log.jsonl"
    cfg = d / "case.json"
    cfg.write_text(json.dumps({
        "tools": [{"name": "buscar", "description": "d", "input_schema": {"id": "string"}, "required": ["id"]}],
        "tool_responses": {"buscar": [{"match": {"id": "T-1"}, "response": {"ok": 1}}, {"match": {}, "response": {"e": 1}, "is_error": True}]},
        "trace_log": str(log),
    }))
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "buscar", "arguments": {"id": "T-1"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "buscar", "arguments": {"id": "T-9"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "nope"},
    ]
    proc = subprocess.run([sys.executable, "-m", "forge.mcp_sim", str(cfg)], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                          capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    out = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    assert [o["id"] for o in out] == [1, 2, 3, 4, 5]
    assert out[1]["result"]["tools"][0]["inputSchema"]["required"] == ["id"]
    assert out[2]["result"]["isError"] is False and out[3]["result"]["isError"] is True
    assert "error" in out[4]
    assert len(log.read_text().splitlines()) == 2


# ---------------------------------------------------------------- bucle con runner programado

class ScriptedRunner:
    """Devuelve trazas que pasan/fallan según una tabla: version_marker -> {case_id: pasa}."""
    backend = "scripted"
    def __init__(self, table): self.table = table; self.retries = 0
    def run(self, pkg, case):
        hits = [k for k in self.table if k != "base" and k in pkg.system_prompt]
        marker = max(hits, key=len) if hits else "base"
        ok = self.table[marker].get(case.id, False)
        return Trace(case.id, "ok" if ok else "mal", [ToolCall("t", {})] if ok else [], 1)


class ScriptedLLM:
    """Editor que añade un marcador por iteración; juez no se usa."""
    def __init__(self, markers): self.markers = list(markers); self.i = 0
    def complete_json(self, role, user, history=None):
        assert role == "editor"
        m = self.markers[self.i % len(self.markers)]; self.i += 1
        base = user.split("=== SYSTEM PROMPT ACTUAL:\n", 1)[1].split("\n=== FIN SYSTEM PROMPT", 1)[0]
        return {"rationale": f"añadir {m}", "system_prompt": base + f"\n{m}"}


def test_loop_accepts_rejects_and_detects_overfit():
    ws = Workspace(Path(tempfile.mkdtemp())); ws.init()
    ws.save_spec(AgentSpec("a", "specialist", "obj"))
    cases = [TestCase(f"f{i}", "x", checks=[Check("tool_called", "t")], split="fit") for i in range(4)] + \
            [TestCase(f"v{i}", "x", checks=[Check("tool_called", "t")], split="validation") for i in range(2)]
    save_cases(ws, cases)
    ws.save_package(AgentPackage("a", "d", "instrucciones iniciales " * 10))
    table = {
        "base": {},                                                             # todo falla
        "M1": {"f0": True, "f1": True, "v0": True, "v1": True},                # mejora real → aceptar
        "M1\nM2": {"f0": True, "f1": True, "f2": True, "v0": False, "v1": False},  # sube fit, hunde val → sobreajuste
        "M1\nM3": {"f0": True, "f1": True, "f2": True, "f3": True, "v0": True, "v1": True},  # bien → aceptar
    }
    llm = ScriptedLLM(["M1", "M2", "M3"])
    tr = Trainer(ws, llm, ScriptedRunner(table), TrainConfig(max_iterations=3, use_judge=False, patience=5))
    tr.train()
    acc = [l for l in tr.log if l.accepted]
    rej = [l for l in tr.log if not l.accepted]
    assert len(acc) == 2 and len(rej) == 1 and rej[0].reason == "sobreajuste"
    assert ws.load_package().system_prompt.endswith("M1\nM3")
    assert (ws.versions_dir / "rejected").exists()
    assert (ws.root / "report.md").exists()




# ---------------------------------------------------------------- ronda 2

from forge.runner import parse_cli_result, is_infra_exception, clean_env
from forge.graders import grade
from forge.loop import _only_diagnosis


def test_cli_error_text_never_counts_as_answer():
    data = {"is_error": True, "result": "Usage limit reached. Try again later.", "num_turns": 1}
    t = parse_cli_result("c", data, [])
    assert t.final_text == "" and t.error and t.raw["infra"] is True
    res = run_checks(t, [Check("not_contains", "garantizo"), Check("tool_not_called", "escalar")])
    assert all(not r.passed for r in res)          # un error de ejecución no "pasa" nada
    agent_err = parse_cli_result("c", {"is_error": True, "result": "Invalid tool input: ticket_id"}, [])
    assert agent_err.raw["infra"] is False and agent_err.final_text == ""


def test_infra_exception_classification():
    import subprocess
    assert is_infra_exception(subprocess.TimeoutExpired("x", 1))
    assert is_infra_exception(ConnectionError())
    assert not is_infra_exception(ModuleNotFoundError("anthropic"))
    assert not is_infra_exception(ValueError("backend desconocido"))
    assert not is_infra_exception(FileNotFoundError())


def test_runner_reraises_bugs_instead_of_hiding_them():
    r = Runner("nope")
    try:
        r.run(AgentPackage("a", "d", "p"), TestCase("c", "x"))
        assert False, "debería haber lanzado"
    except ValueError:
        pass


def test_clean_env_drops_session_vars():
    import os
    os.environ["CLAUDECODE"] = "1"; os.environ["CLAUDE_CODE_FOO"] = "1"; os.environ["HTTPS_PROXY"] = "x"
    env = clean_env()
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_FOO" not in env
    assert env.get("HTTPS_PROXY") == "x" and "PATH" in env


def test_judge_failure_marks_infra_not_higher_score():
    class BadJudge:
        def complete_json(self, role, user, history=None): raise RuntimeError("red")
    case = TestCase("c", "x", checks=[Check("contains", "hola")], rubric="tono")
    t = Trace("c", "hola", [])
    r = grade(BadJudge(), AgentSpec("a", "specialist", "o"), case, t)
    assert r.infra_error and r.judge_score is None


def test_validate_patch_allows_moving_content_to_skill_but_not_deleting():
    pkg = AgentPackage("n", "d", "x" * 1200)
    moved = {"system_prompt": "rol y límites " * 20, "skills": {"procedimiento": "y" * 1000}}
    assert _validate_patch(moved, pkg) == ""
    deleted = {"system_prompt": "rol y límites " * 20}
    assert "40%" in _validate_patch(deleted, pkg)
    assert "modelo" in _validate_patch({"config": {"model": "opus"}}, pkg)
    assert _validate_patch({"config": {"max_turns": 8}}, pkg) == ""


def test_only_diagnosis_patch():
    assert _only_diagnosis({"rationale": "falta la política", "needs_knowledge": ["política de devoluciones"]})
    assert not _only_diagnosis({"needs_knowledge": ["x"], "system_prompt": "y" * 100})
    assert not _only_diagnosis({"rationale": "nada"})


def test_decide_with_runs_uses_noise_threshold_and_paired_passrates():
    t = trainer(runs_per_case=2, min_delta=0.01)
    base = EvalReport("v", "fit", [cr("a", 0.3, 0), cr("a", 0.9, 1), cr("b", 0.4, 0), cr("b", 0.95, 1), cr("c", 0.9, 0), cr("c", 0.9, 1)])
    cand = EvalReport("v", "fit", [cr("a", 0.6, 0), cr("a", 0.7, 1), cr("b", 0.7, 0), cr("b", 0.7, 1), cr("c", 0.9, 0), cr("c", 0.9, 1)])
    ok, why = t._decide(base, cand, "fit")      # media sube +0.05 pero el ruido es grande
    assert not ok and "umbral" in why
    # un caso excluido por infra en el candidato no cuenta como "caso perdido"
    base2 = report({"a": 0.9, "b": 0.9, "c": 0.3})
    cand2 = EvalReport("v", "fit", [cr("a", 0.9), cr("b", 0.0, infra=True), cr("c", 0.9)])
    ok, why = t._decide(base2, cand2, "fit")
    assert ok, why


def test_decide_runs1_requires_a_real_case_change():
    t = trainer(min_delta=0.01)
    ok, why = t._decide(report({"a": 0.8, "b": 0.85, "c": 0.9}), report({"a": 0.86, "b": 0.86, "c": 0.9}), "fit")
    assert not ok and "ruido" in why


def test_validation_tolerates_single_noisy_case():
    t = trainer(val_tolerance=0.02)
    base = report({f"v{i}": 0.85 for i in range(6)})
    cand = report({**{f"v{i}": 0.85 for i in range(5)}, "v5": 0.78})
    ok, why = t._decide(base, cand, "validation")
    assert ok, why


def test_editor_prompt_never_sees_validation_or_test():
    """La promesa metodológica central: el editor solo ve fit."""
    ws = Workspace(Path(tempfile.mkdtemp())); ws.init()
    ws.save_spec(AgentSpec("a", "specialist", "obj"))
    cases = [TestCase("fit_caso", "input de fit SECRETO_FIT", checks=[Check("tool_called", "t")], split="fit"),
             TestCase("val_caso", "input de validation SECRETO_VAL", checks=[Check("tool_called", "t")], split="validation"),
             TestCase("test_caso", "input de test SECRETO_TEST", checks=[Check("tool_called", "t")], split="test")]
    save_cases(ws, cases)
    ws.save_package(AgentPackage("a", "d", "instrucciones iniciales " * 10))
    seen = []
    class SpyLLM:
        def complete_json(self, role, user, history=None):
            seen.append(user)
            base = user.split("=== SYSTEM PROMPT ACTUAL:\n", 1)[1].split("\n=== FIN SYSTEM PROMPT", 1)[0]
            return {"rationale": "r", "system_prompt": base + f"\nM{len(seen)}"}
    table = {"base": {}, "M1": {"fit_caso": True, "val_caso": False, "test_caso": False}, "M1\nM2": {"fit_caso": True}}
    tr = Trainer(ws, SpyLLM(), ScriptedRunner(table), TrainConfig(max_iterations=2, use_judge=False, patience=5))
    tr.train()
    assert seen, "el editor no fue llamado"
    for prompt in seen:
        assert "SECRETO_VAL" not in prompt and "SECRETO_TEST" not in prompt and "val_caso" not in prompt and "test_caso" not in prompt
        assert "validation" not in prompt.lower().replace("casos que no ves", "")  # ni la palabra con cifras
    # el split test no se evaluó hasta el final
    assert (ws.runs_dir / "final-test.json").exists()


def test_split_quotas_global_with_small_tag_groups():
    cases = [TestCase(f"c{i}", "x", tags=[f"t{i % 7}"]) for i in range(30)]   # 7 tags de 4-5 casos
    assign_splits(cases, 0.25, 0.15, seed=3)
    n = {s: sum(1 for c in cases if c.split == s) for s in ("fit", "validation", "test")}
    assert n["test"] >= 4 and n["validation"] >= 7 and n["fit"] >= 15, n
    assert len({c.tags[0] for c in cases if c.split == "test"}) >= 3   # test tiene variedad de tags


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f(); print("ok", f.__name__)
