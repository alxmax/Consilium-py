from __future__ import annotations

import json
import subprocess

import click

from consilium import deliberate
from consilium.models import Report


@click.group()
def main() -> None:
    pass


@main.command("deliberate")
@click.argument("proposal")
@click.option("--context", "-c", multiple=True, help="Context files (path)")
@click.option("--mode", default="sequential", type=click.Choice(["sequential", "dialectic"]))
@click.option("--model", default="claude-sonnet-4-6")
@click.option("--skeptic-can-override", is_flag=True, default=False, help="Allow Skeptic to downgrade verdict (dialectic only)")
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def deliberate_cmd(
    proposal: str,
    context: tuple[str, ...],
    mode: str,
    model: str,
    skeptic_can_override: bool,
    output: str,
) -> None:
    """Deliberate a proposed change."""
    ctx_text = ""
    for path in context:
        ctx_text += f"\n\n--- {path} ---\n" + open(path).read()

    report = deliberate(
        proposal,
        context=ctx_text,
        mode=mode,
        model=model,
        skeptic_can_override=skeptic_can_override,
    )
    _print_report(report, output)


@main.command("check")
@click.option("--diff", default=None, help="Git ref for diff (e.g. HEAD~1, main). Omit for staged changes.")
@click.option("--mode", default="sequential", type=click.Choice(["sequential", "dialectic"]))
@click.option("--model", default="claude-sonnet-4-6")
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

    report = deliberate(
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
    else:
        click.echo(f"\nVerdict:    {report.verdict}")
        click.echo(f"Confidence: {report.confidence:.2f}")
        click.echo(f"Mode:       {report.mode}")
        click.echo(f"\n{report.recommendation}")
        if report.skeptic and report.skeptic.can_object:
            click.echo(f"\nSkeptic ({report.skeptic.addressable}): {report.skeptic.failure_mode}")
            for c in report.skeptic.concrete_concerns:
                click.echo(f"  - {c}")
