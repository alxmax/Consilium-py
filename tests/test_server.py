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
