"""Unit tests for the public deliberate() API."""
# tested-by: CPYBUS-API-001
# tested-by: CPYEXT-LTL-001
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from consilium.models import Report

try:
    import consilium.modes.langgraph_mode  # noqa: F401
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False


def _go_report(mode: str) -> Report:
    return Report(verdict="GO", confidence=0.9, recommendation="ok", voices=[], mode=mode)


class TestDeliberateModeRouting(unittest.TestCase):
    def test_sequential_mode(self):
        from consilium import deliberate
        # Patch the name as it lives in the consilium package namespace
        with patch("consilium.run_sequential", return_value=_go_report("sequential")) as mock:
            report = deliberate("Add health check", mode="sequential")
        mock.assert_called_once()
        self.assertEqual(report.mode, "sequential")

    def test_dialectic_mode(self):
        from consilium import deliberate
        with patch("consilium.run_dialectic", return_value=_go_report("dialectic")) as mock:
            report = deliberate("Add health check", mode="dialectic")
        mock.assert_called_once()
        self.assertEqual(report.mode, "dialectic")

    def test_trias_mode(self):
        from consilium import deliberate
        with patch("consilium.run_trias", return_value=_go_report("trias")) as mock:
            report = deliberate("Add health check", mode="trias")
        mock.assert_called_once()
        self.assertEqual(report.mode, "trias")

    def test_trias_forwards_skeptic_override(self):
        """Regression (audit 2026-07-01): --skeptic-can-override was silently
        ignored in trias mode — deliberate() never forwarded the flag."""
        from consilium import deliberate
        with patch("consilium.run_trias", return_value=_go_report("trias")) as mock:
            deliberate("Add health check", mode="trias", skeptic_can_override=True)
        self.assertTrue(mock.call_args.kwargs.get("skeptic_can_override"))

    @unittest.skipUnless(_LANGGRAPH_AVAILABLE, "langgraph not installed")
    def test_langgraph_mode(self):
        from consilium import deliberate
        import consilium.modes.langgraph_mode as lg
        with patch.object(lg, "run_langgraph", return_value=_go_report("langgraph")) as mock:
            report = deliberate("Add health check", mode="langgraph")
        mock.assert_called_once()
        self.assertEqual(report.mode, "langgraph")

    def test_unknown_mode_raises_value_error(self):
        from consilium import deliberate
        with self.assertRaises(ValueError) as ctx:
            deliberate("test", mode="unknown")
        self.assertIn("unknown", str(ctx.exception))

    def test_context_passed_as_raw_text(self):
        """context= is raw text; file loading is the caller's responsibility."""
        from consilium import deliberate
        captured = []

        def capture_inp(inp):
            captured.append(inp.context)
            return _go_report("sequential")

        with patch("consilium.run_sequential", side_effect=capture_inp):
            deliberate("test", context="raw text here")

        self.assertEqual(captured[0], "raw text here")


class TestConsuliumModelEnvVar(unittest.TestCase):
    def test_env_var_overrides_model_param(self):
        """CONSILIUM_MODEL env var overrides the model= parameter."""
        from consilium import deliberate
        captured = []

        def capture_inp(inp):
            captured.append(inp.model)
            return _go_report("sequential")

        with patch("consilium.run_sequential", side_effect=capture_inp), \
             patch.dict(os.environ, {"CONSILIUM_MODEL": "claude-haiku-4-5"}):
            deliberate("test", model="claude-sonnet-4-6")

        self.assertEqual(captured[0], "claude-haiku-4-5")

    def test_no_env_var_uses_param(self):
        from consilium import deliberate
        captured = []

        def capture_inp(inp):
            captured.append(inp.model)
            return _go_report("sequential")

        env_without_key = {k: v for k, v in os.environ.items() if k != "CONSILIUM_MODEL"}
        with patch("consilium.run_sequential", side_effect=capture_inp), \
             patch.dict(os.environ, env_without_key, clear=True):
            deliberate("test", model="claude-sonnet-4-6")

        self.assertEqual(captured[0], "claude-sonnet-4-6")


class TestNonDeliberationAnswer(unittest.TestCase):
    def test_not_a_proposal_becomes_plain_answer(self):
        """A not_a_proposal report is replaced by a plain ANSWER, not returned as BLOCK."""
        from consilium import deliberate
        block = Report(
            verdict="BLOCK", confidence=0.1, recommendation="blocked",
            voices=[], reason="not_a_proposal", mode="sequential",
        )
        with patch("consilium.run_sequential", return_value=block), \
                patch("consilium.plain_answer", return_value="Hello! How can I help?") as pa:
            report = deliberate("hi", mode="sequential")
        self.assertEqual(report.verdict, "ANSWER")
        self.assertEqual(report.recommendation, "Hello! How can I help?")
        self.assertEqual(report.voices, [])
        pa.assert_called_once()

    def test_trias_not_a_proposal_becomes_answer(self):
        """Bug #5 (audit 2026-07-01): trias now propagates the personality
        BLOCK reason, so chit-chat converts to ANSWER like in sequential."""
        from consilium import deliberate
        block = Report(
            verdict="BLOCK", confidence=0.1, recommendation="blocked",
            voices=[], reason="not_a_proposal", mode="trias",
        )
        with patch("consilium.run_trias", return_value=block), \
                patch("consilium.plain_answer", return_value="Hello!"):
            report = deliberate("hi", mode="trias")
        self.assertEqual(report.verdict, "ANSWER")

    def test_normal_verdict_not_converted(self):
        """A normal verdict is returned unchanged; plain_answer is not called."""
        from consilium import deliberate
        with patch("consilium.run_sequential", return_value=_go_report("sequential")), \
                patch("consilium.plain_answer") as pa, \
                patch("consilium.short_response") as sr:
            report = deliberate("Add health check", mode="sequential")
        self.assertEqual(report.verdict, "GO")
        pa.assert_not_called()
        sr.assert_not_called()

    def test_scale_down_gets_real_short_response(self):
        """A scale_down report's leaked instruction is replaced by a real short reply."""
        from consilium import deliberate
        rep = Report(
            verdict="GO", confidence=0.5,
            recommendation="Compressed deliberation — short response (max 2 sentences)",
            voices=[], reason="scale_down", mode="sequential",
        )
        with patch("consilium.run_sequential", return_value=rep), \
                patch("consilium.short_response", return_value="No one can reliably predict it.") as sr:
            report = deliberate("who will win the World Cup", mode="sequential")
        self.assertEqual(report.recommendation, "No one can reliably predict it.")
        self.assertEqual(report.verdict, "GO")
        sr.assert_called_once()


