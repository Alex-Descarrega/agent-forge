"""python -m pytest tests  (o python tests/test_pipeline.py)"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forge.schemas import Trace, ToolCall, Check
from forge.graders import run_checks
from forge.cli import main


def test_checks():
    t = Trace("c", "Necesito tu número de pedido, ¿me lo pasas?", [ToolCall("buscar_ticket", {"ticket_id": "T-1"}), ToolCall("escalar", {"motivo": "legal"})], 2)
    res = run_checks(t, [
        Check("tool_called", "escalar"), Check("tool_not_called", "responder"),
        Check("tool_called_before", ["buscar_ticket", "escalar"]), Check("asks_question"),
        Check("contains", "pedido"), Check("tool_input_contains", {"tool": "escalar", "field": "motivo", "value": "legal"}),
        Check("tool_calls_max", 2), Check("turns_max", 3), Check("not_contains", "garantizo"),
    ])
    assert all(r.passed for r in res), [r.detail for r in res if not r.passed]
    bad = run_checks(t, [Check("tool_called", "responder"), Check("json_has_keys", ["a"])])
    assert not any(r.passed for r in bad)


def test_demo_pipeline():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / "demo"
        main(["demo", str(ws)])
        assert (ws / "report.md").exists()
        assert (ws / "package" / "agent.md").exists()
        cases = json.loads((ws / "evals" / "cases.json").read_text())
        assert any(c["split"] == "validation" for c in cases)
        runs = sorted((ws / "runs").glob("*-fit.json"))
        assert len(runs) >= 2
        last = json.loads(runs[-1].read_text())
        assert last["pass_rate"] >= 0.95
        assert (Path(d) / "demo-agent.zip").exists()


if __name__ == "__main__":
    test_checks(); test_demo_pipeline(); print("OK")
