"""`reqmap.py mcp`: the engine as a Model Context Protocol server over stdio (ADR-0043).

Each tool is one CLI invocation, run in a fresh `reqmap.py` process. The engine keeps
module state (`apply_config` rewrites `config`, paths resolve against the working
directory), so a long-lived server importing it would carry one call's state into the
next; a subprocess starts clean every time, and the CLI stays the only code path.
"""
# implements: ARCH-MCP-073
import json, os, subprocess, sys

from . import ENGINE_DIR, MAP_ENGINE_VERSION

# The one protocol revision this server speaks. A client asking for another is answered
# with this one, which the specification allows; the client decides whether to go on.
PROTOCOL_VERSION = "2025-06-18"
OUTPUT_CAP = 200000        # characters of one tool result; the rest is cut and said so
CALL_TIMEOUT = 600         # seconds; a full `sync` on a large repo stays well inside it

_JSON = ("--json",)


def _param(name, kind, help_text, flag=None, required=False, bare=False):
    # implements: REQ-MCPTOOLS-1028
    """One tool parameter. `flag` is the CLI flag it becomes; None makes it the
    positional argument that follows the verb. `bare` passes the flag alone when the
    value is omitted, for a flag whose value is optional (`--release [VERSION]`)."""
    return {"name": name, "type": kind, "help": help_text, "flag": flag,
            "required": required, "bare": bare}


_ID = "A requirement id, e.g. ARCH-PARSE-001."

# The tools, named for the question an agent asks rather than for the flag that asks it:
# `gate` once had sixteen flags, most of them separate modes (ADR-0044 moved the questions
# to `ask`). `argv` is the fixed part of the invocation; a test holds every verb and flag
# here to the command registry.
MCP_TOOLS = (
    {"name": "reqmap_gate", "argv": ["gate"], "ok": (0, 1), "writes": False,
     "description": "The verdict: code tags resolve to requirements, no contract drifted, "
                    "test links hold, requirements are readable and the committed map is "
                    "fresh. Exit 1 is a FAIL verdict, not a tool error.",
     "params": [_param("strict", "bool", "Promote drift and test-link warnings to errors.",
                       "--strict"),
                _param("since", "str", "Only requirements whose files changed since this "
                                       "git ref.", "--since")]},
    {"name": "reqmap_next", "argv": ["gate", "--risk"], "writes": False,
     "description": "What to do next: the health score and the counted risk buckets.",
     "params": [_param("all", "bool", "List every pending item, not the top few.", "--all")]},
    {"name": "reqmap_health", "argv": ["gate", "--risk", *_JSON], "writes": False,
     "description": "The health score and its component counts, as JSON.", "params": []},
    {"name": "reqmap_show", "argv": ["gate", *_JSON], "writes": False,
     "description": "One requirement's dossier: contract, dependencies, code members, open "
                    "questions and risk signals, as JSON with the requirement's frontmatter "
                    "and body.",
     "params": [_param("id", "str", _ID, "--show", required=True)]},
    {"name": "reqmap_search", "argv": ["ask", *_JSON], "writes": False,
     "description": "Requirements ranked by relevance to a free-text query, as JSON; an id "
                    "in the query is matched first.",
     "params": [_param("query", "str", "What to look for.", "--search", required=True),
                _param("top", "int", "How many matches to return (default 5).", "--top")]},
    {"name": "reqmap_audit", "argv": ["gate", "--audit", *_JSON], "ok": (0, 1),
     "writes": False,
     "description": "Everything the engine can find, as JSON: gate, health, duplicate "
                    "contracts, design, tag coverage, exemptions and corpus shape.",
     "params": []},
    {"name": "reqmap_dupes", "argv": ["ask", "--dupes", *_JSON], "writes": False,
     "description": "Requirement pairs whose contracts share wording, most similar first, "
                    "as JSON.",
     "params": [_param("threshold", "number", "Cosine cutoff in (0, 1], default 0.35.",
                       "--threshold"),
                _param("top", "int", "Print only this many pairs.", "--top")]},
    {"name": "reqmap_design", "argv": ["ask", "--design", *_JSON], "writes": False,
     "description": "The advisory design review of the repository's code, as JSON.",
     "params": []},
    {"name": "reqmap_untagged", "argv": ["gate", "--risk", "--untagged"], "writes": False,
     "description": "Tag coverage per directory, and the source files no requirement claims.",
     "params": []},
    {"name": "reqmap_review", "argv": ["ask"], "writes": False,
     "description": "The review plan for one requirement, as JSON: intent, contract, cases "
                    "and code anchors, for judging whether the code does what it says.",
     "params": [_param("id", "str", _ID, "--review", required=True)]},
    {"name": "reqmap_clarify", "argv": ["clarify", *_JSON], "writes": False,
     "description": "The questions a requirement has not answered, as JSON; with no id, "
                    "for the whole corpus.",
     "params": [_param("id", "str", _ID)]},
    {"name": "reqmap_release_plan", "argv": ["sync", *_JSON], "writes": False,
     "description": "The release `reqmap_release` would cut, as JSON: version, file "
                    "changes, CHANGELOG entry, plan change and any problem. Writes nothing.",
     "params": [_param("version", "str", "Release this vX.Y.Z instead of the planned one.",
                       "--release", bare=True)]},
    {"name": "reqmap_sync", "argv": ["sync"], "writes": True,
     "description": "Rebuild everything derived: the drift lock, the map, the findings and "
                    "the site regions. Refuses when a confirmed contract changed, unless "
                    "`accept_drift` gives the reason.",
     "params": [_param("accept_drift", "str", "Why the changed contracts are accepted.",
                       "--accept-drift")]},
    {"name": "reqmap_release", "argv": ["sync", "--apply", *_JSON],
     "writes": True,
     "description": "Cut the next planned release: bump the version files, write the "
                    "CHANGELOG entry and drop the milestone from the plan. Tagging stays "
                    "in CI. Exit 2 means it refused and wrote nothing.",
     "params": [_param("version", "str", "Release this vX.Y.Z instead of the planned one.",
                       "--release", bare=True)]},
)

