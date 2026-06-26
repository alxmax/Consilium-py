from __future__ import annotations
# implements: CPYBUS-CLI-001
# implements: CPYEXT-LTL-001

import json
import subprocess

import click

from consilium import deliberate
from consilium.explain import explain_module
from consilium.models import Report


def _is_provider_error(e: BaseException) -> bool:
    """True for a transient LLM-provider failure (litellm/openai/anthropic) — a
    503, rate limit, timeout — as opposed to a real bug, which we must not mask."""
    root = (type(e).__module__ or "").split(".")[0]
    if root in ("litellm", "openai"):
        return True
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return False
    return isinstance(e, anthropic.APIError)


def _deliberate_or_exit(proposal: str, **kwargs) -> Report:
    """Call `deliberate()`, turning a provider outage into a clean CLI message
    instead of a raw traceback. Non-provider exceptions propagate unchanged."""
    try:
        return deliberate(proposal, **kwargs)
    except Exception as e:  # noqa: BLE001
        if not _is_provider_error(e):
            raise
        status = getattr(e, "status_code", None)
        model = kwargs.get("model") or "the configured model"
        # A 404 (model retired/unknown) or 401/403 (auth) is PERMANENT — telling the
        # user to "re-run shortly" sends them into an infinite retry on a dead model.
        # Only 429 / 5xx / connection errors (no status) are genuinely transient.
        if status in (401, 403, 404):
            kind = "not found or retired" if status == 404 else "rejected (auth / permission)"
            raise click.ClickException(
                f"Model {model!r} {kind} (HTTP {status}) — this is NOT transient. "
                "Pick a current model (unset CONSILIUM_MODEL for the default, or pass "
                "--model, e.g. gemini/gemini-2.5-flash) and check the matching API key."
            ) from None
        detail = f" (HTTP {status})" if status else ""
        raise click.ClickException(
            f"Model provider unavailable{detail} — usually transient (rate limit / "
            "high demand). Re-run shortly, or switch model: unset CONSILIUM_MODEL "
            "for the default, or use an Anthropic model."
        ) from None


@click.group()
def main() -> None:
    pass


@main.command("deliberate")
@click.argument("proposal")
@click.option("--context", "-c", multiple=True, help="Context files (path)")
@click.option("--mode", default="sequential", type=click.Choice(["sequential", "dialectic", "trias", "langgraph"]))
@click.option("--model", default="openrouter/google/gemini-2.0-flash-001", envvar="CONSILIUM_MODEL", help="Model string. Use 'provider/model' for LiteLLM (e.g. openrouter/google/gemini-2.0-flash-001).")
@click.option("--skeptic-can-override", is_flag=True, default=False, help="Allow Skeptic to downgrade verdict (dialectic only)")
@click.option("--rag", is_flag=True, default=False, help="Inject similar past runs as context (requires consilium-py[rag])")
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
    """Deliberate a proposed change."""
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


@main.command("index")
def index_cmd() -> None:
    """Index all past runs in ~/.consilium/runs/ into the RAG vector store."""
    try:
        from consilium.rag import index_all_runs  # noqa: PLC0415
    except ImportError as e:
        raise click.ClickException(str(e))
    count = index_all_runs()
    click.echo(f"Indexed {count} run(s) into ~/.consilium/chroma/")


@main.command("check")
@click.option("--diff", default=None, help="Git ref for diff (e.g. HEAD~1, main). Omit for staged changes.")
@click.option("--mode", default="sequential", type=click.Choice(["sequential", "dialectic", "trias", "langgraph"]))
@click.option("--model", default="openrouter/google/gemini-2.0-flash-001", envvar="CONSILIUM_MODEL", help="Model string. Use 'provider/model' for LiteLLM (e.g. openrouter/google/gemini-2.0-flash-001).")
@click.option("--skeptic-can-override", is_flag=True, default=False)
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def check_cmd(
    diff: str | None,
    mode: str,
    model: str,
    skeptic_can_override: bool,
    output: str,
) -> None:
    """Deliberate on a git diff."""
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
        raise click.ClickException("No diff found. Use --diff HEAD~1 or stage some changes.")

    report = _deliberate_or_exit(
        proposal,
        context=context,
        mode=mode,
        model=model,
        skeptic_can_override=skeptic_can_override,
    )
    _print_report(report, output)


def _print_report(report: Report, output: str) -> None:
    if output == "json":
        click.echo(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        return
    # A non-deliberation input (greeting/chit-chat) is answered directly —
    # print only the reply, with no verdict/confidence header.
    if report.verdict == "ANSWER":
        click.echo(f"\n{report.recommendation}")
        return
    click.echo(f"\nVerdict:    {report.verdict}")
    click.echo(f"Confidence: {report.confidence:.2f}")
    click.echo(f"Mode:       {report.mode}")
    click.echo(f"\n{report.recommendation}")
    # "How to implement" — only for actionable verdicts; a STOP/BLOCK
    # carries no chosen approach worth sketching.
    if report.verdict in ("GO", "MODIFY") and report.chosen_sketch:
        click.echo(f"\nHow to implement ({report.chosen}):")
        if report.chosen_summary:
            click.echo(f"  {report.chosen_summary}")
        click.echo(f"  {report.chosen_sketch}")
        if report.chosen_rationale:
            click.echo(f"  Why: {report.chosen_rationale}")
    if report.skeptic and report.skeptic.can_object:
        click.echo(f"\nSkeptic ({report.skeptic.addressable}): {report.skeptic.failure_mode}")
        for c in report.skeptic.concrete_concerns:
            click.echo(f"  - {c}")


@main.command("explain")
@click.argument("path")
@click.option("--model", default="openrouter/google/gemini-2.0-flash-001", envvar="CONSILIUM_MODEL")
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def explain_cmd(path: str, model: str, output: str) -> None:
    """Explain the Python code at PATH (file or directory)."""
    try:
        report = explain_module(path, model)
    except Exception as e:  # noqa: BLE001
        if not _is_provider_error(e):
            raise
        raise click.ClickException(str(e)) from None

    if output == "json":
        import json as _json
        click.echo(_json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
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


if __name__ == "__main__":  # enables `python -m consilium.cli ...`
    main()
