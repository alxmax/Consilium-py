"""Generate the consilium-py architecture poster (.excalidraw + .html).

ONE scene, layers stacked top -> bottom:
  1 STRUCTURE   2 WORKFLOW   3 MODES   4 INTEGRATION   5 DATA   6 DISTRIBUTION
Colour encodes role (see legend); jargon decoded in the glossary.
Re-run to regenerate: python scripts/make_diagram.py
"""
import sys, os, glob, re


def _builder_path():
    cache = os.path.join(os.path.expanduser("~"), ".claude", "plugins",
                         "cache", "requirement-manager", "requirement-manager")
    hits = glob.glob(os.path.join(cache, "*", "skills",
                                  "excalidraw-diagram", "scripts"))
    if not hits:
        raise RuntimeError("excalidraw-diagram skill not found")

    def _ver(p):
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", p)
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    return max(hits, key=_ver)


sys.path.insert(0, _builder_path())
from excalidraw_builder import Scene  # noqa: E402

ROLES = {
    "interface":    "blue",     # CLI / Python API surface
    "engine":       "teal",     # dispatcher + mode orchestration
    "voice":        "violet",   # the deliberating voices + prompts
    "aggregation":  "orange",   # verdict/confidence synthesis
    "external":     "grey",     # third-party systems & deps
    "data":         "green",    # records / persisted state / I/O
    "tooling":      "yellow",   # dev tooling
    "distribution": "pink",     # how it ships
}

s = Scene(seed=7, roles=ROLES)
s.title("consilium-py — architecture", 40, -50, size=30)
s.label("Three AI voices deliberate a code change into a GO/MODIFY/STOP verdict. "
        "Read top -> bottom: components, run order, modes, integration, data, shipping.",
        40, -8, size=13)

# ── 1 · STRUCTURE ────────────────────────────────────────────────────────────
y = s.section("1 - STRUCTURE   the modules under src/consilium/")
gx, gy = 80, y + 8
pkg = s.grid([
    ("cli.py\ndeliberate/check/index", "interface"),
    ("__init__.py\ndeliberate() API", "interface"),
    ("modes/\nseq.dia.trias.lg", "engine"),
    ("voices.py\nAPI dispatch", "voice"),
    ("prompts/voices\n7 .md prompts", "voice"),
    ("skeptic.py\nadversarial pass", "voice"),
    ("aggregator.py\nscheme -> verdict", "aggregation"),
    ("confidence.py\nscore variance", "aggregation"),
    ("models.py\nReport schema", "data"),
    ("rag.py\npast-run recall", "data"),
], gx, gy, 5, w=178, h=64, gap_x=40, gap_y=34, font_size=12)
s.enclose(pkg, pad=22, label=None)
pkg_cx = gx + (5 * 178 + 4 * 40) / 2
s.label("consilium-py package (src/consilium/)", pkg_cx, gy + 64 * 2 + 34 + 30, size=13)
# dev tooling, lives outside the package
tool = s.box("reqmap.py\nrequirement SSOT", gx + 5 * 178 + 4 * 40 + 70, gy + 50,
             w=170, h=64, fill="tooling", font_size=12)
s.label("scripts/ (dev tooling)", gx + 5 * 178 + 4 * 40 + 70 + 85, gy + 124, size=12)

# ── 2 · WORKFLOW ──────────────────────────────────────────────────────────────
y = s.section("2 - WORKFLOW   sequential run order (left -> right)")
ids = s.pipeline([
    {"text": "PROPOSAL\n+ context", "kind": "terminator", "fill": "data", "label": "propose"},
    {"text": "Generator", "kind": "process", "fill": "voice", "label": "blind to risk"},
    {"text": "Conservator", "kind": "process", "fill": "voice", "label": "scores risk"},
    {"text": "Control", "kind": "process", "fill": "voice", "label": "audits"},
    {"text": "aggregate", "kind": "decision", "fill": "aggregation", "label": "verdict"},
    {"text": "Report", "kind": "terminator", "fill": "data"},
], 80, y, gap=205, font_size=13)
s.label("Each voice = 1 model call via voices.call_voice(); aggregator gates on "
        "glossary_fail / irreversibility -> BLOCK.", 80 + 360, y + 112, size=12, align="center")

# ── 3 · MODES ─────────────────────────────────────────────────────────────────
y = s.section("3 - MODES   four variants of the same flow")
seq = s.box("sequential\n(default)", 80, y, w=160, h=70, fill="engine", font_size=13)
s.label("Gen -> Cons -> Ctrl", 160, y + 80, size=12)
dia = s.box("dialectic", 320, y, w=160, h=70, fill="engine", font_size=13)
s.label("sequential + Skeptic", 400, y + 80, size=12)
pers = s.column([("Pioneer", "voice"), ("Architect", "voice"), ("Steward", "voice")],
                600, y, w=150, h=44, gap=16, font_size=13)
