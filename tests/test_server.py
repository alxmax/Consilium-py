"""Smoke tests for the FastAPI HTTP server. Skipped if [server] extra not installed."""
# tested-by: CPYSRV-HTTP-001
# tested-by: CPYSRV-AUTH-001
import json
import os
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


def _stub_report():
    from consilium.models import Report
    return Report(verdict="GO", confidence=0.9, recommendation="ok", voices=[])


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


@unittest.skipUnless(_SERVER_AVAILABLE, "consilium-py[server] not installed")
class TestApiKeyAuth(unittest.TestCase):
    """Off by default so `consilium serve` on localhost stays frictionless;
    enforced the moment an operator sets a key."""

    def setUp(self) -> None:
        from consilium import server
        server.reset_rate_limit()
        self.client = TestClient(app)
        self.stub = _stub_report()

    def test_no_key_configured_leaves_endpoint_open(self) -> None:
        cleaned = {k: v for k, v in os.environ.items() if k != "CONSILIUM_API_KEY"}
        with patch.dict(os.environ, cleaned, clear=True), \
                patch("consilium.server.deliberate", return_value=self.stub):
            resp = self.client.post("/deliberate", json={"proposal": "x"})
        self.assertEqual(resp.status_code, 200)

    def test_configured_key_rejects_request_without_header(self) -> None:
        with patch.dict(os.environ, {"CONSILIUM_API_KEY": "secret"}), \
                patch("consilium.server.deliberate", return_value=self.stub) as d:
            resp = self.client.post("/deliberate", json={"proposal": "x"})
        self.assertEqual(resp.status_code, 401)
        d.assert_not_called()

    def test_configured_key_rejects_wrong_header(self) -> None:
        with patch.dict(os.environ, {"CONSILIUM_API_KEY": "secret"}), \
                patch("consilium.server.deliberate", return_value=self.stub):
            resp = self.client.post(
                "/deliberate", json={"proposal": "x"}, headers={"X-API-Key": "wrong"}
            )
        self.assertEqual(resp.status_code, 401)

    def test_correct_key_is_accepted(self) -> None:
        with patch.dict(os.environ, {"CONSILIUM_API_KEY": "secret"}), \
                patch("consilium.server.deliberate", return_value=self.stub):
            resp = self.client.post(
                "/deliberate", json={"proposal": "x"}, headers={"X-API-Key": "secret"}
            )
        self.assertEqual(resp.status_code, 200)


@unittest.skipUnless(_SERVER_AVAILABLE, "consilium-py[server] not installed")
class TestRateLimit(unittest.TestCase):
    def setUp(self) -> None:
        from consilium import server
        server.reset_rate_limit()
        self.client = TestClient(app)
        self.stub = _stub_report()

    def test_requests_beyond_the_limit_get_429(self) -> None:
        """An unauthenticated deliberation costs 3-10 provider calls; an open
        endpoint with no cap hands the operator an unbounded bill."""
        with patch.dict(os.environ, {"CONSILIUM_RATE_LIMIT": "2"}), \
                patch("consilium.server.deliberate", return_value=self.stub):
            first = self.client.post("/deliberate", json={"proposal": "x"})
            second = self.client.post("/deliberate", json={"proposal": "x"})
            third = self.client.post("/deliberate", json={"proposal": "x"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 429)

    def test_limit_does_not_apply_to_the_ui_route(self) -> None:
        with patch.dict(os.environ, {"CONSILIUM_RATE_LIMIT": "1"}):
            self.client.get("/")
            resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)


@unittest.skipUnless(_SERVER_AVAILABLE, "consilium-py[server] not installed")
class TestAskRoute(unittest.TestCase):
    """The chat surface: same process, separate route, separate module."""

    def setUp(self) -> None:
        from consilium import server
        server.reset_rate_limit()
        self.client = TestClient(app)

    @staticmethod
    def _answer():
        from consilium.models import Report
        return Report(verdict="ANSWER", confidence=0.0, recommendation="It is 3.",
                      voices=[], mode="chat", sources=["spec.md#0"])

    def test_returns_the_answer_and_its_sources(self) -> None:
        with patch("consilium.server.ask", return_value=self._answer()):
            resp = self.client.post("/ask", json={"question": "what is the retry budget?"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["recommendation"], "It is 3.")
        self.assertEqual(body["sources"], ["spec.md#0"])

    def test_defaults_to_grounded_answer_without_deliberating(self) -> None:
        with patch("consilium.server.ask", return_value=self._answer()) as a:
            self.client.post("/ask", json={"question": "what is the retry budget?"})
        self.assertEqual(a.call_args.kwargs["rag"], True)
        self.assertIsNone(a.call_args.kwargs["mode"])

    def test_mode_opts_into_full_deliberation(self) -> None:
        with patch("consilium.server.ask", return_value=self._answer()) as a:
            self.client.post("/ask", json={"question": "Add Redis", "mode": "sequential"})
        self.assertEqual(a.call_args.kwargs["mode"], "sequential")

    def test_unknown_mode_returns_400_not_500(self) -> None:
        with patch("consilium.server.ask", side_effect=ValueError("Unknown mode: 'nope'")):
            resp = self.client.post("/ask", json={"question": "x", "mode": "nope"})
        self.assertEqual(resp.status_code, 400)

    def test_is_behind_the_same_api_key(self) -> None:
        with patch.dict(os.environ, {"CONSILIUM_API_KEY": "secret"}), \
                patch("consilium.server.ask", return_value=self._answer()) as a:
            resp = self.client.post("/ask", json={"question": "x"})
        self.assertEqual(resp.status_code, 401)
        a.assert_not_called()
