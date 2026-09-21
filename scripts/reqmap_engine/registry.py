import json, os, re

from . import ENGINE_DIR
from .commands import COMMANDS, COMMAND_GROUPS


def _cli_choices():  # implements: REQ-CMDREGISTRY-834
    """The CLI command names, derived from the registry (single source of truth)."""
    return list(COMMANDS)


def _generate_schema():  # implements: ARCH-CMDREGISTRY-033
    """Function-calling schema (OpenAI tool format) generated from COMMANDS.
    Returns a JSON string (indent=2, trailing newline) — byte-stable for the gate
    drift-compare. Internal commands are excluded from the AI-facing schema."""
    # A flag that takes many values must not be advertised as a lone string: a caller
    # that believes the schema sends one id and never learns the other eleven were
    # dropped. `list` is the only entry whose JSON shape needs an `items` clause.
    _TYPE = {"bool": "boolean", "str": "string", "float": "number", "int": "integer",
             "list": "array"}
    tools = []
    for name, spec in COMMANDS.items():
        if spec.get("internal") or spec.get("tool") is False:
            continue
        props = {"root": {"type": "string",
                          "description": "Repo root where requirements/ lives; "
                                         "defaults to the current directory."}}
        if spec.get("arg"):
            props["arg"] = {"type": "string", "description": spec["arg"]}
        for p in spec["params"]:
            props[p["name"]] = {"type": _TYPE[p["type"]], "description": p["help"]}
            if p["type"] == "list":
                props[p["name"]]["items"] = {"type": "string"}
        tools.append({"type": "function", "function": {
            "name": "reqmap_" + name.replace("-", "_"),
            "description": spec["summary"],
            "parameters": {"type": "object", "properties": props, "required": []},
        }})
    return json.dumps(tools, indent=2, ensure_ascii=False) + "\n"


def commands_manifest():  # implements: ARCH-CMDREGISTRY-033  # implements: REQ-CMDREGISTRY-963
    """The command registry as data, for any surface that documents the CLI without
    running it — the map viewer's command reference is the first. Derived from
    COMMANDS, so a command that exists is documented and one that does not, is not."""
    group_of = {}
    for group, names in COMMAND_GROUPS:
        for n in names:
            group_of[n] = group
    out = []
    for name, spec in COMMANDS.items():
        if spec.get("internal"):
            continue
        out.append({
            "name": name,
            "group": group_of.get(name, "read"),
            "summary": " ".join(spec["summary"].split()),
            "arg": spec.get("arg"),
            "flags": [{"flag": p["flag"], "help": " ".join(p["help"].split())}
                      for p in spec["params"]],
        })
    return out


def _generate_command_table():  # implements: REQ-CMDREGISTRY-834
    """A markdown table of the user CLI commands from COMMANDS, for the generated
    region inside SKILL.universal.md. Internal commands are excluded."""
    rows = ["| Command | What it does | Flags |", "|---|---|---|"]
    for name, spec in COMMANDS.items():
        if spec.get("internal"):
            continue
        flags = ", ".join("`" + p["flag"] + "`" for p in spec["params"]) or "—"
        rows.append("| `{}` | {} | {} |".format(name, spec["summary"], flags))
    return "\n".join(rows)


def _generate_command_list():  # implements: REQ-CMDREGISTRY-834
    """The command reference for SKILL.md, grouped the way COMMAND_GROUPS groups the
    verbs, as the bullet list that file has always used. SKILL.md is the contract an
    assistant reads when it meets the engine on a fresh repo, and a hand-kept list there
    documented `scan` after it was gone and five different verbs under the name `sync`.
    Rendered from the registry, a verb that exists is documented and one that does not,
    is not — the same guarantee the universal table already had."""
    group_of = {}
    for group, names in COMMAND_GROUPS:
        for n in names:
            group_of[n] = group
    titles = {"author": "Author", "build": "Build", "read": "Read"}
    lines = []
    for group, _names in COMMAND_GROUPS:
        members = [(n, s) for n, s in COMMANDS.items()
                   if not s.get("internal") and group_of.get(n, "read") == group]
        if not members:
            continue
        lines.append("**{}**".format(titles.get(group, group.title())))
        for name, spec in members:
            call = "python scripts/reqmap.py " + name
            if spec.get("arg"):
                call += " " + spec["arg"]
            flags = "; ".join("`{}` {}".format(p["flag"], " ".join(p["help"].split()))
                              for p in spec["params"])
            lines.append("- `{}` — {}{}".format(
                call, " ".join(spec["summary"].split()),
                " Flags: " + flags + "." if flags else ""))
        lines.append("")
    return "\n".join(lines).rstrip()


