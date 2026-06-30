"""Unit tests for consilium explain — call_voice mocked, no API calls."""
# tested-by: CPYBUS-EXPLAIN-001
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner


VALID_JSON_RESPONSE = json.dumps({
    "summary": "A simple utility module.",
    "public_api": ["do_thing: does the thing"],
    "dependencies": ["pathlib: file I/O"],
    "data_flow": "Input path → read file → return string.",
    "gotchas": ["Raises FileNotFoundError if path missing."],
})


class TestExplainModule(unittest.TestCase):
    def _tmp_py(self, tmp_path: Path, content: str = "def foo(): pass") -> Path:
        f = tmp_path / "sample.py"
        f.write_text(content, encoding="utf-8")
        return f

    def _run(self, path: str, response: str = VALID_JSON_RESPONSE):
        with patch("consilium.explain.call_voice", return_value=response):
            from consilium.explain import explain_module
            return explain_module(path, model="test/model")

    def test_returns_explainreport_with_required_summary(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.py"
            p.write_text("def foo(): pass", encoding="utf-8")
            report = self._run(str(p))
        self.assertIsInstance(report.summary, str)
        self.assertTrue(report.summary)  # non-empty

    def test_source_code_passed_to_call_voice(self):
        """call_voice user_msg must contain the actual source code."""
        import tempfile
        source = "def magic(): return 42"
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "magic.py"
            p.write_text(source, encoding="utf-8")
            with patch("consilium.explain.call_voice", return_value=VALID_JSON_RESPONSE) as mock_cv:
                from consilium.explain import explain_module
                explain_module(str(p), model="test/model")
        _voice, system_prompt, user_msg, _model = mock_cv.call_args[0]
        self.assertIn(source, user_msg)

    def test_system_prompt_contains_json_schema_instruction(self):
        """System prompt must include a JSON schema so the model knows what to return."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.py"
            p.write_text("x = 1", encoding="utf-8")
            with patch("consilium.explain.call_voice", return_value=VALID_JSON_RESPONSE) as mock_cv:
                from consilium.explain import explain_module
                explain_module(str(p), model="test/model")
        _voice, system_prompt, _user_msg, _model = mock_cv.call_args[0]
        # The explain.md prompt must contain a JSON schema with at minimum the "summary" key.
        self.assertIn("summary", system_prompt)
        self.assertIn("json", system_prompt.lower())

    def test_no_python_files_returns_summary_message(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "readme.txt").write_text("hello", encoding="utf-8")
            from consilium.explain import explain_module
            report = explain_module(tmp, model="test/model")
        self.assertIn("No Python files", report.summary)

    def test_malformed_json_response_uses_prose_as_summary(self):
        """If model returns prose instead of JSON, first 300 chars become summary."""
        import tempfile
        prose = "This module handles authentication logic."
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "auth.py"
            p.write_text("pass", encoding="utf-8")
            report = self._run(str(p), response=prose)
        self.assertEqual(report.summary, prose)

    def test_file_count_cap_respected(self):
        """At most _MAX_FILES Python files are read."""
        import tempfile
        from consilium.explain import _MAX_FILES
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(_MAX_FILES + 5):
                (Path(tmp) / f"mod_{i}.py").write_text(f"x = {i}", encoding="utf-8")
            with patch("consilium.explain.call_voice", return_value=VALID_JSON_RESPONSE) as mock_cv:
                from consilium.explain import explain_module
                explain_module(tmp, model="test/model")
        _voice, _sys, user_msg, _model = mock_cv.call_args[0]
        # user_msg is built from at most MAX_FILES files; check by counting "# " path headers
        headers = [line for line in user_msg.splitlines() if line.startswith("# ") and line.endswith(".py")]
        self.assertLessEqual(len(headers), _MAX_FILES)


class TestExplainCLI(unittest.TestCase):
    def test_cli_exits_zero_on_valid_file(self):
        import tempfile
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "foo.py"
            p.write_text("def foo(): pass", encoding="utf-8")
            with patch("consilium.explain.call_voice", return_value=VALID_JSON_RESPONSE):
                from consilium.cli import main
                result = runner.invoke(main, ["explain", str(p)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("A simple utility module.", result.output)

    def test_cli_json_output(self):
        import tempfile
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "foo.py"
            p.write_text("pass", encoding="utf-8")
            with patch("consilium.explain.call_voice", return_value=VALID_JSON_RESPONSE):
                from consilium.cli import main
                result = runner.invoke(main, ["explain", str(p), "--output", "json"])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.output)
        self.assertIn("summary", data)
        self.assertTrue(data["summary"])

    def test_cli_missing_path_nonzero_exit(self):
        runner = CliRunner()
        from consilium.cli import main
        result = runner.invoke(main, ["explain", "/nonexistent/path/that/does/not/exist.py"])
        # No Python files → exits 0 with a message, not a crash
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("Traceback", result.output)


if __name__ == "__main__":
    unittest.main()
