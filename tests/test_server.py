"""Smoke tests for the FastAPI HTTP server. Skipped if [server] extra not installed."""
# tested-by: CPYSRV-HTTP-001
import json
import unittest
from unittest.mock import patch

CONS_GO = json.dumps({
    "scores": [{"id": "a", "reversibility": "complete", "magnitude": "minor",
                "regression_risk": {"net_concern": 0.1, "magnitude": "minor"},
                "irreversibility_flag": False}]
})
GEN_GO = json.dumps({
    "preferred": "a",
    "options": [{"id": "a", "description": "Approach A"}, {"id": "b", "description": "Alt"}],
    "abstain": {"triggered": False},
})
CTRL_GO = json.dumps({"glossary_fail": False, "glossary": [], "disagreements": []})


def _voice_side_effect(*_a, **_kw):  # type: ignore[return]
    return next(_outputs)


try:
    from fastapi.testclient import TestClient
    from consilium.server import app
    _SERVER_AVAILABLE = True
except ImportError:
    _SERVER_AVAILABLE = False


@unittest.skipUnless(_SERVER_AVAILABLE, "consilium-py[server] not installed")
class TestServerEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_deliberate_returns_200_and_valid_report(self) -> None:
        global _outputs
        _outputs = iter([GEN_GO, CONS_GO, CTRL_GO])
        with patch("consilium.modes.sequential.call_voice", side_effect=_voice_side_effect):
            resp = self.client.post("/deliberate", json={"proposal": "Add health check"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("verdict", body)
        self.assertIn(body["verdict"], {"GO", "MODIFY", "STOP", "BLOCK", "ESCALATE", "ANSWER"})
        self.assertIn("confidence", body)
        self.assertIn("recommendation", body)
        self.assertIsInstance(body["voices"], list)

    def test_deliberate_with_context_and_mode(self) -> None:
        global _outputs
        _outputs = iter([GEN_GO, CONS_GO, CTRL_GO])
        with patch("consilium.modes.sequential.call_voice", side_effect=_voice_side_effect):
            resp = self.client.post(
                "/deliberate",
                json={"proposal": "Refactor auth", "context": "src/auth.py", "mode": "sequential"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("verdict", resp.json())

    def test_provider_error_returns_actionable_detail_not_raw_500(self) -> None:
        """A provider failure becomes a clean 502 + detail, not an unhandled 500."""
        class FakeLLMError(Exception):
            status_code = 401
        FakeLLMError.__module__ = "litellm.exceptions"
        with patch("consilium.server.deliberate", side_effect=FakeLLMError("auth rejected")):
            resp = self.client.post("/deliberate", json={"proposal": "Add health check"})
        self.assertEqual(resp.status_code, 502)
        detail = resp.json()["detail"]
        self.assertIn("not transient", detail.lower())
        self.assertNotIn("401", str(resp.status_code))  # the caller's own status must not be 401

    def test_non_provider_exception_is_not_masked(self) -> None:
        """A real bug still surfaces (not silently reclassified as a provider error)."""
        with patch("consilium.server.deliberate", side_effect=ValueError("real bug")):
            with self.assertRaises(ValueError):
                self.client.post("/deliberate", json={"proposal": "Add health check"})

    def test_rag_and_skeptic_override_fields_reach_deliberate(self) -> None:
        from consilium.models import Report
        stub = Report(verdict="GO", confidence=0.9, recommendation="ok", voices=[])
        with patch("consilium.server.deliberate", return_value=stub) as mock_deliberate:
            self.client.post(
                "/deliberate",
                json={"proposal": "Add health check", "mode": "dialectic",
                      "rag": True, "skeptic_can_override": True},
            )
        self.assertEqual(mock_deliberate.call_args.kwargs["rag"], True)
        self.assertEqual(mock_deliberate.call_args.kwargs["skeptic_can_override"], True)

    def test_rag_and_skeptic_override_default_false(self) -> None:
        from consilium.models import Report
        stub = Report(verdict="GO", confidence=0.9, recommendation="ok", voices=[])
        with patch("consilium.server.deliberate", return_value=stub) as mock_deliberate:
            self.client.post("/deliberate", json={"proposal": "Add health check"})
        self.assertEqual(mock_deliberate.call_args.kwargs["rag"], False)
        self.assertEqual(mock_deliberate.call_args.kwargs["skeptic_can_override"], False)
