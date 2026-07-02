"""CLI acceptance tests."""
# tested-by: CPYBUS-CLI-001
# tested-by: CPYSRV-SERVE-001
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import click
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
        data = json.loads(result.stdout)
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


class TestDirectoryContextSecurity(unittest.TestCase):
    """Unit tests for the -c/--context <directory> helpers in consilium.cli:
    secret exclusion (aurelius), binary exclusion (dimon), git-tracked-only
    discovery (musk), and the token-cap abort boundary (wittgenstein)."""

    def test_secret_files_never_appear_in_context(self):
        """aurelius: .env/id_rsa/etc. must never appear in assembled context,
        even though they sit right next to a normal file in the target dir."""
        from consilium.cli import _read_files
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "app.py"), "w") as f:
                f.write("print('hello world')")
            with open(os.path.join(d, ".env"), "w") as f:
                f.write("SECRET_KEY=supersecret123")
            with open(os.path.join(d, "id_rsa"), "w") as f:
                f.write("-----BEGIN PRIVATE KEY-----FAKE-----END PRIVATE KEY-----")
            with open(os.path.join(d, "service-account-prod.json"), "w") as f:
                f.write('{"type": "service_account", "private_key": "fake"}')
            result = _read_files([d])
        self.assertIn("print('hello world')", result)
        self.assertNotIn("supersecret123", result)
        self.assertNotIn(".env", result)
        self.assertNotIn("PRIVATE KEY", result)
        self.assertNotIn("id_rsa", result)
        self.assertNotIn("service_account", result)

    def test_binary_files_excluded_from_listing_and_context(self):
        """dimon: a file with a NUL byte in its first 8KB must be excluded
        from both the file listing and the assembled context text."""
        from consilium.cli import _list_dir_files, _read_directory
        with tempfile.TemporaryDirectory() as d:
            text_path = os.path.join(d, "notes.txt")
            with open(text_path, "w") as f:
                f.write("plain text content")
            bin_path = os.path.join(d, "blob.bin")
            with open(bin_path, "wb") as f:
                f.write(b"prefix\x00suffix" + b"\xff" * 20)

            files = _list_dir_files(d)
            self.assertIn(text_path, files)
            self.assertNotIn(bin_path, files)

            context = _read_directory(d)
        self.assertIn("plain text content", context)
        self.assertNotIn("blob.bin", context)

    def test_git_ls_files_only_tracked_and_not_ignored(self):
        """musk: discovery uses `git ls-files` under a git repo — a gitignored
        file must not appear, while a tracked (staged) file and an untracked
        but non-ignored file both do."""
        if not shutil.which("git"):
            self.skipTest("git is not available in this environment")
        from consilium.cli import _list_dir_files

        with tempfile.TemporaryDirectory() as d:
            init = subprocess.run(["git", "init"], cwd=d, capture_output=True, text=True)
            if init.returncode != 0:
                self.skipTest(f"git init failed: {init.stderr}")

            tracked = os.path.join(d, "tracked.py")
            with open(tracked, "w") as f:
                f.write("x = 1")
            untracked = os.path.join(d, "untracked.py")
            with open(untracked, "w") as f:
                f.write("y = 2")
            with open(os.path.join(d, ".gitignore"), "w") as f:
                f.write("ignored.txt\n")
            ignored = os.path.join(d, "ignored.txt")
            with open(ignored, "w") as f:
                f.write("should never appear")

            subprocess.run(
                ["git", "add", "tracked.py"], cwd=d, capture_output=True, text=True, check=True
            )

            files = _list_dir_files(d)

        self.assertIn(tracked, files)
        self.assertIn(untracked, files)
        self.assertNotIn(ignored, files)

    def test_token_cap_boundary_pass_and_abort(self):
        """wittgenstein: single-comparator token abort at the boundary —
        estimated_tokens = len(text) // 4; 50_000 tokens passes, 50_001 aborts."""
        from consilium.cli import _list_dir_files, _read_directory

        with tempfile.TemporaryDirectory() as d:
            file_path = os.path.join(d, "big.txt")
            with open(file_path, "w") as f:
                f.write("placeholder")
            files = _list_dir_files(d)
            self.assertEqual(files, [file_path])

            header = f"\n\n--- {file_path} ---\n"
            header_len = len(header)

            # Exactly 50_000 estimated tokens (200_000 chars) must pass.
            pass_len = 50_000 * 4 - header_len
            with open(file_path, "w") as f:
                f.write("a" * pass_len)
            text = _read_directory(d)
            self.assertEqual(len(text), 50_000 * 4)

            # Exactly 50_001 estimated tokens (200_004 chars) must abort.
            fail_len = 50_001 * 4 - header_len
            with open(file_path, "w") as f:
                f.write("a" * fail_len)
            with self.assertRaises(click.ClickException):
                _read_directory(d)

    def test_read_files_multiple_plain_files_unchanged(self):
        """Regression guard: passing several plain files (no directories) to
        _read_files still concatenates them as before the directory-context
        feature was added."""
        from consilium.cli import _read_files
        with tempfile.TemporaryDirectory() as d:
            f1 = os.path.join(d, "a.txt")
            with open(f1, "w") as f:
                f.write("AAA")
            f2 = os.path.join(d, "b.txt")
            with open(f2, "w") as f:
                f.write("BBB")
            result = _read_files([f1, f2])
        self.assertIn("AAA", result)
        self.assertIn("BBB", result)


if __name__ == "__main__":
    unittest.main()
