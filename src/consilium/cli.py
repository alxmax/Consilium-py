import json

import click

from consilium import deliberate


@click.group()
def main() -> None:
    pass


@main.command("deliberate")
@click.argument("proposal")
@click.option("--context", "-c", multiple=True, help="Context files (path)")
@click.option("--mode", default="sequential", help="sequential (default)")
@click.option("--model", default="claude-sonnet-4-6")
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def deliberate_cmd(
    proposal: str,
    context: tuple[str, ...],
    mode: str,
    model: str,
    output: str,
) -> None:
    """Deliberate a proposed change."""
    ctx_text = ""
    for path in context:
        ctx_text += f"\n\n--- {path} ---\n" + open(path).read()

    report = deliberate(proposal, context=ctx_text, mode=mode, model=model)

    if output == "json":
        click.echo(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
    else:
        click.echo(f"\nVerdict:    {report.verdict}")
        click.echo(f"Confidence: {report.confidence:.2f}")
        click.echo(f"\n{report.recommendation}")
