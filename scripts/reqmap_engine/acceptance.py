"""The acceptance section: CASE-N blocks, folded items, labelled and automatable criteria."""
import re

from .sections import ACCEPTANCE_LABELS, _atomic_spans, _section_lines


_AC_LABEL_RE = re.compile(r"^((?:CASE|AC)-\d+)\b")   # CASE-N is current, AC-N legacy
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# The template records how a criterion is checked as an HTML comment on its label:
# `AC-1  <!-- verifiable by: automated test -->`. Only this vocabulary marks a
# criterion a machine can never verify; an ABSENT marker means automatable, so a
# corpus that never adopted the marker keeps exactly the behavior it had.
_AC_VERIFIABLE_RE = re.compile(r"verifiable\s+by\s*:([^>]*)", re.I)
_AC_MANUAL_WORDS = ("manual", "inspection", "review", "demo", "walkthrough", "sign-off")


def _acc_blocks(body):  # implements: ARCH-ACVERIFY-019  # implements: REQ-ATOMICFORM-053
    """Parse the HOW — Acceptance section into one record per criterion:
    `{"label": "AC-1" or "", "text": <folded prose>, "manual": bool}`.

    Two authoring shapes exist and both count: the labelled Gherkin BLOCK the
    template prescribes (`AC-1` followed by indented Given/When/Then lines) and a
    plain `- ` bullet. `_bullets` sees only the second, which is why the emitted
    `acc` list was empty for every requirement written the prescribed way — the map,
    the viewer, and any downstream count had nothing to read (50/50 nodes here).

    An atomic body has no Acceptance heading: its single `Scenario:` block is the one
    criterion, returned unlabelled so `# verifies: <ID>#AC-N` has nothing to point at —
    at one criterion per requirement, `tested-by:` is already per-criterion precision.

    One parser, three callers (`_acc_items`, `_labeled_acs`, `_count_ac`) so a
    criterion cannot be counted by one and missed by another. The block-start test
    is `_count_ac`'s verbatim, keeping `len(_acc_blocks(b)) == _count_ac(b)`."""
    _sp = _atomic_spans(body)
    if _sp:                                        # atomic: the Scenario is the one criterion
        _txt = " ".join(l.strip() for l in _sp[1])
        return [{"label": "", "text": _txt, "manual": bool(_AC_VERIFIABLE_RE.search(_txt))
                 and any(w in _txt.lower() for w in _AC_MANUAL_WORDS)}]
    out = []
    for s in _section_lines(body, ACCEPTANCE_LABELS):
        m = _AC_LABEL_RE.match(s)
        if m or s.startswith("- "):
            label = m.group(1) if m else ""
            out.append({"label": label, "raw": [s[len(label):] if m else s[2:]]})
        elif s and out:
            # continuation of the criterion above (an indented Given/When/Then line,
            # or a marker comment on its own line) — folded in, so a multi-line
            # criterion is never truncated to its first physical line.
            out[-1]["raw"].append(s)
    blocks = []
    for b in out:
        raw = " ".join(b["raw"]).strip()
        mark = _AC_VERIFIABLE_RE.search(raw)
        marker = mark.group(1) if mark else ""
        blocks.append({
            "label": b["label"],
            "text": _HTML_COMMENT_RE.sub("", raw).strip(),
            # `|` means the template's unedited placeholder list ("automated test |
            # manual | inspection | load test") — an author who never chose is not
            # declaring the criterion manual.
            "manual": "|" not in marker and any(w in marker.lower() for w in _AC_MANUAL_WORDS),
        })
    return blocks


def _acc_items(body):  # implements: ARCH-MAP-007
    """Acceptance criteria as display strings, for the emitted `acc` list: an
    `AC-1 — Given … When … Then …` line per labelled block, or the bullet text."""
    out = []
    for b in _acc_blocks(body):
        label, text = b["label"], b["text"]
        item = f"{label} — {text}" if label and text else (label or text)
        if item:
            out.append(item)
    return out


def _labeled_acs(body):  # implements: ARCH-ACVERIFY-019  # implements: REQ-ACVERIFY-822
    """Ordered list of `AC-N` labels declared in the HOW — Acceptance section.
    Empty when the requirement writes bullet ACs without labels — per-AC coverage
    only applies to requirements that label their criteria, so unlabelled ones are
    silently exempt (no false 'unverified' warning)."""
    out = []
    for b in _acc_blocks(body):
        if b["label"] and b["label"] not in out:
            out.append(b["label"])
    return out


def _automatable_acs(body):  # implements: ARCH-ACVERIFY-019  # implements: REQ-ACVERIFY-822
    """`_labeled_acs` minus the criteria marked `verifiable by: inspection|manual`.
    A criterion a human checks by reading can never carry a `# verifies:` tag, so
    counting it as unverified is a warning no one can ever clear — the marker the
    template already prescribes is the answer, it simply was not read here."""
    return [b["label"] for b in _acc_blocks(body)
            if b["label"] and not b["manual"]]
