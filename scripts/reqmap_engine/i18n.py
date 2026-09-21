"""The translation cache (`_i18n/<locale>.json`): gaps, hashes, attaching translations to nodes.
"""
import hashlib, json, os

from . import config as cfg
from .sections import ACCEPTANCE_LABELS, CONTRACT_LABELS, _from_any
from .text import _first_quote, _section_raw, _title


# ---------------------------------------------------------------------------
# Content translation, reading half — implements: ARCH-TRANSLATE-044
#
# READ-ONLY. The command that produced `requirements/_i18n/<locale>.json` was
# removed on 2026-09-05, together with everything that shelled out to an
# external LLM CLI. What is left reads an already-committed cache file, so no
# code path in this engine starts a subprocess and the gate/sync/CI path stays
# usable on a machine that has never heard of `claude`. A cache entry is served
# only while its hash matches the requirement, so the cache decays as
# requirements are edited and refreshing it is a manual step.
# ---------------------------------------------------------------------------
TRANSLATOR_VERSION = "1"   # part of the cache key: bump to invalidate every cached
LANGUAGE_LOCALES = {"en": (), "ro": ("ro",), "both": ("ro",)}   # locales a setting expects filled


def _translation_gaps(reqs, reqs_dir):
    # implements: ARCH-TRANSLATE-044  # implements: REQ-TRANSLATE-996
    """Every (requirement, locale) the configured LANGUAGE expects a fresh translation
    for and does not have, with the reason and the exact source fields to translate.

    Reads the cache files raw rather than through `_load_translations`, which drops a
    stale entry silently — here "stale" is the finding, so the two must be told apart.
    Returns `[]` under `en`: nothing is expected, so nothing is missing."""
    out = []
    for locale in LANGUAGE_LOCALES.get(cfg.LANGUAGE, ()):
        cache = {}
        try:
            with open(os.path.join(reqs_dir, "_i18n", locale + ".json"), encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        if not isinstance(cache, dict):
            cache = {}
        for rid in sorted(reqs):
            r = reqs[rid]
            if r["meta"].get("status") == "deprecated":
                continue
            body = r["body"]
            title = _title(body)
            want = translation_hash(body, title)
            entry = cache.get(rid)
            have = entry.get("hash") if isinstance(entry, dict) else None
            if have == want:
                continue
            out.append({
                "id": rid, "locale": locale,
                "reason": "stale" if entry is not None else "missing",
                "hash": want,
                "title": title,
                "intent": _first_quote(body),
                "contract": _from_any(_section_raw, body, CONTRACT_LABELS),
                "acceptance": _from_any(_section_raw, body, ACCEPTANCE_LABELS),
            })
    return out


def cmd_i18n(ws, as_json=False):  # implements: ARCH-TRANSLATE-044  # implements: REQ-TRANSLATE-996
    """`ask --i18n`: the translations the configured LANGUAGE expects and does not have.

    Read-only. The JSON form is the hand-off: each entry carries the four source fields
    exactly as the hash was computed over them, plus that hash, so whoever translates —
    the skill, an assistant, a person — writes `_i18n/<locale>.json[id]` with the four
    translated fields and the same `hash`, and the next `sync` serves it. The engine
    calls nothing external (REQ-TRANSLATE-937); it says what is owed and by what key."""
    reqs, reqs_dir = ws.reqs, ws.reqs_dir
    gaps = _translation_gaps(reqs, reqs_dir)
    if as_json:
        print(json.dumps({"language": cfg.LANGUAGE, "gaps": gaps}, indent=2, ensure_ascii=False))
        return 0
    if not LANGUAGE_LOCALES.get(cfg.LANGUAGE):
        print("LANGUAGE is `{}` - no translation is expected. Set `\"LANGUAGE\": \"ro\"` or "
              "`\"both\"` in requirements/{} to have the engine track Romanian coverage."
              .format(cfg.LANGUAGE, cfg.CONFIG_FILE))
        return 0
    if not gaps:
        print("LANGUAGE is `{}` - every requirement has a fresh translation in: {}."
              .format(cfg.LANGUAGE, ", ".join(LANGUAGE_LOCALES[cfg.LANGUAGE])))
        return 0
    missing = sum(1 for g in gaps if g["reason"] == "missing")
    print("LANGUAGE is `{}` - {} requirement(s) need a translation ({} missing, {} stale):\n"
          .format(cfg.LANGUAGE, len(gaps), missing, len(gaps) - missing))
    for g in gaps:
        print("  {:<8} {:<26} {:<7} {}".format(g["locale"], g["id"], g["reason"], g["title"][:60]))
    print("\nRe-run with --json for the source fields and the cache key to write back; "
          "each entry goes in requirements/_i18n/<locale>.json under its id, with the same `hash`.")
    return 0


def _translation_source_text(body, title):  # implements: ARCH-TRANSLATE-044
    """The exact span that gets translated and hashed: title + WHY + Contract +
    Acceptance. Deliberately wider than binding_hash() (Contract+Acceptance only) —
    a title-only edit must also invalidate a cached translation."""
    return "\n".join([
        title, _first_quote(body),
        _from_any(_section_raw, body, CONTRACT_LABELS),
        _from_any(_section_raw, body, ACCEPTANCE_LABELS),
    ])


def translation_hash(body, title):
    # implements: ARCH-TRANSLATE-044  # implements: REQ-TRANSLATE-937
    """Cache-invalidation key for one requirement's translation. NOT binding_hash() —
    see _translation_source_text. Includes TRANSLATOR_VERSION so bumping the prompt
    or the model invalidates every cached entry in one step, not file-by-file."""
    h = hashlib.sha256()
    h.update(_translation_source_text(body, title).encode("utf-8"))
    h.update(TRANSLATOR_VERSION.encode("utf-8"))
    return h.hexdigest()[:12]


def _load_translations(reqs, reqs_dir):
    # implements: ARCH-TRANSLATE-044  # implements: REQ-TRANSLATE-938
    """Read every requirements/_i18n/<locale>.json cache file and return
    {rid: {locale: {title, intent, contract, acceptance}}} for entries whose
    stored hash still matches the requirement's CURRENT content. A stale entry
    (source edited since the last `translate` run) is silently dropped rather
    than served — this is what keeps `map`/`map --check` deterministic and
    `claude`-free: they only ever read a file already sitting on disk, and they
    never serve a translation known to be out of date."""
    i18n_dir = os.path.join(reqs_dir, "_i18n")
    if not os.path.isdir(i18n_dir):
        return {}
    out = {}
    for fname in sorted(os.listdir(i18n_dir)):
        if not fname.endswith(".json"):
            continue
        locale = fname[:-len(".json")]
        try:
            with open(os.path.join(i18n_dir, fname), encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(cache, dict):
            continue
        for rid, entry in cache.items():
            r = reqs.get(rid)
            if not r or not isinstance(entry, dict):
                continue
            title = _title(r["body"])
            if entry.get("hash") != translation_hash(r["body"], title):
                continue
            out.setdefault(rid, {})[locale] = {
                k: entry.get(k, "") for k in ("title", "intent", "contract", "acceptance")
            }
    return out


def _attach_translations(data, reqs, reqs_dir):
    # implements: ARCH-TRANSLATE-044  # implements: REQ-TRANSLATE-938
    """Mutate data['nodes'] in place, adding node['i18n'] = {locale: {...}} for
    any node with a fresh cached translation. Shared by cmd_map
    so both emit the same graph — no `claude` call here, file reads only."""
    i18n = _load_translations(reqs, reqs_dir)
    for node in data["nodes"]:
        if node["id"] in i18n:
            node["i18n"] = i18n[node["id"]]
    return data
