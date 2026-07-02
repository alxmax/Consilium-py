"""CLI acceptance tests."""
# tested-by: CPYBUS-CLI-001
# tested-by: CPYSRV-SERVE-001
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

    def test_no_rag_overrides_env_default(self):
        """CONSILIUM_RAG=1 makes --rag default on; --no-rag must force it off."""
        from consilium.cli import main
        runner = CliRunner()
        captured = {}

        def capture(proposal, **kwargs):
            captured.update(kwargs)
            return _go_report()

        with patch("consilium.cli.deliberate", side_effect=capture):
            result = runner.invoke(
                main, ["deliberate", "test", "--no-rag"], env={"CONSILIUM_RAG": "1"}
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(captured.get("rag"), "--no-rag must win over CONSILIUM_RAG=1")

    def test_rag_env_default_on(self):
        """CONSILIUM_RAG=1 turns rag on without an explicit flag."""
        from consilium.cli import main
        runner = CliRunner()
        captured = {}

        def capture(proposal, **kwargs):
            captured.update(kwargs)
            return _go_report()

        with patch("consilium.cli.deliberate", side_effect=capture):
            result = runner.invoke(
                main, ["deliberate", "test"], env={"CONSILIUM_RAG": "1"}
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(captured.get("rag"), "CONSILIUM_RAG=1 should enable rag")

    def test_context_file_utf8_non_ascii(self):
        """--context reads UTF-8 files; non-ASCII content must not be mangled
        by the platform's default encoding (Windows: cp1252)."""
        from consilium.cli import main
        runner = CliRunner()
        captured = {}

        def capture(proposal, **kwargs):
            captured.update(kwargs)
            return _go_report()

        with runner.isolated_filesystem():
            with open("ctx.txt", "w", encoding="utf-8") as f:
                f.write("café résumé — naïve façade")
            with patch("consilium.cli.deliberate", side_effect=capture):
                result = runner.invoke(main, ["deliberate", "test", "-c", "ctx.txt"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("café résumé — naïve façade", captured.get("context", ""))


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


class TestServeCmd(unittest.TestCase):
    """consilium serve — no real server is started and no real browser is opened:
    uvicorn.run, socket.socket (port-free probe), threading.Thread, and webbrowser.open
    are all mocked."""

    def _free_socket(self):
        sock = MagicMock()
        sock.connect_ex.return_value = 1  # non-zero == port free
        return sock

    def test_starts_uvicorn_with_resolved_model_and_free_port(self):
        from consilium.cli import main
        import os
        runner = CliRunner()
        with patch("uvicorn.run") as mock_run,              patch("socket.socket") as mock_socket_cls,              patch("threading.Thread") as mock_thread,              patch("webbrowser.open") as mock_open,              patch.dict("os.environ", {}, clear=False):
            mock_socket_cls.return_value.__enter__.return_value = self._free_socket()
            result = runner.invoke(main, ["serve", "--model", "openai/gpt-4o", "--port", "9999"])
            # env mutation is a side effect of the command — must be checked before
            # patch.dict reverts os.environ on context exit.
            self.assertEqual(os.environ.get("CONSILIUM_MODEL"), "openai/gpt-4o")
        self.assertEqual(result.exit_code, 0, result.output)
        mock_run.assert_called_once_with(
            "consilium.server:app", host="127.0.0.1", port=9999, log_level="warning"
        )
        mock_thread.assert_called_once()
        mock_open.assert_not_called()  # thread is mocked — it never actually runs

    def test_retries_next_port_when_busy(self):
        from consilium.cli import main
        runner = CliRunner()
        connect_results = iter([0, 1])  # first port busy, second free
        with patch("uvicorn.run") as mock_run,              patch("socket.socket") as mock_socket_cls,              patch("threading.Thread"),              patch("webbrowser.open"),              patch.dict("os.environ", {}, clear=False):
            sock = MagicMock()
            sock.connect_ex.side_effect = lambda *a, **kw: next(connect_results)
            mock_socket_cls.return_value.__enter__.return_value = sock
            result = runner.invoke(main, ["serve", "--port", "8124", "--no-browser"])
        self.assertEqual(result.exit_code, 0, result.output)
        mock_run.assert_called_once_with(
            "consilium.server:app", host="127.0.0.1", port=8125, log_level="warning"
        )
        self.assertIn("busy", result.output.lower())

    def test_no_browser_flag_skips_browser_thread(self):
        from consilium.cli import main
        runner = CliRunner()
        with patch("uvicorn.run"),              patch("socket.socket") as mock_socket_cls,              patch("threading.Thread") as mock_thread,              patch("webbrowser.open") as mock_open,              patch.dict("os.environ", {}, clear=False):
            mock_socket_cls.return_value.__enter__.return_value = self._free_socket()
            result = runner.invoke(main, ["serve", "--no-browser"])
        self.assertEqual(result.exit_code, 0, result.output)
        mock_thread.assert_not_called()
        mock_open.assert_not_called()

    def test_missing_server_extra_raises_clean_error(self):
        from consilium.cli import main
        runner = CliRunner()
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("no module named uvicorn")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = runner.invoke(main, ["serve"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("[server]", result.output)


if __name__ == "__main__":
    unittest.main()
