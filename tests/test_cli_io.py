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


if __name__ == "__main__":
    unittest.main()
