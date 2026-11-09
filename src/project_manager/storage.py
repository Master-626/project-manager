"""Transactional, local SQLite task storage. No sample or fallback data."""

import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import click

from .models.task import Task

APPLICATION_ID = 0x50524A4D  # PRJM
SCHEMA_VERSION = 1
PRIORITIES = ("low", "medium", "high", "urgent")
MAX_TASK_ID = 2**63 - 1
SCHEMA_SQL = """
CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    priority TEXT NOT NULL CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
                    done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0, 1)),
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    CHECK((done = 0 AND completed_at IS NULL) OR
                          (done = 1 AND completed_at IS NOT NULL))
                )
"""


class StorageError(Exception):
    """The store could not safely complete an operation."""


class TaskNotFound(Exception):
    """The requested task does not exist."""


def default_database() -> Path:
    """Use the platform's per-user data directory, never the working tree."""
    return Path(click.get_app_dir("project-manager")) / "tasks.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_title(title: str) -> bool:
    return (
        isinstance(title, str)
        and bool(title.strip())
        and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in title)
    )


def _valid_timestamp(value: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _task(row: sqlite3.Row) -> Task:
    if (
        row is None
        or not isinstance(row["id"], int)
        or not 1 <= row["id"] <= MAX_TASK_ID
        or not _valid_title(row["title"])
        or row["priority"] not in PRIORITIES
        or type(row["done"]) is not int
        or row["done"] not in (0, 1)
        or not _valid_timestamp(row["created_at"])
        or (row["done"] == 0 and row["completed_at"] is not None)
        or (row["done"] == 1 and not _valid_timestamp(row["completed_at"]))
    ):
        raise StorageError(
            "Invalid saved task data; existing data was not reset. Restore a backup."
        )
    return Task(
        id=row["id"],
        title=row["title"],
        priority=row["priority"],
        done=bool(row["done"]),
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


class TaskStore:
    def __init__(self, database: Optional[Path] = None, timeout: float = 5.0):
        self.path = Path(database) if database is not None else default_database()
        self.timeout = timeout

    @contextmanager
    def _connection(
        self, write: bool = False, create: bool = False
    ) -> Iterator[sqlite3.Connection]:
        connection = None
        try:
            try:
                file_mode = self.path.stat().st_mode
            except FileNotFoundError:
                if self.path.is_symlink():
                    raise StorageError(
                        "Database path is a dangling symbolic link: '{}'".format(
                            self.path
                        )
                    )
            else:
                if not stat.S_ISREG(file_mode):
                    raise StorageError(
                        "Database path must be a regular file: '{}'".format(self.path)
                    )
            if create:
                self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            mode = "rwc" if create else "rw" if write else "ro"
            # A URI forces literal filenames such as ':memory:' and escapes ?/#.
            uri = self.path.absolute().as_uri() + "?mode=" + mode
            connection = sqlite3.connect(uri, uri=True, timeout=self.timeout)
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            self._schema(connection, create=create)
            yield connection
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(
                "Cannot access task database '{}': {}".format(self.path, exc)
            ) from exc
        finally:
            if connection is not None:
                connection.close()  # Rolls back an uncommitted transaction on failure.

    def _schema(self, connection: sqlite3.Connection, create: bool) -> None:
        app_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        objects = connection.execute(
            "SELECT name, type FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
        ).fetchall()
        if app_id == 0 and version == 0 and not objects and create:
            connection.execute(SCHEMA_SQL)
            connection.execute("PRAGMA application_id = {}".format(APPLICATION_ID))
            connection.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
            return
        if app_id != APPLICATION_ID or version != SCHEMA_VERSION:
            raise StorageError(
                "Unsupported task database '{}'. Expected project-manager schema {}; "
                "existing data was not reset. Choose another --database file or restore a backup.".format(
                    self.path, SCHEMA_VERSION
                )
            )
        expected = [
            ("id", "INTEGER", 0, 1),
            ("title", "TEXT", 1, 0),
            ("priority", "TEXT", 1, 0),
            ("done", "INTEGER", 1, 0),
            ("created_at", "TEXT", 1, 0),
            ("completed_at", "TEXT", 0, 0),
        ]
        columns = [
            (r[1], r[2], r[3], r[5])
            for r in connection.execute("PRAGMA table_info(tasks)")
        ]
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if (
            columns != expected
            or [(r[0], r[1]) for r in objects] != [("tasks", "table")]
            or table_sql is None
            or " ".join(table_sql[0].split()) != " ".join(SCHEMA_SQL.split())
        ):
            raise StorageError(
                "Invalid task schema in '{}'; existing data was not reset.".format(
                    self.path
                )
            )

    def add(self, title: str, priority: str = "medium") -> Task:
        if not _valid_title(title):
            raise ValueError(
                "Task title must be nonblank and must not contain control characters."
            )
        title = title.strip()
        if priority not in PRIORITIES:
            raise ValueError(
                "Priority must be one of: {}.".format(", ".join(PRIORITIES))
            )
        with self._connection(write=True, create=True) as connection:
            created_at = _now()
            cursor = connection.execute(
                "INSERT INTO tasks (title, priority, created_at) VALUES (?, ?, ?)",
                (title, priority, created_at),
            )
            task = _task(
                connection.execute(
                    "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            )
            if cursor.rowcount != 1 or (
                task.title,
                task.priority,
                task.created_at,
                task.done,
            ) != (title, priority, created_at, False):
                raise StorageError("Task insertion did not persist the requested data.")
        return task  # Only return success after commit.

    def list_tasks(self) -> List[Task]:
        # Missing stores are empty. Existing but inaccessible/corrupt stores are errors.
        try:
            self.path.lstat()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise StorageError(
                "Cannot access task database '{}': {}".format(self.path, exc)
            ) from exc
        with self._connection() as connection:
            return [
                _task(row)
                for row in connection.execute("SELECT * FROM tasks ORDER BY id")
            ]

    def complete(self, task_id: int) -> Tuple[Task, bool]:
        if (
            isinstance(task_id, bool)
            or not isinstance(task_id, int)
            or not 1 <= task_id <= MAX_TASK_ID
        ):
            raise ValueError(
                "Task ID must be an integer between 1 and {}.".format(MAX_TASK_ID)
            )
        try:
            self.path.lstat()
        except FileNotFoundError:
            raise TaskNotFound("Task #{} does not exist.".format(task_id))
        except OSError as exc:
            raise StorageError(
                "Cannot access task database '{}': {}".format(self.path, exc)
            ) from exc
        with self._connection(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise TaskNotFound("Task #{} does not exist.".format(task_id))
            original = _task(row)
            changed = not original.done
            if changed:
                completed_at = _now()
                cursor = connection.execute(
                    "UPDATE tasks SET done = 1, completed_at = ? WHERE id = ?",
                    (completed_at, task_id),
                )
                row = connection.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
            task = _task(row)
            if changed and (
                cursor.rowcount != 1
                or not task.done
                or task.completed_at != completed_at
                or (task.title, task.priority, task.created_at)
                != (original.title, original.priority, original.created_at)
            ):
                raise StorageError(
                    "Task completion did not persist the requested data."
                )
        return task, changed
