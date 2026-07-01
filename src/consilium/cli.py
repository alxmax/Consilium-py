from __future__ import annotations
# implements: CPYBUS-CLI-001
# implements: CPYEXT-LTL-001

import json
import subprocess

import click

from consilium import deliberate
from consilium.errors import is_provider_error, provider_error_message
from consilium.explain import explain_module
from consilium.models import DEFAULT_MODEL as _DEFAULT_MODEL
from consilium.models import Report


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
@click.option("--rag", is_flag=True, default=False,
              help="Inject similar past runs as context (requires consilium-py[rag]).")
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
    """
    ctx_text = ""
    for path in context:
        with open(path, encoding="utf-8") as f:
            ctx_text += f"\n\n--- {path} ---\n" + f.read()

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
    if diff:
        result = subprocess.run(["git", "diff", diff], capture_output=True, text=True)
        proposal = f"Review this diff (git diff {diff})"
    else:
        result = subprocess.run(["git", "diff", "--staged"], capture_output=True, text=True)
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
