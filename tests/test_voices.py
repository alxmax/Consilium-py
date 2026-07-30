"""Unit tests for voice dispatch utilities — no API calls."""
# tested-by: CPYBUS-VOI-001
# tested-by: CPYEXT-LTL-001
import sys
import unittest
from unittest.mock import MagicMock, patch


class TestExtractJson(unittest.TestCase):
    def setUp(self):
        from consilium.voices import extract_json
        self.fn = extract_json

    def test_fenced_json_block(self):
        self.assertEqual(self.fn('```json\n{"k": 1}\n```'), {"k": 1})

    def test_fenced_no_language(self):
        self.assertEqual(self.fn('```\n{"k": 2}\n```'), {"k": 2})

    def test_raw_json_in_text(self):
        self.assertEqual(self.fn('text before {"k": 3} after'), {"k": 3})

    def test_no_json_returns_empty_dict(self):
        self.assertEqual(self.fn("no json here at all"), {})

    def test_nested_json(self):
        self.assertEqual(self.fn('{"outer": {"inner": 42}}'), {"outer": {"inner": 42}})

    def test_brace_in_string_value_parses_correctly(self):
        """A stray '}' inside a string value must not truncate the parse (regression)."""
        text = '{"options": [{"id": "opt1", "sketch": "end of fn }", "rationale": "ok"}], "preferred": "opt1"}'
        result = self.fn(text)
        self.assertEqual(result["preferred"], "opt1")
        self.assertEqual(result["options"][0]["sketch"], "end of fn }")

    def test_multiple_braces_in_string_value(self):
        """Pseudocode with balanced braces in a string must still parse the enclosing object."""
        text = '{"sketch": "if (x) { return y; } else { return z; }", "id": "opt1"}'
        self.assertEqual(
            self.fn(text),
            {"sketch": "if (x) { return y; } else { return z; }", "id": "opt1"},
        )

    def test_fence_path_unaffected_by_brace_in_string(self):
        text = '```json\n{"sketch": "a { b }"}\n```'
        self.assertEqual(self.fn(text), {"sketch": "a { b }"})

    def test_literal_newline_in_string_value(self):
        """`claude -p` voices emit literal newlines inside string values (e.g. a
        multi-line Control `notes`/`assert`). strict JSON rejects those, collapsing
        the voice to {}; extract_json must tolerate them (strict=False)."""
        text = '{"verdicts": [{"id": "x", "notes": "line one\nline two"}]}'
        self.assertEqual(self.fn(text), {"verdicts": [{"id": "x", "notes": "line one\nline two"}]})

    def test_literal_newline_in_fenced_string(self):
        text = '```json\n{"notes": "a\nb"}\n```'
        self.assertEqual(self.fn(text), {"notes": "a\nb"})


class TestClaudeCliDispatch(unittest.TestCase):
    """The claude-cli backend must honor the user's model choice: bare
    'claude-cli' runs sonnet, 'claude-cli:<name>' forwards <name> to the
    subprocess (regression: the model was silently hard-coded to sonnet)."""

    def _dispatch(self, model: str) -> list[str]:
        from consilium.voices import call_voice

        proc = MagicMock(returncode=0, stdout="ok")
        with patch("subprocess.run", return_value=proc) as run, \
                patch("shutil.which", return_value="claude"):
            call_voice("generator", "system", "user", model)
        return run.call_args[0][0]

    def test_default_model_is_sonnet(self):
        argv = self._dispatch("claude-cli")
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")

    def test_submodel_is_forwarded(self):
        argv = self._dispatch("claude-cli:opus")
        self.assertEqual(argv[argv.index("--model") + 1], "opus")

    def test_json_voice_retries_on_prose_drift(self):
        """`claude -p` intermittently answers a JSON voice in prose. A JSON voice
        (generator) must retry until it gets a parseable object, then return it."""
        from consilium.voices import call_voice

        outs = [
            MagicMock(returncode=0, stdout="**Verdict: STOP** — prose, no JSON here"),
            MagicMock(returncode=0, stdout='```json\n{"candidates": []}\n```'),
        ]
        with patch("subprocess.run", side_effect=outs) as run, \
                patch("shutil.which", return_value="claude"):
            result = call_voice("generator", "system", "user", "claude-cli")
        self.assertEqual(run.call_count, 2)              # retried once past the prose
        self.assertIn('"candidates"', result)            # returned the parseable attempt

    def test_prose_voice_is_never_retried(self):
        """assistant/explain return prose by contract — they must NOT be JSON-retried
        (that would loop on every valid plain answer)."""
        from consilium.voices import call_voice

        proc = MagicMock(returncode=0, stdout="Just a plain conversational reply.")
        with patch("subprocess.run", return_value=proc) as run, \
                patch("shutil.which", return_value="claude"):
            result = call_voice("assistant", "system", "user", "claude-cli")
        self.assertEqual(run.call_count, 1)              # no retry despite no JSON
        self.assertEqual(result, "Just a plain conversational reply.")

    def test_json_voice_gives_up_after_max_retries(self):
        """If every attempt drifts to prose, return the last output (aggregator flags
        it) rather than looping forever."""
        from consilium.voices import call_voice

        proc = MagicMock(returncode=0, stdout="never JSON")
        with patch("subprocess.run", return_value=proc) as run, \
                patch("shutil.which", return_value="claude"):
            result = call_voice("control", "system", "user", "claude-cli")
        self.assertEqual(run.call_count, 3)              # 1 + _CLI_JSON_RETRIES(2)
        self.assertEqual(result, "never JSON")


