"""Command-line interface for persisted local tasks."""

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__
from .storage import MAX_TASK_ID, PRIORITIES, StorageError, TaskNotFound, TaskStore

console = Console()


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    envvar="PROJECT_MANAGER_DB",
    help="SQLite file (also PROJECT_MANAGER_DB). Defaults to your user data directory.",
)
@click.pass_context
def main(ctx, database):
    """Project Manager - Manage tasks stored locally between runs."""
    ctx.obj = TaskStore(database)


@main.command()
@click.argument("title")
@click.option(
    "--priority",
    "-p",
    type=click.Choice(PRIORITIES),
    default="medium",
    show_default=True,
)
@click.pass_obj
def add(store, title, priority):
    """Save a new task and print its ID."""
    try:
        task = store.add(title, priority)
    except (StorageError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        Text(
            "Added task #{}: {} (priority: {})".format(
                task.id, task.title, task.priority
            )
        )
    )


@main.command(name="list")
@click.pass_obj
def list_tasks(store):
    """List all saved tasks, including completed tasks."""
    try:
        tasks = store.list_tasks()
    except StorageError as exc:
        raise click.ClickException(str(exc)) from exc
    if not tasks:
        console.print('No tasks yet. Add one with: project-manager add "Task title"')
        return
    table = Table(title="Tasks")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Priority")
    table.add_column("Status")
    for task in tasks:
        table.add_row(
            str(task.id),
            Text(task.title),
            task.priority,
            "Completed" if task.done else "Pending",
        )
    console.print(table)


@main.command()
@click.argument("task_id", type=click.IntRange(1, MAX_TASK_ID))
@click.pass_obj
def done(store, task_id):
    """Persist completion of an existing task. Repeating is harmless."""
    try:
        task, changed = store.complete(task_id)
    except (StorageError, TaskNotFound, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if changed:
        console.print("Completed task #{}".format(task.id))
    else:
        console.print("Task #{} is already completed.".format(task.id))


if __name__ == "__main__":
    main()
