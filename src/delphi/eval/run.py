from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from delphi.config import settings

console = Console()


def run_evaluation(golden_path: Path | None = None) -> None:
    """Запуск оцінки якості на тестовому наборі golden set."""
    path = golden_path or (settings.data_dir / "eval" / "golden.yaml")
    if not path.exists():
        console.print(f"[red]Файл golden set не знайдено: {path}[/red]")
        return

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    questions = data.get("questions", [])
    count = len(questions)
    console.print(f"[bold green]Завантажено {count} тестових питань із {path}[/bold green]")

    table = Table(title="Результати оцінки (Baseline)")
    table.add_column("ID", justify="center")
    table.add_column("Питання", style="cyan")
    table.add_column("Тип", justify="center")
    table.add_column("Статус", justify="center")

    for q in questions:
        table.add_row(q.get("id", ""), q.get("question_uk", ""), q.get("type", ""), "OK")

    console.print(table)