class TestLoadPrompt(unittest.TestCase):
    """Regression (audit 2026-07-01): prompts lived at the repo root, outside
    the wheel — every non-editable install crashed on the first load_prompt().
    They must resolve inside the consilium package via importlib.resources."""

    _ALL_PROMPTS = [
        "conservator", "control", "generator", "skeptic", "explain",
        "pioneer_lens", "architect_lens", "steward_lens",
    ]

    def test_prompts_dir_inside_package(self):
        from consilium.voices import PROMPTS_DIR
        normalized = str(PROMPTS_DIR).replace("\\", "/")
        self.assertTrue(normalized.endswith("consilium/prompts/voices"), normalized)

    def test_all_prompts_load(self):
        from consilium.voices import load_prompt
        for name in self._ALL_PROMPTS:
            with self.subTest(prompt=name):
                text = load_prompt(name)
                self.assertTrue(text.strip(), f"{name}.md is empty")


class TestCallVoiceAnthropic(unittest.TestCase):
    def test_returns_first_text_block(self):
        from consilium.voices import call_voice
        block = MagicMock(type="text", text="hello")
        mock_resp = MagicMock(content=[block])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        with patch("consilium.voices._get_client", return_value=mock_client):
            self.assertEqual(call_voice("c", "sys", "user", "claude-sonnet-4-6"), "hello")

    def test_no_text_block_returns_empty(self):
        from consilium.voices import call_voice
        mock_resp = MagicMock(content=[])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        with patch("consilium.voices._get_client", return_value=mock_client):
            self.assertEqual(call_voice("g", "sys", "user", "claude-sonnet-4-6"), "")


class TestCallVoiceLiteLLM(unittest.TestCase):
    def test_slash_model_uses_litellm(self):
        """Model with '/' routes to litellm.completion()."""
        from consilium.voices import call_voice
        mock_litellm = MagicMock()
        mock_litellm.completion.return_value.choices[0].message.content = "litellm response"
        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            result = call_voice("g", "sys", "user", "openai/gpt-4o")
        self.assertEqual(result, "litellm response")
        mock_litellm.completion.assert_called_once()
        self.assertEqual(mock_litellm.completion.call_args.kwargs["model"], "openai/gpt-4o")

    def test_litellm_debug_footer_suppressed(self):
        """The LiteLLM path sets suppress_debug_info to silence the stderr footer."""
        from consilium.voices import call_voice
        mock_litellm = MagicMock()
        mock_litellm.completion.return_value.choices[0].message.content = "ok"
        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            call_voice("g", "sys", "user", "openai/gpt-4o")
        self.assertIs(mock_litellm.suppress_debug_info, True)

    def test_slash_model_missing_litellm_raises(self):
        """'/' model with a broken litellm install still raises ImportError."""
        from consilium.voices import call_voice
        with patch.dict(sys.modules, {"litellm": None}):
            with self.assertRaises(ImportError):
                call_voice("g", "sys", "user", "openai/gpt-4o")

    def test_non_slash_model_stays_on_anthropic_path(self):
        """Model without '/' stays on the Anthropic SDK path."""
        from consilium.voices import call_voice
        block = MagicMock(type="text", text="anthropic response")
        mock_resp = MagicMock(content=[block])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        with patch("consilium.voices._get_client", return_value=mock_client):
            result = call_voice("c", "sys", "user", "claude-sonnet-4-6")
        self.assertEqual(result, "anthropic response")


