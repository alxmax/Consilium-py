"""CLI input/output contract: plain-answer for non-deliberation input + how-to-implement output.
Voices/deliberation are mocked — no API calls.
"""
# tested-by: CPYBUS-CLI-001
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from consilium.cli import main
from consilium.models import Report

GO_WITH_SKETCH = Report(
    verdict="GO",
    confidence=0.9,
    recommendation="Proceed with approach_a.",
    voices=[],
    chosen="approach_a",
    chosen_summary="Add a /health endpoint",
    chosen_sketch="Add a GET /health route returning 200 + version JSON.",
    chosen_rationale="Smallest change that satisfies the readiness goal.",
)

STOP_REPORT = Report(
    verdict="STOP",
    confidence=0.1,
    recommendation="Too risky.",
    voices=[],
    chosen="approach_a",
    chosen_sketch="Should never be printed for STOP.",
)

ANSWER_REPORT = Report(
    verdict="ANSWER",
    confidence=0.0,
    recommendation="Hello! How can I help?",
    voices=[],
    reason="not_a_proposal",
)


class TestHowToImplementOutput(unittest.TestCase):
    def test_sketch_printed_for_go(self):
        with patch("consilium.cli.deliberate", return_value=GO_WITH_SKETCH):
            result = CliRunner().invoke(main, ["deliberate", "Add health check"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("How to implement (approach_a)", result.output)
        self.assertIn("GET /health", result.output)
        self.assertIn("Why:", result.output)

    def test_sketch_suppressed_for_stop(self):
        with patch("consilium.cli.deliberate", return_value=STOP_REPORT):
            result = CliRunner().invoke(main, ["deliberate", "Drop prod DB"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("How to implement", result.output)
        self.assertNotIn("never be printed", result.output)


class TestAnswerOutput(unittest.TestCase):
    def test_answer_printed_plainly(self):
        """A non-deliberation input is answered directly: only the reply, no verdict header."""
        with patch("consilium.cli.deliberate", return_value=ANSWER_REPORT):
            result = CliRunner().invoke(main, ["deliberate", "hi"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Hello! How can I help?", result.output)
        self.assertNotIn("Verdict:", result.output)
        self.assertNotIn("Confidence:", result.output)


class TestProviderError(unittest.TestCase):
    def test_provider_503_shows_clean_message(self):
        """A transient provider error becomes a clean CLI message, not a traceback."""
        class FakeLLMError(Exception):
            pass
        FakeLLMError.__module__ = "litellm.exceptions"
        with patch("consilium.cli.deliberate", side_effect=FakeLLMError("503 high demand")):
            result = CliRunner().invoke(main, ["deliberate", "hi"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("provider unavailable", result.output.lower())
        self.assertNotIn("Traceback", result.output)

    def test_real_bug_is_not_masked(self):
        """A non-provider exception propagates; it is not swallowed as a provider message."""
        with patch("consilium.cli.deliberate", side_effect=ValueError("real bug")):
            result = CliRunner().invoke(main, ["deliberate", "hi"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertNotIn("provider unavailable", result.output.lower())

    def test_provider_404_marked_permanent(self):
        """A 404 (retired/unknown model) is reported as permanent, not 'transient — re-run shortly'."""
        class FakeLLMError(Exception):
            status_code = 404
        FakeLLMError.__module__ = "litellm.exceptions"
        with patch("consilium.cli.deliberate", side_effect=FakeLLMError("model not found")):
            result = CliRunner().invoke(
                main, ["deliberate", "hi", "--model", "gemini/gemini-2.0-flash"]
            )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("404", result.output)
        self.assertIn("not transient", result.output.lower())
        self.assertNotIn("re-run shortly", result.output.lower())
        self.assertNotIn("Traceback", result.output)


if __name__ == "__main__":
    unittest.main()
