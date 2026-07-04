from __future__ import annotations
# implements: CPYBUS-CLI-001
# implements: CPYEXT-LTL-001

import fnmatch
import json
import os
import re
import subprocess
import sys

import click

from consilium import deliberate
from consilium.errors import is_provider_error, provider_error_message
from consilium.explain import explain_module
from consilium.models import DEFAULT_MODEL as _DEFAULT_MODEL
from consilium.models import Report


_FILE_PATH_RE = re.compile(r"[\w./\\-]+\.[a-zA-Z]{1,5}")

# Conservative fixed cap for assembled directory context. Not adaptive per
# model/provider — very large payloads may still hit provider- or
# claude-cli-specific limits (arg length / reload behavior).
MAX_CONTEXT_TOKENS = 50_000

# Never read these into a prompt, regardless of git-tracked status (defense in
# depth over git's exclude rules).
_SECRET_GLOBS = (
    ".env", ".env.*", "*.env", "*.env.*",
    "*.pem", "*.key", "*.p12", "*.crt",
    "*credentials*.json", "*service-account*.json",
    "id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*",
    ".netrc", ".npmrc", ".pypirc",
)

# Directories the non-git fallback walk never descends into.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def _detect_context_files(proposal: str) -> list[str]:
    """Find file paths mentioned in the proposal text that exist on disk."""
    seen: list[str] = []
    for match in _FILE_PATH_RE.findall(proposal):
        if os.path.isfile(match) and match not in seen:
            seen.append(match)
    return seen


def _is_secret_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, glob) for glob in _SECRET_GLOBS)


def _has_null_byte(path: str) -> bool:
    """Binary sniff: True if the first 8 KiB contains a NUL byte (or is unreadable)."""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return True


def _list_dir_files(path: str) -> list[str]:
    """Discover context files under a directory.

    Prefers `git ls-files` (tracked + untracked-but-not-ignored) so only
    version-controlled content is read; falls back to a filtered os.walk with a
    null-byte binary sniff for non-git targets. Secret/credential files are
    excluded from both paths.
    """
    files: list[str] = []
    result = None
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."],
            # encoding="utf-8": git emits UTF-8 pathnames; without it text=True
            # decodes via cp1252 on Windows and non-ASCII-named files mis-decode,
            # so os.path.isfile() below drops them silently from the context.
            cwd=path, capture_output=True, text=True, encoding="utf-8",
        )
    except OSError:
        result = None
    if result is not None and result.returncode == 0 and result.stdout:
        for rel in result.stdout.split("\0"):
            if not rel:
                continue
            full = os.path.join(path, rel)
            if os.path.isfile(full):
                files.append(full)
    else:
        for root, dirs, names in os.walk(path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.endswith(".egg-info")]
            for name in names:
                full = os.path.join(root, name)
                if not _has_null_byte(full):
                    files.append(full)

    files = [f for f in files if not _is_secret_file(os.path.basename(f))]
    return sorted(files)


def _read_directory(path: str) -> str:
    """Assemble a directory's text files into a single context blob, aborting
    (never truncating) once the estimated token count exceeds the fixed cap."""
    files = _list_dir_files(path)
    text = ""
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                text += f"\n\n--- {f} ---\n" + fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        # Stop reading once already over cap — a directory with a few huge
        # files shouldn't force reading every remaining one into memory first.
        if len(text) // 4 > MAX_CONTEXT_TOKENS:
            break

    estimated_tokens = len(text) // 4
    if estimated_tokens > MAX_CONTEXT_TOKENS:
        largest = sorted(files, key=lambda p: os.path.getsize(p), reverse=True)[:3]
        hint = "\n  Largest files: " + ", ".join(largest) if largest else ""
        raise click.ClickException(
            f"Directory context too large: {path} is ~{estimated_tokens} tokens "
            f"(cap {MAX_CONTEXT_TOKENS}).\n"
            "  Narrow scope by passing specific files with -c instead." + hint
        )
    return text


def _read_files(paths: list[str]) -> str:
    ctx_text = ""
    for path in paths:
        if os.path.isdir(path):
            # Directory context stays bounded: only git-tracked (or, for non-git
            # targets, non-binary walked) files, minus secrets, aborting past
            # MAX_CONTEXT_TOKENS. This extends "context = files you name" to "a
            # directory of files" — not codebase-wide scanning; `consilium
            # check` remains the separate diff-review path.
            ctx_text += _read_directory(path)
            continue
        if not os.path.isfile(path):
            raise click.ClickException(f"--context file not found: {path}")
        with open(path, encoding="utf-8") as f:
            ctx_text += f"\n\n--- {path} ---\n" + f.read()
    return ctx_text


_NO_CONTEXT_HINT = (
    "  No context provided — reasoning on proposal text alone.\n"
    "  Use --context <file> or 'consilium check' for a real diff."
)


