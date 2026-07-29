"""Chat Q&A surface: retrieve-then-answer by default, deliberation on request."""
# tested-by: CPYBUS-CHAT-001
import unittest
from unittest.mock import patch

from consilium.models import Report

_BLOCK = "RELEVANT DOCS:\n  - [spec.md#0] 'the retry budget is 3'"
_BUNDLE = (_BLOCK, ["spec.md#0"])


def _go_report() -> Report:
    return Report(verdict="GO", confidence=0.9, recommendation="deliberated", voices=[])


class TestAskDefaultPath(unittest.TestCase):
    def test_does_not_run_the_voice_pipeline(self):
        """A question must not burn 3-10 voice calls only to discard them."""
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle", return_value=_BUNDLE), \
                patch("consilium.chat.plain_answer", return_value="It is 3."), \
                patch("consilium.chat.deliberate") as delib:
            report = chat.ask("what is the retry budget?")
        delib.assert_not_called()
        self.assertEqual(report.verdict, "ANSWER")
        self.assertEqual(report.recommendation, "It is 3.")

    def test_answer_is_grounded_in_retrieved_context(self):
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle", return_value=_BUNDLE), \
                patch("consilium.chat.plain_answer", return_value="It is 3.") as pa:
            chat.ask("what is the retry budget?")
        self.assertIn("retry budget is 3", pa.call_args.kwargs["context"])

    def test_reports_its_sources(self):
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle", return_value=_BUNDLE), \
                patch("consilium.chat.plain_answer", return_value="It is 3."):
            report = chat.ask("what is the retry budget?")
        self.assertEqual(report.sources, ["spec.md#0"])

    def test_rag_disabled_skips_retrieval_and_reports_no_sources(self):
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle") as bundle, \
                patch("consilium.chat.plain_answer", return_value="hi"):
            report = chat.ask("hello", rag=False)
        bundle.assert_not_called()
        self.assertEqual(report.sources, [])
        self.assertEqual(report.recommendation, "hi")

    def test_caller_context_reaches_the_prompt_without_rag(self):
        """A caller with no ingested corpus is not limited to an ungrounded reply —
        regression guard for the context-discard bug PR #53 fixed on the RAG path."""
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle") as bundle, \
                patch("consilium.chat.plain_answer", return_value="ok") as pa:
            chat.ask("what is the daily limit?", rag=False, context="daily_dd_usd: 500")
        bundle.assert_not_called()
        self.assertIn("daily_dd_usd: 500", pa.call_args.kwargs["context"])

    def test_caller_context_and_rag_context_are_both_present(self):
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle", return_value=_BUNDLE), \
                patch("consilium.chat.plain_answer", return_value="ok") as pa:
            chat.ask("what is the retry budget?", context="caller-supplied fact")
        sent = pa.call_args.kwargs["context"]
        self.assertIn("caller-supplied fact", sent)
        self.assertIn("retry budget is 3", sent)


class TestAskDeliberateOptIn(unittest.TestCase):
    def test_explicit_mode_runs_the_full_deliberation(self):
        from consilium import chat
        with patch("consilium.chat.deliberate", return_value=_go_report()) as delib, \
                patch("consilium.chat.plain_answer") as pa:
            report = chat.ask("Add Redis caching", mode="sequential")
        pa.assert_not_called()
        delib.assert_called_once()
        self.assertEqual(delib.call_args.kwargs["mode"], "sequential")
        self.assertEqual(report.verdict, "GO")

    def test_unknown_mode_is_rejected(self):
        from consilium import chat
        with self.assertRaises(ValueError):
            chat.ask("Add Redis caching", mode="nonsense")


if __name__ == "__main__":
    unittest.main()


class TestAskTenantScoping(unittest.TestCase):
    def test_tenant_reaches_retrieval(self):
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle", return_value=_BUNDLE) as bundle, \
                patch("consilium.chat.plain_answer", return_value="ok"):
            chat.ask("q", tenant="acme")
        self.assertEqual(bundle.call_args.kwargs["tenant"], "acme")

    def test_default_is_shared_corpus(self):
        from consilium import chat
        with patch("consilium.rag.build_rag_bundle", return_value=_BUNDLE) as bundle, \
                patch("consilium.chat.plain_answer", return_value="ok"):
            chat.ask("q")
        self.assertIsNone(bundle.call_args.kwargs["tenant"])

    def test_tenant_forwarded_to_deliberation_mode(self):
        from consilium import chat
        with patch("consilium.chat.deliberate", return_value=_go_report()) as d:
            chat.ask("q", mode="sequential", tenant="acme")
        self.assertEqual(d.call_args.kwargs["tenant"], "acme")
