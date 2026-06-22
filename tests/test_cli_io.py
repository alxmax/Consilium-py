"""CLI input/output contract: clarify-on-non-proposal + how-to-implement output.
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

NOT_A_PROPOSAL = Report(
    verdict="BLOCK",
    confidence=0.1,
    recommendation="Not a deliberation input — rephrase as a concrete proposal.",
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


class TestClarifyOnNonProposal(unittest.TestCase):
    def test_non_interactive_keeps_block_sentinel(self):
        """Non-TTY (CI/pipe): no prompt, BLOCK is preserved — deliberate called once."""
        with patch("consilium.cli.deliberate", return_value=NOT_A_PROPOSAL) as dlb:
            result = CliRunner().invoke(main, ["deliberate", "How is the weather"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(dlb.call_count, 1)
        self.assertIn("Not a deliberation input", result.output)

    def test_interactive_clarify_reruns_on_rephrase(self):
        """TTY: the dead-end BLOCK prompts once; the user's rephrase is re-deliberated."""
        outputs = iter([NOT_A_PROPOSAL, GO_WITH_SKETCH])
        with patch("consilium.cli.deliberate", side_effect=lambda *a, **k: next(outputs)) as dlb, \
                patch("consilium.cli._stdin_is_tty", return_value=True):
            result = CliRunner().invoke(
                main, ["deliberate", "How is the weather"], input="Add a /health endpoint\n"
            )
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(dlb.call_count, 2)
        # second call deliberated the rephrased proposal
        self.assertEqual(dlb.call_args_list[1].args[0], "Add a /health endpoint")
        self.assertIn("How to implement (approach_a)", result.output)

    def test_interactive_skip_keeps_block(self):
        """TTY but user presses Enter: no re-deliberation, original guidance stands."""
        with patch("consilium.cli.deliberate", return_value=NOT_A_PROPOSAL) as dlb, \
                patch("consilium.cli._stdin_is_tty", return_value=True):
            result = CliRunner().invoke(
                main, ["deliberate", "How is the weather"], input="\n"
            )
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(dlb.call_count, 1)


if __name__ == "__main__":
    unittest.main()