def _resolve_context(proposal: str) -> str:
    """No --context flag given: try to detect files mentioned in the proposal
    and confirm with the user before using them as context; otherwise warn
    that the deliberation is running on the proposal text alone."""
    if not sys.stdin.isatty():
        click.echo(_NO_CONTEXT_HINT, err=True)
        return ""

    candidates = _detect_context_files(proposal)
    paths: list[str] = []
    if candidates:
        click.echo(f"  Detected file(s) in proposal: {', '.join(candidates)}")
        answer = click.prompt("  Use as context? [y/n/other path]", default="y").strip()
        answer_l = answer.lower()
        if answer_l in ("y", "yes"):
            paths = candidates
        elif answer_l in ("n", "no"):
            paths = []
        else:
            paths = [p for p in re.split(r"[,\s]+", answer) if os.path.isfile(p)]
            if not paths:
                click.echo(f"  '{answer}' is not a valid file — proceeding without context.", err=True)

    if paths:
        return _read_files(paths)

    click.echo(_NO_CONTEXT_HINT, err=True)
    return ""


def _deliberate_or_exit(proposal: str, **kwargs) -> Report:
    try:
        return deliberate(proposal, **kwargs)
    except Exception as e:  # noqa: BLE001
        if not is_provider_error(e):
            raise
        raise click.ClickException(provider_error_message(e, kwargs.get("model"))) from None


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Consilium — AI deliberation for code changes.

    \b
    Quick start (no API key needed):
      consilium serve                       start the web UI
      consilium deliberate "your proposal"  deliberate in the terminal
      consilium check                       review staged git changes
      consilium explain src/               explain a codebase

    \b
    Set CONSILIUM_MODEL=claude-cli to use your local Claude subscription.
    Set CONSILIUM_MODEL=openrouter/... or any provider/model for API access.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# implements: CPYSRV-SERVE-001
@main.command("serve")
@click.option("--port", default=8124, help="Port to listen on (tries next free port if busy).")
@click.option("--host", default="127.0.0.1", hidden=True)
@click.option("--model", default=_DEFAULT_MODEL, envvar="CONSILIUM_MODEL",
              help="Model to use. Default: CONSILIUM_MODEL env var.")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically.")
def serve_cmd(port: int, host: str, model: str, no_browser: bool) -> None:
    """Start the web UI server.

    \b
    Examples:
      consilium serve
      consilium serve --port 9000
      CONSILIUM_MODEL=claude-cli consilium serve
    """
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        raise click.ClickException(
            "The server requires the [server] extra.\n"
            "Run: pip install 'consilium-py[server]'"
        )

    import os
    import socket
    import threading
    import webbrowser

    os.environ["CONSILIUM_MODEL"] = model

    # Find a free port if the requested one is busy.
    def _is_free(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, p)) != 0

    while not _is_free(port):
        click.echo(f"  Port {port} busy — trying {port + 1}…")
        port += 1

    url = f"http://{host}:{port}"
    click.echo(f"\n  Consilium  →  {url}\n  Model: {model}\n  Press Ctrl+C to stop.\n")

    if not no_browser:
        def _open() -> None:
            import time
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run("consilium.server:app", host=host, port=port, log_level="warning")


@main.command("deliberate")
@click.argument("proposal")
@click.option("--context", "-c", multiple=True, help="Context files (path).")
@click.option("--mode", default="sequential",
              type=click.Choice(["sequential", "dialectic", "trias", "langgraph"]),
              help="Deliberation mode.")
@click.option("--model", default=_DEFAULT_MODEL, envvar="CONSILIUM_MODEL",
              help="Model string. Use 'provider/model' for LiteLLM.")
@click.option("--skeptic-can-override", is_flag=True, default=False,
              help="Allow Skeptic to downgrade verdict (dialectic only).")
@click.option("--rag/--no-rag", default=False, envvar="CONSILIUM_RAG",
              help="Inject similar past runs + ingested docs as context "
                   "(requires consilium-py[rag]). Default from CONSILIUM_RAG env "
                   "var; --no-rag forces it off even when the env var is set.")
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def deliberate_cmd(
    proposal: str,
    context: tuple[str, ...],
    mode: str,
    model: str,
    skeptic_can_override: bool,
    rag: bool,
    output: str,
) -> None:
    """Deliberate a proposed change.

    \b
    Examples:
      consilium deliberate "Add a /health endpoint"
      consilium deliberate "Refactor auth" --mode dialectic
      consilium deliberate "Add caching" -c api.py -c models.py
      consilium deliberate "Review module" -c src/consilium/

    \b
    A directory passed to -c assembles its git-tracked text files into the
    prompt (experimental; no guarantee the voices find real bugs — use a
    linter/static analyzer for that). Aborts past a conservative ~50k-token
    cap rather than truncating.
    """
    ctx_text = _read_files(list(context)) if context else _resolve_context(proposal)

    report = _deliberate_or_exit(
        proposal,
        context=ctx_text,
        mode=mode,
        model=model,
        skeptic_can_override=skeptic_can_override,
        rag=rag,
    )
    _print_report(report, output)


@main.command("check")
@click.option("--diff", default=None,
              help="Git ref to diff against (e.g. HEAD~1, main). Omit for staged changes.")