s.enclose(pers, pad=20, label=None)
s.label("trias - 3 personalities, parallel, majority vote", 675, y + 3 * 44 + 2 * 16 + 26, size=12)
lg = s.box("langgraph", 880, y, w=160, h=70, fill="engine", font_size=13)
s.label("StateGraph orchestration", 960, y + 80, size=12)

# ── 4 · INTEGRATION ───────────────────────────────────────────────────────────
y = s.section("4 - INTEGRATION   invoked, external systems, persisted state")
cli = s.box("consilium CLI\ndeliberate/check/index", 80, y, w=190, h=70, fill="interface", font_size=12)
gitd = s.box("git diff", 80, y + 180, w=190, h=64, fill="external", font_size=13)
api = s.box("deliberate()\nPython API", 80, y + 360, w=190, h=64, fill="interface", font_size=12)
eng = s.box("deliberate()\ndispatch + modes", 420, y + 170, w=180, h=90, fill="engine", font_size=13)
anth = s.box("Anthropic API", 880, y, w=180, h=70, fill="external", font_size=13)
ltl = s.box("LiteLLM\nprovider/model", 880, y + 150, w=180, h=70, fill="external", font_size=12)
chroma = s.box("ChromaDB", 880, y + 340, w=180, h=64, fill="external", font_size=13)
state = s.box("~/.consilium/\nruns + chroma", 1260, y + 337, w=180, h=70, fill="data", font_size=12)

s.arrow(gitd, cli, label="check")
s.arrow(cli, eng, label="invoke")
s.arrow(api, eng, label="call")
s.arrow(eng, anth, label="voice call")
s.arrow(eng, ltl, label="provider/")
s.arrow(eng, chroma, label="rag: recall/index")
s.arrow(chroma, state, label="save_run")

# ── 5 · DATA ──────────────────────────────────────────────────────────────────
y = s.section("5 - DATA   the Report record (models.py)")
rep = s.box("Report\nverdict\nconfidence\nrecommendation\nvoices[]\nchosen . mode . skeptic",
            420, y, w=210, h=176, fill="data", font_size=13)
v1 = s.box("verdict in\nGO.MODIFY.STOP\nBLOCK.ESCALATE", 90, y, w=250, h=80, fill="aggregation", font_size=12)
v2 = s.box("confidence 0.0-1.0\ninter-voice agreement", 90, y + 100, w=250, h=70, fill="aggregation", font_size=12)
v3 = s.box("voices[]: VoiceOutput\nvote . score . concerns", 710, y, w=250, h=80, fill="voice", font_size=12)
v4 = s.box("skeptic: SkepticObjection\nfailure_mode . addressable", 710, y + 100, w=250, h=70, fill="voice", font_size=12)
s.arrow(rep, v1)
s.arrow(rep, v2)
s.arrow(rep, v3)
s.arrow(rep, v4)

# ── 6 · DISTRIBUTION ──────────────────────────────────────────────────────────
y = s.section("6 - DISTRIBUTION   how it ships")
pypi = s.box("PyPI\nconsilium-py", 80, y, w=170, h=70, fill="distribution", font_size=13)
pipi = s.box("pip install", 330, y, w=150, h=70, fill="distribution", font_size=13)
entry = s.box("consilium\nconsole script", 760, y, w=170, h=70, fill="interface", font_size=12)
extras = s.box("extras:\n[rag] [langgraph]\n[litellm]", 760, y + 120, w=190, h=80, fill="distribution", font_size=12)
s.arrow(pypi, pipi)
s.arrow(pipi, entry, label="entry point")
s.arrow(pipi, extras, label="optional deps")
s.label("Each extra pulls its own deps only when installed; the core install is anthropic + click + pydantic.",
        300, y + 215, size=11, align="center")

# ── legend + glossary ─────────────────────────────────────────────────────────
y = s.section("Legend & glossary")
s.legend(x=80, y=y, title="Role (colour)")
s.glossary([
    ("SSOT", "single source of truth (requirement map)"),
    ("Skeptic", "one adversarial pass on the chosen approach"),
    ("Trias", "3 personalities (Pioneer/Architect/Steward) vote"),
    ("RAG", "inject similar past runs as extra context"),
    ("LiteLLM", "provider-agnostic gateway: provider/model"),
    ("glossary_fail", "Control gate: non-verifiable terms -> BLOCK"),
], 360, y, title="Terms")

s.save("consilium_architecture", out_dir="docs",
       crossing_check="error", legend_check="error",
       overflow_check="error", text_overlap_check="error")
print("OK")
