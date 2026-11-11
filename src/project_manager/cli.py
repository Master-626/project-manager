"""Command-line interface for persisted local tasks."""

from pathlib import Path

import click
from rich.cells import cell_len
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
    help="SQLite file (also PROJECT_MANAGER_DB). A leading ~ is expanded. Defaults to your user data directory.",
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
    message = Text(
        "Added task #{}: {} (priority: {})".format(task.id, task.title, task.priority)
    )
    _print_wide(
        message,
        cell_len(message.plain) + 1,
        no_wrap=True,
        overflow="ignore",
    )


def _print_wide(renderable, width, **print_options):
    """Print without the 80-column crop Rich uses for a dumb terminal.

    Setting only ``console.width`` is ignored when TERM is dumb unless the
    height is set as well. Restore both so later output keeps the real size.
    """
    saved = (console._width, console._height)
    console.size = (max(width, console.size.width), console.size.height)
    try:
        console.print(renderable, crop=False, **print_options)
    finally:
        console._width, console._height = saved


def _task_table_width(tasks):
    """Console width required to print every title without cropping."""
    id_w = max([cell_len("ID")] + [cell_len(str(task.id)) for task in tasks])
    title_w = max([cell_len("Title")] + [cell_len(task.title) for task in tasks])
    priority_w = max(
        [cell_len("Priority")] + [cell_len(task.priority) for task in tasks]
    )
    status_w = max(
        [cell_len("Status")]
        + [cell_len("Completed" if task.done else "Pending") for task in tasks]
    )
    # One space of padding on each side of every column, a border around them,
    # and slack so a legacy-Windows console width adjustment cannot crop a title.
    return id_w + title_w + priority_w + status_w + (2 * 4) + 5 + 2


def _print_task_table(tasks):
    table = Table(title="Tasks")
    table.add_column("ID", style="cyan", no_wrap=True, overflow="ignore")
    table.add_column("Title", style="green", no_wrap=True, overflow="ignore")
    table.add_column("Priority", no_wrap=True, overflow="ignore")
    table.add_column("Status", no_wrap=True, overflow="ignore")
    for task in tasks:
        table.add_row(
            str(task.id),
            Text(task.title),
            task.priority,
            "Completed" if task.done else "Pending",
        )
    _print_wide(table, _task_table_width(tasks))


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
    _print_task_table(tasks)


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


@main.command()
@click.argument("task_id", type=click.IntRange(1, MAX_TASK_ID))
@click.pass_obj
def delete(store, task_id):
    """Delete an existing task. Its ID is not reused."""
    try:
        task = store.delete(task_id)
    except (StorageError, TaskNotFound, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("Deleted task #{}".format(task.id))


if __name__ == "__main__":
    main()