_SCHEMA_TYPE = {"bool": "boolean", "str": "string", "int": "integer", "number": "number"}
_PY_TYPE = {"bool": (bool,), "str": (str,), "int": (int,), "number": (int, float)}


def tool_list(allow_writes):  # implements: ARCH-MCP-073  # implements: REQ-MCPTOOLS-1028
    """The `tools/list` entries this server offers; a writing tool only with `allow_writes`."""
    out = []
    for tool in MCP_TOOLS:
        if tool["writes"] and not allow_writes:
            continue
        props = {p["name"]: {"type": _SCHEMA_TYPE[p["type"]], "description": p["help"]}
                 for p in tool["params"]}
        out.append({
            "name": tool["name"], "description": tool["description"],
            "inputSchema": {"type": "object", "properties": props,
                            "required": [p["name"] for p in tool["params"] if p["required"]],
                            "additionalProperties": False},
            "annotations": {"readOnlyHint": not tool["writes"], "destructiveHint": False,
                            "idempotentHint": not tool["writes"], "openWorldHint": False},
        })
    return out


def tool_argv(tool, args):  # implements: REQ-MCPTOOLS-1028
    """The CLI arguments for one call, or ValueError naming the argument that is wrong.
    A value is passed as its own argv element, never through a shell."""
    known = {p["name"]: p for p in tool["params"]}
    unknown = sorted(set(args) - set(known))
    if unknown:
        raise ValueError("unknown argument(s): " + ", ".join(unknown))
    argv = list(tool["argv"])
    for p in tool["params"]:
        value = args.get(p["name"])
        if value is None:
            if p["required"]:
                raise ValueError("missing required argument: " + p["name"])
            argv += [p["flag"]] if p["bare"] else []
            continue
        ok = isinstance(value, _PY_TYPE[p["type"]]) and not (
            p["type"] != "bool" and isinstance(value, bool))
        if not ok:
            raise ValueError("{} must be a {}".format(p["name"], _SCHEMA_TYPE[p["type"]]))
        if p["type"] == "bool":
            argv += [p["flag"]] if value else []
        elif p["flag"] is None:
            argv.insert(1, str(value))
        else:
            argv += [p["flag"], str(value)]
    return argv


