import typer
from rich.console import Console
from rich.panel import Panel

from delphi.db.repo import seed_database
from delphi.eval.run import run_evaluation
from delphi.rag.oracle import OracleService

app = typer.Typer(
    name="delphi",
    help="Дельфійський оракул — CLI для управління базою знань, інгестом та запитами",
)
console = Console()


@app.command()
def seed():
    """Initialize SQLite database and populate with initial seed data."""
    console.print("[bold yellow]Ініціалізація бази даних та сідування...[/bold yellow]")
    counts = seed_database()
    console.print(
        f"[bold green]Успішно додано:[/bold green] "
        f"{counts['entities']} сутностей, {counts['places']} місць, "
        f"{counts['relations']} зв'язків, {counts['myths']} міфів, "
        f"{counts['routes']} маршрутів, {counts['aliases']} аліасів."
    )


@app.command()
def ingest():
    """Download texts, chunk, tag entities, and build indexes."""
    console.print("[bold cyan]Запуск офлайн-інгесту корпусів...[/bold cyan]")
    console.print("[yellow]Етап офлайн-інгесту буде розгорнуто в Етапі 3.[/yellow]")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Питання до Дельфійського оракула"),
    style: str = typer.Option("піфія", "--style", "-s", help="Стиль: 'піфія' або 'науковий'"),
):
    """Ask the Oracle directly from the command line."""
    console.print(Panel(f"[bold cyan]Питання:[/bold cyan] {question} (стиль: {style})"))
    oracle = OracleService()
    ans = oracle.ask(question, style=style)

    console.print(Panel(ans.text, title="Відповідь Піфії", border_style="magenta"))

    if ans.citations:
        console.print("[bold]Джерела цитат:[/bold]")
        for c in ans.citations:
            console.print(f"  [{c.num}] {c.author}, {c.work} ({c.ref})")

    if ans.entities:
        console.print(f"[dim]Розпізнані сутності: {', '.join(ans.entities)}[/dim]")


@app.command()
def eval():
    """Run evaluation benchmarks against the golden set."""
    console.print("[bold blue]Запуск тестування на golden set...[/bold blue]")
    run_evaluation()


if __name__ == "__main__":
    app()
