"""Unit tests for LangGraph orchestration mode."""
# tested-by: CPYEXT-LG-001
import json
import sys
import unittest
from unittest.mock import patch

CONS = json.dumps({
    "scores": [{"id": "a", "reversibility": "complete", "magnitude": "minor",
                "regression_risk": {"net_concern": 0.2}, "irreversibility_flag": False}]
})
GEN = json.dumps({
    "preferred": "a",
    "options": [{"id": "a", "description": "Primary"}],
    "abstain": {"triggered": False},
})
CTRL = json.dumps({"glossary_fail": False, "glossary": [], "disagreements": []})

try:
    import consilium.modes.langgraph_mode  # noqa: F401
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False


def _voice_iter(*outputs):
    it = iter(outputs)
    return lambda *a, **kw: next(it)


@unittest.skipUnless(_LANGGRAPH_AVAILABLE, "langgraph not installed")
class TestRunLangGraph(unittest.TestCase):
    def setUp(self):
        import consilium.modes.langgraph_mode as lg
        lg._graph = None  # reset cached graph before each test

    def _run(self, proposal="Add health check"):
        from consilium.models import DeliberationInput
        from consilium.modes.langgraph_mode import run_langgraph
        with patch("consilium.modes.langgraph_mode.call_voice", side_effect=_voice_iter(GEN, CONS, CTRL)), \
             patch("consilium.modes.langgraph_mode.load_prompt", return_value=""):
            return run_langgraph(DeliberationInput(proposal=proposal))

    def test_mode_is_langgraph(self):
        self.assertEqual(self._run().mode, "langgraph")

    def test_pipeline_executed(self):
        self.assertTrue(self._run().pipeline_executed)

    def test_same_verdict_as_sequential(self):
        from consilium.models import DeliberationInput
        from consilium.modes.sequential import run_sequential
        from consilium.modes.langgraph_mode import run_langgraph
        import consilium.modes.langgraph_mode as lg

        with patch("consilium.modes.sequential.call_voice", side_effect=_voice_iter(GEN, CONS, CTRL)), \
             patch("consilium.modes.sequential.load_prompt", return_value=""):
            seq = run_sequential(DeliberationInput(proposal="Add health check"))

        lg._graph = None
        with patch("consilium.modes.langgraph_mode.call_voice", side_effect=_voice_iter(GEN, CONS, CTRL)), \
             patch("consilium.modes.langgraph_mode.load_prompt", return_value=""):
            lg_rep = run_langgraph(DeliberationInput(proposal="Add health check"))

        self.assertEqual(seq.verdict, lg_rep.verdict)

    def test_deliberate_dispatches_to_langgraph(self):
        from consilium import deliberate
        import consilium.modes.langgraph_mode as lg
        lg._graph = None
        with patch("consilium.modes.langgraph_mode.call_voice", side_effect=_voice_iter(GEN, CONS, CTRL)), \
             patch("consilium.modes.langgraph_mode.load_prompt", return_value=""):
            report = deliberate("Add health check", mode="langgraph")
        self.assertEqual(report.mode, "langgraph")


class TestLangGraphMissingImport(unittest.TestCase):
    def test_missing_langgraph_raises_import_error(self):
        saved = sys.modules.pop("consilium.modes.langgraph_mode", None)
        try:
            with patch.dict(sys.modules, {"langgraph": None, "langgraph.graph": None}):
                with self.assertRaises(ImportError) as ctx:
                    import consilium.modes.langgraph_mode  # noqa: F401
            self.assertIn("consilium-py[langgraph]", str(ctx.exception))
        finally:
            sys.modules.pop("consilium.modes.langgraph_mode", None)
            if saved is not None:
                sys.modules["consilium.modes.langgraph_mode"] = saved


if __name__ == "__main__":
    unittest.main()