def run_tool(argv, workspace):  # implements: REQ-MCPTOOLS-1028
    """Run `reqmap.py` with `argv` plus the server's workspace flags; (exit code, text)."""
    cmd = [sys.executable, "-X", "utf8", os.path.join(ENGINE_DIR, "reqmap.py")]
    try:
        done = subprocess.run(cmd + argv + workspace, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "timed out after {} s".format(CALL_TIMEOUT)
    text = done.stdout
    if done.stderr.strip():
        text += ("\n" if text else "") + "[stderr]\n" + done.stderr
    if len(text) > OUTPUT_CAP:
        text = text[:OUTPUT_CAP] + "\n[output cut at {} characters]".format(OUTPUT_CAP)
    return done.returncode, text


def call_tool(name, args, server):  # implements: REQ-MCPTOOLS-1028
    """The `tools/call` result, or ValueError for a call the protocol should reject."""
    tool = next((t for t in MCP_TOOLS if t["name"] == name), None)
    if tool is None or (tool["writes"] and not server["allow_writes"]):
        raise ValueError("unknown tool: {}{}".format(
            name, " (writing tools need `reqmap.py mcp --allow-writes`)"
            if tool is not None else ""))
    rc, text = server["run"](tool_argv(tool, args or {}), server["workspace"])
    content = [{"type": "text", "text": text or "(no output)"}]
    if rc != 0:
        content.append({"type": "text", "text": "exit code {}".format(rc)})
    return {"content": content, "isError": rc not in tool.get("ok", (0,))}


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _initialize_result():  # implements: REQ-MCPPROTOCOL-1027
    return {"protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False},
                             "resources": {"listChanged": False}},
            "serverInfo": {"name": "reqmap", "version": MAP_ENGINE_VERSION},
            "instructions": "Requirement manager for this repository. Start with "
                            "reqmap_gate for the verdict or reqmap_next for what to do; "
                            "reqmap_show and reqmap_search read one requirement, and each "
                            "requirement is also a resource, reqmap://requirement/<id>."}


MAP_URI = "reqmap://map"
REQUIREMENT_URI = "reqmap://requirement/"


def _map_path(workspace):  # implements: REQ-MCPRESOURCES-1030
    """`_map.json` in the requirements directory the server was started on."""
    flags = dict(zip(workspace[::2], workspace[1::2]))
    reqs = flags.get("--reqs") or os.path.join(flags["--root"], "requirements")
    return os.path.join(reqs, "_map.json")


def resource_list(server):  # implements: REQ-MCPRESOURCES-1030
    """The committed map, and one resource per requirement it names. Read from the map
    file, not the engine: a listing must not cost a full scan. No map, no resources."""
    try:
        with open(_map_path(server["workspace"]), encoding="utf-8") as f:
            nodes = json.load(f).get("nodes") or []
    except (OSError, ValueError, AttributeError):
        return []
    nodes = nodes.values() if isinstance(nodes, dict) else nodes
    out = [{"uri": MAP_URI, "name": "_map.json", "mimeType": "application/json",
            "description": "The requirement graph this repository commits: every "
                           "requirement, its members, dependencies and health."}]
    for n in nodes:
        if isinstance(n, dict) and n.get("id"):
            out.append({"uri": REQUIREMENT_URI + n["id"], "name": n["id"],
                        "title": n.get("title") or n["id"], "mimeType": "application/json"})
    return out


