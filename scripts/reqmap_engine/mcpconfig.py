"""The client configuration that starts `reqmap.py mcp`, written by `init` (ADR-0043).

Two files, one per client family: `.mcp.json` for Claude Code and `.vscode/mcp.json` for
VS Code with GitHub Copilot. Neither guarantees the server's working directory, so every
path is written against the variable each client expands to the project root.
"""
# implements: ARCH-MCP-073
import json, os

from . import ENGINE_DIR

# (path, top-level key, the variable the client expands to the project root)
MCP_CONFIGS = (
    (".mcp.json", "mcpServers", "${CLAUDE_PROJECT_DIR:-.}"),
    (".vscode/mcp.json", "servers", "${workspaceFolder}"),
)
SERVER_NAME = "reqmap"


def server_entry(code_root, reqs_dir, base, python=None):
    # implements: REQ-MCPSEED-1029
    """The stdio server entry for one client, or None when the engine is not inside the
    repository: a committed config cannot start an engine a clone does not contain."""
    root = os.path.abspath(code_root)
    try:
        rel_engine = os.path.relpath(os.path.join(ENGINE_DIR, "reqmap.py"), root)
        rel_reqs = os.path.relpath(os.path.abspath(reqs_dir), root)
    except ValueError:          # Windows: another drive has no relative form
        return None
    if rel_engine.startswith(".."):
        return None
    under = lambda rel: base + "/" + rel.replace(os.sep, "/")
    return {"type": "stdio",
            "command": python or ("python" if os.name == "nt" else "python3"),
            "args": [under(rel_engine), "mcp", "--root", base,
                     "--reqs", under(rel_reqs), "--code", base]}


def seed_mcp_files(code_root, reqs_dir):  # implements: REQ-MCPSEED-1029
    """Write each client's config when the file does not exist; never edit one that does.
    Returns (created, notes)."""
    created, notes = [], []
    for rel, key, base in MCP_CONFIGS:
        path = os.path.join(code_root, *rel.split("/"))
        if os.path.exists(path):
            if SERVER_NAME not in _servers(path, key):
                notes.append("{} exists and has no `{}` server; add one by hand to use "
                             "`reqmap.py mcp` from that client.".format(rel, SERVER_NAME))
            continue
        entry = server_entry(code_root, reqs_dir, base)
        if entry is None:
            notes.append("no MCP config: the engine is not inside this repository. Vendor it "
                         "under scripts/ and re-run init.")
            return created, notes
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({key: {SERVER_NAME: entry}}, indent=2) + "\n")
        created.append(rel)
    return created, notes


def _servers(path, key):
    """The server names an existing config declares; empty when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    servers = data.get(key) if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}