@click.option("--mode", default="sequential",
              type=click.Choice(["sequential", "dialectic", "trias", "langgraph"]))
@click.option("--model", default=_DEFAULT_MODEL, envvar="CONSILIUM_MODEL")
@click.option("--skeptic-can-override", is_flag=True, default=False)
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def check_cmd(
    diff: str | None,
    mode: str,
    model: str,
    skeptic_can_override: bool,
    output: str,
) -> None:
    """Deliberate on a git diff.

    \b
    Examples:
      consilium check                  review staged changes
      consilium check --diff HEAD~1    review last commit
      consilium check --diff main      review branch vs main
    """
    # encoding="utf-8": the diff content becomes the deliberation context the
    # voices read; without it text=True mangles non-ASCII via cp1252 on Windows.
    # errors="replace" keeps the CLI from crashing on a non-UTF-8 source byte
    # (cp1252 never raised, so strict utf-8 would be a regression).
    if diff:
        result = subprocess.run(["git", "diff", diff], capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        proposal = f"Review this diff (git diff {diff})"
    else:
        result = subprocess.run(["git", "diff", "--staged"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        proposal = "Review staged changes"

    if result.returncode != 0:
        raise click.ClickException(result.stderr.strip())

    context = result.stdout
    if not context.strip():
        raise click.ClickException(
            "No diff found.\n"
            "  Stage changes with: git add <files>\n"
            "  Or specify a ref:   consilium check --diff HEAD~1"
        )

    report = _deliberate_or_exit(
        proposal, context=context, mode=mode, model=model,
        skeptic_can_override=skeptic_can_override,
    )
    _print_report(report, output)


# implements: CPYBUS-EXPLAIN-001
@main.command("explain")
@click.argument("path")
@click.option("--model", default=_DEFAULT_MODEL, envvar="CONSILIUM_MODEL")
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def explain_cmd(path: str, model: str, output: str) -> None:
    """Explain the Python code at PATH (file or directory).

    \b
    Examples:
      consilium explain src/consilium/voices.py
      consilium explain src/consilium/ --output json
    """
    try:
        report = explain_module(path, model)
    except Exception as e:  # noqa: BLE001
        if not is_provider_error(e):
            raise
        raise click.ClickException(str(e)) from None

    if output == "json":
        click.echo(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        return

    click.echo(f"\n{report.summary}")
    if report.public_api:
        click.echo("\nPublic API:")
        for item in report.public_api:
            click.echo(f"  {item}")
    if report.dependencies:
        click.echo("\nDependencies:")
        for item in report.dependencies:
            click.echo(f"  {item}")
    if report.data_flow:
        click.echo(f"\nData flow:\n  {report.data_flow}")
    if report.gotchas:
        click.echo("\nGotchas:")
        for item in report.gotchas:
            click.echo(f"  ! {item}")


@main.command("index")
def index_cmd() -> None:
    """Index past runs into the RAG vector store (requires consilium-py[rag])."""
    try:
        from consilium.rag import index_all_runs  # noqa: PLC0415
    except ImportError as e:
        raise click.ClickException(str(e))
    count = index_all_runs()
    click.echo(f"Indexed {count} run(s) into ~/.consilium/chroma/")


# implements: CPYEXT-DOCRAG-001
@main.command("ingest")
@click.argument("path")
def ingest_cmd(path: str) -> None:
    """Chunk and index a document or directory for RAG retrieval (requires consilium-py[rag]).

    \b
    Examples:
      consilium ingest README.md
      consilium ingest docs/
    """
    try:
        from consilium.rag import ingest_path  # noqa: PLC0415
    except ImportError as e:
        raise click.ClickException(str(e))
    try:
        count = ingest_path(path)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))
    click.echo(f"Indexed {count} chunk(s) from {path} into ~/.consilium/chroma/")


def _print_report(report: Report, output: str) -> None:
    if output == "json":
        click.echo(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        return
    if report.verdict == "ANSWER":
        click.echo(f"\n{report.recommendation}")
        return

    _VERDICT_COLOR = {"GO": "green", "MODIFY": "yellow", "STOP": "red", "BLOCK": "red"}
    color = _VERDICT_COLOR.get(report.verdict, "white")
    click.echo("")
    click.echo(click.style(f"  {report.verdict}", fg=color, bold=True) +
               f"  confidence {report.confidence:.0%}  mode {report.mode}")
    click.echo(f"\n  {report.recommendation}")

    if report.verdict in ("GO", "MODIFY") and report.chosen_sketch:
        click.echo(f"\n  How to implement ({report.chosen}):")
        if report.chosen_summary:
            click.echo(f"    {report.chosen_summary}")
        click.echo(f"    {report.chosen_sketch}")
        if report.chosen_rationale:
            click.echo(f"    Why: {report.chosen_rationale}")

    if report.skeptic and report.skeptic.can_object:
        click.echo(f"\n  Skeptic ({report.skeptic.addressable}): {report.skeptic.failure_mode}")
        for c in report.skeptic.concrete_concerns:
            click.echo(f"    - {c}")


if __name__ == "__main__":
    main()