def resource_templates():  # implements: REQ-MCPRESOURCES-1030
    """The `resources/templates/list` entries: one requirement by id."""
    return [{"uriTemplate": REQUIREMENT_URI + "{id}", "name": "requirement",
             "mimeType": "application/json",
             "description": "One requirement's dossier with its frontmatter and body, as "
                            "`reqmap_show` returns it."}]


def read_resource(uri, server):  # implements: REQ-MCPRESOURCES-1030
    """`resources/read` contents, LookupError when the resource does not exist, or
    ValueError for a URI this server does not serve."""
    if uri == MAP_URI:
        try:
            with open(_map_path(server["workspace"]), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            raise LookupError("no committed map: run `reqmap.py sync`")
    elif isinstance(uri, str) and uri.startswith(REQUIREMENT_URI):
        rid = uri[len(REQUIREMENT_URI):]
        rc, text = server["run"](["gate", "--json", "--show", rid], server["workspace"])
        if rc != 0:
            raise LookupError("no requirement with id {}".format(rid))
    else:
        raise ValueError("unknown resource: {}".format(uri))
    return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}


def _call(params, server):
    return call_tool(params.get("name"), params.get("arguments"), server)


# method -> the result it answers with. A ValueError is invalid params (-32602), a
# LookupError a resource that does not exist (-32002, the protocol's resource-not-found).
_ROUTES = {
    "initialize": lambda params, server: _initialize_result(),
    "ping": lambda params, server: {},
    "tools/list": lambda params, server: {"tools": tool_list(server["allow_writes"])},
    "tools/call": _call,
    "resources/list": lambda params, server: {"resources": resource_list(server)},
    "resources/templates/list": lambda params, server: {
        "resourceTemplates": resource_templates()},
    "resources/read": lambda params, server: read_resource(params.get("uri"), server),
}


def handle(msg, server):  # implements: ARCH-MCP-073  # implements: REQ-MCPPROTOCOL-1027
    """One JSON-RPC message in, one response out; None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600,
                      "invalid request")
    if "id" not in msg:
        return None
    method, params, msg_id = msg["method"], msg.get("params") or {}, msg["id"]
    route = _ROUTES.get(method)
    if route is None:
        return _error(msg_id, -32601, "method not found: {}".format(method))
    try:
        return {"jsonrpc": "2.0", "id": msg_id, "result": route(params, server)}
    except LookupError as e:
        return _error(msg_id, -32002, str(e))
    except ValueError as e:
        return _error(msg_id, -32602, str(e))


def _workspace_flags(a, env=None):  # implements: REQ-MCPPROTOCOL-1027
    """The server's own --root/--reqs/--code/--cache, absolute, for every call it makes.
    A relative path resolves against `CLAUDE_PROJECT_DIR` when the client sets it: no
    client promises the server's working directory is the project."""
    base = (env if env is not None else os.environ).get("CLAUDE_PROJECT_DIR") or os.getcwd()
    at = lambda p: os.path.normpath(os.path.join(base, p))
    flags = ["--root", at(a.root)]
    for flag, value in (("--reqs", a.reqs), ("--code", a.code)):
        if value:
            flags += [flag, at(value)]
    return flags + (["--cache"] if a.cache else [])


def serve(a, stdin=None, stdout=None, run=run_tool):
    # implements: ARCH-MCP-073  # implements: REQ-MCPPROTOCOL-1027
    """Read newline-delimited JSON-RPC from stdin until it closes, answering on stdout.
    Nothing but protocol messages is written to stdout; diagnostics go to stderr."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    server = {"allow_writes": bool(getattr(a, "allow_writes", False)),
              "workspace": _workspace_flags(a), "run": run}
    for raw in stdin:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line), server)
        except json.JSONDecodeError:
            reply = _error(None, -32700, "parse error")
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
    return 0