_REGION_RE = re.compile(
    r"(<!--##REQMAP:COMMANDS##-->)(.*?)(<!--##/REQMAP:COMMANDS##-->)", re.DOTALL)

# Every generated region, with the renderer that owns it. Both the writer and the
# freshness check walk this one list, so adding a surface here is the whole job.
_SKILL_REGIONS = (
    (("skills", "requirement-manager", "SKILL.universal.md"), _generate_command_table),
    (("skills", "requirement-manager", "SKILL.md"), _generate_command_list),
)


def _write_region(path, body):  # implements: REQ-CMDREGISTRY-834
    """Replace the delimited region body in `path`; prose outside is untouched."""
    # newline="" on both ends: read/write the file's own line endings verbatim so
    # regenerating the region never silently normalizes the WHOLE file's CRLF to LF on
    # read (universal-newline translation) with no re-translation on write.
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    # The body is generated with bare "\n". Written as-is into a CRLF file it left
    # the region LF inside CRLF prose. `_check_integration_fresh` reads the file with
    # universal newlines, so CRLF collapses to LF before the comparison and the gate
    # saw nothing wrong; git did, and every `sync` on Windows left a line-ending-only
    # diff. The body takes the file's own convention, the way `tool_definition.json`
    # already did.
    eol = "\r\n" if "\r\n" in text else "\n"
    body = body.replace("\r\n", "\n").replace("\n", eol)
    new = _REGION_RE.sub(lambda m: m.group(1) + eol + body + eol + m.group(3), text)
    if new != text:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new)


def cmd_gen_integration(reqs_dir, code_root):  # implements: REQ-CMDREGISTRY-834
    """Write tool_definition.json (OpenAI function-calling schema) generated from COMMANDS."""
    plugin_root = os.path.dirname(ENGINE_DIR)
    tj_path = os.path.join(plugin_root, "tool_definition.json")
    schema = _generate_schema()
    # newline="" on both ends: read the file's existing CRLF/LF convention verbatim and
    # re-apply it explicitly before writing. _generate_schema() always joins with bare
    # "\n", so a bare text-mode write here would flip the whole committed CRLF file to LF
    # on any non-Windows host (os.linesep == "\n" there) even though the JSON is unchanged.
    eol = "\n"
    if os.path.exists(tj_path):
        with open(tj_path, encoding="utf-8", newline="") as f:
            if "\r\n" in f.read():
                eol = "\r\n"
    if eol == "\r\n":
        schema = schema.replace("\n", "\r\n")
    with open(tj_path, "w", encoding="utf-8", newline="") as f:
        f.write(schema)
    print("wrote tool_definition.json")
    for parts, render in _SKILL_REGIONS:
        skill = os.path.join(plugin_root, *parts)
        if os.path.exists(skill):
            _write_region(skill, render())
            print("wrote {} command region".format(parts[-1]))
    return 0


def _check_integration_fresh(plugin_root):  # implements: REQ-CMDREGISTRY-834
    """Return a list of stale generated artifacts (empty = fresh). Compares the
    committed tool_definition.json + the SKILL.universal.md command-table region
    against a fresh generation from the registry. Mirrors map --check. Artifacts
    that don't exist (e.g. a consumer repo that doesn't ship them) are skipped, so
    this never breaks a vendored-engine gate."""
    stale = []
    tj = os.path.join(plugin_root, "tool_definition.json")
    if os.path.exists(tj):
        with open(tj, encoding="utf-8") as _f:
            if _f.read() != _generate_schema():
                stale.append("tool_definition.json")
    for parts, render in _SKILL_REGIONS:
        skill = os.path.join(plugin_root, *parts)
        if os.path.exists(skill):
            with open(skill, encoding="utf-8") as _f:
                m = _REGION_RE.search(_f.read())
            if m and m.group(2).strip() != render().strip():
                stale.append("/".join(parts))
    return stale
