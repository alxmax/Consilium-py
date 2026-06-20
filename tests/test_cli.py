"""CLI acceptance tests."""
# tested-by: CPYBUS-CLI-001
import json
import unittest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from consilium.models import Report


def _go_report() -> Report:
    return Report(verdict="GO", confidence=0.85, recommendation="Looks good.", voices=[], mode="sequential")


def _modify_report() -> Report:
    return Report(verdict="MODIFY", confidence=0.6, recommendation="Review first.", voices=[], mode="sequential")


class TestDeliberateCmd(unittest.TestCase):
    def test_json_output_is_valid(self):
        from consilium.cli import main
        runner = CliRunner()
        with patch("consilium.cli.deliberate", return_value=_go_report()):
            result = runner.invoke(main, ["deliberate", "Add health check", "--output", "json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        self.assertEqual(data["verdict"], "GO")
        self.assertIn("confidence", data)

    def test_text_output_shows_verdict(self):
        from consilium.cli import main
        runner = CliRunner()
        with patch("consilium.cli.deliberate", return_value=_go_report()):
            result = runner.invoke(main, ["deliberate", "Add health check"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("GO", result.output)

    def test_context_file_content_injected(self):
        """--context <path> reads the file and concatenates into context."""
        from consilium.cli import main
        runner = CliRunner()
        captured = {}

        def capture(proposal, **kwargs):
            captured.update(kwargs)
            return _go_report()

        with runner.isolated_filesystem():
            with open("ctx.txt", "w") as f:
                f.write("extra context content")
            with patch("consilium.cli.deliberate", side_effect=capture):
                result = runner.invoke(main, ["deliberate", "test", "-c", "ctx.txt"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("extra context content", captured.get("context", ""))


class TestCheckCmd(unittest.TestCase):
    def test_empty_diff_errors(self):
        from consilium.cli import main
        runner = CliRunner()
        empty = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=empty):
            result = runner.invoke(main, ["check"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No diff found", result.output)

    def test_diff_calls_deliberate(self):
        from consilium.cli import main
        runner = CliRunner()
        has_diff = MagicMock(returncode=0, stdout="diff --git a/f.py b/f.py\n+line", stderr="")
        with patch("subprocess.run", return_value=has_diff), \
             patch("consilium.cli.deliberate", return_value=_modify_report()) as mock:
            result = runner.invoke(main, ["check", "--diff", "HEAD~1"])
        self.assertEqual(result.exit_code, 0, result.output)
        mock.assert_called_once()

    def test_git_error_propagates(self):
        from consilium.cli import main
        runner = CliRunner()
        fail = MagicMock(returncode=1, stdout="", stderr="not a git repository")
        with patch("subprocess.run", return_value=fail):
            result = runner.invoke(main, ["check"])
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
