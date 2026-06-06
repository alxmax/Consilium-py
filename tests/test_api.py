"""Unit tests for the public deliberate() API.
# tested-by: CPYBUS-API-001
# tested-by: CPYEXT-LTL-001
"""
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


if __name__ == "__main__":
    unittest.main()