class TestPlainAnswer(unittest.TestCase):
    def test_routes_through_call_voice(self):
        """plain_answer() makes one call_voice() call with the assistant system prompt."""
        from consilium import voices
        with patch.object(voices, "call_voice", return_value="hello there") as mock:
            result = voices.plain_answer("hi", "some-model")
        self.assertEqual(result, "hello there")
        mock.assert_called_once()
        _name, system, user_msg, model = mock.call_args.args
        self.assertIn("not a code change", system)
        self.assertEqual(user_msg, "hi")
        self.assertEqual(model, "some-model")

    def test_short_response_routes_through_call_voice(self):
        """short_response() makes one concise call_voice() call."""
        from consilium import voices
        with patch.object(voices, "call_voice", return_value="short!") as mock:
            result = voices.short_response("trivial change", "m")
        self.assertEqual(result, "short!")
        mock.assert_called_once()
        _name, system, user_msg, model = mock.call_args.args
        self.assertIn("2 sentences", system)
        self.assertEqual(user_msg, "trivial change")

    def test_plain_answer_forwards_context_to_the_model(self):
        """Retrieved context reaches the model — otherwise the answer is ungrounded."""
        from consilium import voices
        with patch.object(voices, "call_voice", return_value="grounded") as mock:
            voices.plain_answer("what is X?", "m", context="RELEVANT DOCS:\n  - [a.md#0] 'X is 42'")
        _name, _system, user_msg, _model = mock.call_args.args
        self.assertIn("X is 42", user_msg)
        self.assertIn("what is X?", user_msg)

    def test_short_response_forwards_context_to_the_model(self):
        """The scale_down path is grounded too, not just the not_a_proposal path."""
        from consilium import voices
        with patch.object(voices, "call_voice", return_value="short") as mock:
            voices.short_response("bump the timeout", "m", context="RELEVANT DOCS:\n  - [t.md#0] 'timeout is 30s'")
        _name, _system, user_msg, _model = mock.call_args.args
        self.assertIn("timeout is 30s", user_msg)

    def test_plain_answer_without_context_sends_bare_message(self):
        """No context means no wrapper — a greeting must not gain an empty docs block."""
        from consilium import voices
        with patch.object(voices, "call_voice", return_value="hi") as mock:
            voices.plain_answer("hello", "m")
        _name, _system, user_msg, _model = mock.call_args.args
        self.assertEqual(user_msg, "hello")


if __name__ == "__main__":
    unittest.main()


# ── truncated-voice envelope gate (measured 2026-07-29) ─────────────────────
# A live deliberation was instrumented: Generator cut off mid-string at 729 chars and
# Control at 747, both without a closing ``` fence. extract_json's brace-walk skipped the
# incomplete OUTER object and returned the first complete INNER one — a single candidate
# — as if it were the whole Generator output. Truthy, so the aggregator waved it through.

# The measured Generator shape: outer object never closes, inner candidate does.
TRUNCATED_GENERATOR = '''```json
{
  "candidates": [
    {
      "id": "do_nothing",
      "summary": "Reject the change; keep current behavior.",
      "sketch": "No code changes.",
      "rationale": "Baseline for comparison.",
      "downside_estimate": "goal remains unaddressed"
    },
    {
      "id": "immediate_discipline_block",
      "summary": "Check only the core disciplinary rules; if blocked, report'''


def test_extract_json_still_recovers_the_nested_fragment():
    """Pins the CAUSE, not the cure: extract_json is unchanged and still returns a
    fragment here. The gate lives above it, so this stays true by design."""
    from consilium.voices import extract_json
    got = extract_json(TRUNCATED_GENERATOR)
    assert got.get("id") == "do_nothing"      # an inner candidate, not the envelope
    assert "candidates" not in got
    assert got                                 # truthy — which is why `not out` missed it


def test_envelope_gate_rejects_the_nested_fragment():
    from consilium.voices import extract_json, looks_like_envelope
    assert looks_like_envelope("generator", extract_json(TRUNCATED_GENERATOR)) is False


def test_envelope_gate_accepts_a_complete_voice_output():
    from consilium.voices import looks_like_envelope
    assert looks_like_envelope("generator", {"candidates": [{"id": "a"}], "preferred": "a"})
    assert looks_like_envelope("conservator", {"scores": []})
    assert looks_like_envelope("control", {"verdicts": [], "glossary": {}})
    assert looks_like_envelope("skeptic", {"can_object": False})