class TestBypassAnswersAreGrounded(unittest.TestCase):
    """The ANSWER / scale_down routes bypass the pipeline; they must still see
    the retrieved RAG block, or a 'grounded' chat answer is silently ungrounded."""

    _RAG_BLOCK = "RELEVANT DOCS:\n  - [spec.md#0] 'the retry budget is 3'"

    def test_not_a_proposal_answer_receives_rag_context(self):
        from consilium import deliberate
        block = Report(
            verdict="BLOCK", confidence=0.1, recommendation="blocked",
            voices=[], reason="not_a_proposal", mode="sequential",
        )
        with patch("consilium.run_sequential", return_value=block), \
                patch("consilium.rag.build_rag_bundle",
                      return_value=(self._RAG_BLOCK, ["spec.md#0"])), \
                patch("consilium.plain_answer", return_value="3") as pa:
            deliberate("what is the retry budget?", mode="sequential", rag=True)
        self.assertIn("retry budget is 3", pa.call_args.kwargs["context"])

    def test_scale_down_response_receives_rag_context(self):
        from consilium import deliberate
        rep = Report(
            verdict="GO", confidence=0.5, recommendation="leaked instruction",
            voices=[], reason="scale_down", mode="sequential",
        )
        with patch("consilium.run_sequential", return_value=rep), \
                patch("consilium.rag.build_rag_bundle",
                      return_value=(self._RAG_BLOCK, ["spec.md#0"])), \
                patch("consilium.rag.save_run"), patch("consilium.rag.index"), \
                patch("consilium.short_response", return_value="It is 3.") as sr:
            deliberate("raise the retry budget", mode="sequential", rag=True)
        self.assertIn("retry budget is 3", sr.call_args.kwargs["context"])

    def test_answer_reports_the_sources_it_was_grounded_in(self):
        """The caller must be able to verify grounding, not just trust it."""
        from consilium import deliberate
        block = Report(
            verdict="BLOCK", confidence=0.1, recommendation="blocked",
            voices=[], reason="not_a_proposal", mode="sequential",
        )
        with patch("consilium.run_sequential", return_value=block), \
                patch("consilium.rag.build_rag_bundle",
                      return_value=(self._RAG_BLOCK, ["spec.md#0"])), \
                patch("consilium.plain_answer", return_value="3"):
            report = deliberate("what is the retry budget?", mode="sequential", rag=True)
        self.assertEqual(report.sources, ["spec.md#0"])

    def test_deliberated_verdict_reports_sources_too(self):
        """Not just the bypass route — a real deliberation cites its docs as well."""
        from consilium import deliberate
        with patch("consilium.run_sequential", return_value=_go_report("sequential")), \
                patch("consilium.rag.build_rag_bundle",
                      return_value=(self._RAG_BLOCK, ["spec.md#0"])), \
                patch("consilium.rag.save_run"), patch("consilium.rag.index"):
            report = deliberate("Add health check", mode="sequential", rag=True)
        self.assertEqual(report.sources, ["spec.md#0"])

    def test_sources_empty_when_rag_disabled(self):
        from consilium import deliberate
        with patch("consilium.run_sequential", return_value=_go_report("sequential")):
            report = deliberate("Add health check", mode="sequential")
        self.assertEqual(report.sources, [])

    def test_answer_without_rag_passes_empty_context(self):
        """rag=False must not fabricate a context block."""
        from consilium import deliberate
        block = Report(
            verdict="BLOCK", confidence=0.1, recommendation="blocked",
            voices=[], reason="not_a_proposal", mode="sequential",
        )
        with patch("consilium.run_sequential", return_value=block), \
                patch("consilium.plain_answer", return_value="hi") as pa:
            deliberate("hello", mode="sequential")
        self.assertEqual(pa.call_args.kwargs["context"], "")


if __name__ == "__main__":
    unittest.main()


class TestDeliberateTenantScoping(unittest.TestCase):
    def test_tenant_scopes_retrieval_and_indexing(self):
        from consilium import deliberate
        with patch("consilium.run_sequential", return_value=_go_report("sequential")), \
                patch("consilium.rag.build_rag_bundle", return_value=("blk", ["s#0"])) as bundle, \
                patch("consilium.rag.save_run"), patch("consilium.rag.index") as idx:
            deliberate("p", mode="sequential", rag=True, tenant="acme")
        self.assertEqual(bundle.call_args.kwargs["tenant"], "acme")
        self.assertEqual(idx.call_args.kwargs["tenant"], "acme")

    def test_default_tenant_is_none(self):
        from consilium import deliberate
        with patch("consilium.run_sequential", return_value=_go_report("sequential")), \
                patch("consilium.rag.build_rag_bundle", return_value=("blk", [])) as bundle, \
                patch("consilium.rag.save_run"), patch("consilium.rag.index"):
            deliberate("p", mode="sequential", rag=True)
        self.assertIsNone(bundle.call_args.kwargs["tenant"])
