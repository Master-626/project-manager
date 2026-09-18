"""CLI interface."""
import click
from rich.console import Console
from rich.table import Table

console = Console()

@click.group()
@click.version_option(version="0.1.0")
def main():
    """Project Manager - Powerful project management CLI."""
    pass

@main.command()
@click.argument("title")
@click.option("--priority", "-p", default="medium", help="Task priority")
def add(title, priority):
    """Add a new task."""
    console.print(f"✅ Added task: [bold green]{title}[/bold green] (priority: {priority})")

@main.command()
def list():
    """List all tasks."""
    table = Table(title="Tasks")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Status")
    table.add_row("1", "Example task", "Pending")
    console.print(table)

@main.command()
@click.argument("task_id", type=int)
def done(task_id):
    """Mark task as done."""
    console.print(f"✅ Completed task #{task_id}")

if __name__ == "__main__":
    main()