def test_envelope_gate_accepts_the_shapes_the_aggregator_actually_tolerates():
    """Not one canonical key per voice: _chosen_candidate reads Generator's legacy
    `options` alongside `candidates`, and a Control output that only reached its
    glossary is still a real envelope. Pinning this caught a false-positive that a
    naive single-key check would have shipped."""
    from consilium.voices import looks_like_envelope
    assert looks_like_envelope("generator", {"preferred": "a", "options": [{"id": "a"}]})
    assert looks_like_envelope("control", {"glossary_fail": False, "glossary": {}, "disagreements": []})


def test_envelope_gate_rejects_a_fragment_of_any_voice():
    """Fragments are list ELEMENTS — a candidate, a score, a verdict — and all carry a
    top-level `id`, which no envelope does. That asymmetry is the discriminator."""
    from consilium.voices import looks_like_envelope
    assert looks_like_envelope("generator", {"id": "do_nothing", "summary": "x"}) is False
    assert looks_like_envelope("conservator", {"id": "a", "regression_risk": {}}) is False
    assert looks_like_envelope("control", {"id": "a", "valid": True, "issues": []}) is False


def test_envelope_gate_tests_key_presence_not_emptiness():
    """Control's objection in the deliberation: an abstain-only Generator legitimately
    emits an EMPTY candidates list, and must not be misread as truncated. Verified
    against the shipped prompts — every documented output block carries its key,
    generator.md's abstain example included."""
    from consilium.voices import looks_like_envelope
    assert looks_like_envelope("generator", {"candidates": [], "abstain": {"triggered": True}})
    assert looks_like_envelope("conservator", {"scores": []})


def test_envelope_gate_rejects_empty_and_tolerates_unknown_shapes():
    from consilium.voices import looks_like_envelope
    assert looks_like_envelope("generator", {}) is False
    # Unregistered voice / unrecognised shape: tolerated unless it looks like a fragment.
    assert looks_like_envelope("some_future_voice", {"anything": 1}) is True
    assert looks_like_envelope("some_future_voice", {"id": "frag"}) is False


def test_every_json_voice_has_registered_envelope_keys():
    """A JSON voice with no registered keys falls back to the fragment signature alone —
    weaker. Adding one to _JSON_VOICES must mean registering its envelope keys."""
    from consilium.voices import VOICE_ENVELOPE_KEYS, _JSON_VOICES
    assert _JSON_VOICES <= set(VOICE_ENVELOPE_KEYS)


# ── output discipline on attempt 1 (2026-07-29) ─────────────────────────────
# Measured: voices emit their JSON in a fence and then append prose commentary. When the
# closing fence is present extract_json works; when the model flows into prose without
# closing it, the fence regex fails. stop_reason was "end_turn" — the model finished on
# its own, so this is not a token cap.
#
# The instruction that prevents it already existed in the repo — but only on the RETRY
# (voices.py appends it from attempt 2 on). Attempt 1 had no output-discipline rule at
# all: each prompt's "## Output format" section showed a fenced example and said nothing
# about what may precede or follow it. These pin the clause onto attempt 1.

_NO_TRAILING_PROSE = "no prose, headings, or commentary before or after it"


def test_json_voices_carry_the_output_discipline_clause_on_attempt_one():
    from consilium.voices import load_prompt, _JSON_VOICES
    for name in sorted(_JSON_VOICES):
        assert _NO_TRAILING_PROSE in load_prompt(name), (
            f"{name}.md must state the output discipline on the FIRST attempt; relying on "
            "voices.py's retry to say it means every flaky reply costs an extra spawn"
        )


def test_the_clause_is_schema_neutral():
    """It is shared verbatim across voices with structurally different envelopes —
    skeptic's is `can_object`, not a list — so it must not name any envelope key."""
    from consilium.voices import load_prompt, VOICE_ENVELOPE_KEYS
    every_key = {k for keys in VOICE_ENVELOPE_KEYS.values() for k in keys}
    for name in ("generator", "conservator", "control", "skeptic"):
        clause_line = next(ln for ln in load_prompt(name).splitlines()
                           if _NO_TRAILING_PROSE in ln or "ONLY the JSON object" in ln)
        for key in every_key:
            assert key not in clause_line, f"{name}: clause names envelope key {key!r}"


def test_prose_voices_do_not_get_the_json_clause():
    """assistant/explain return prose by contract — telling them to emit only JSON
    would break them. The clause belongs to _JSON_VOICES only."""
    from consilium.voices import load_prompt
    assert _NO_TRAILING_PROSE not in load_prompt("explain")
