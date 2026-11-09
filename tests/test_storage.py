import os
import sqlite3
from datetime import datetime

import pytest

from project_manager.storage import (
    APPLICATION_ID,
    MAX_TASK_ID,
    StorageError,
    TaskNotFound,
    TaskStore,
)


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "nested" / "tasks.sqlite3")


def test_empty_store_does_not_create_file(store):
    assert store.list_tasks() == []
    assert not store.path.parent.exists()
    with pytest.raises(TaskNotFound):
        store.complete(1)
    assert not store.path.parent.exists()


def test_add_list_and_complete_reopen(store):
    first = store.add("  Finish 中文 📚  ", "urgent")
    second = TaskStore(store.path).add("second")
    assert first.id == 1 and second.id == 2
    assert first.title == "Finish 中文 📚"
    assert first.priority == "urgent" and not first.done
    assert first.completed_at is None
    assert datetime.fromisoformat(first.created_at).utcoffset().total_seconds() == 0
    completed, changed = TaskStore(store.path).complete(first.id)
    assert changed and completed.done and completed.completed_at
    assert completed.created_at == first.created_at
    again, changed = TaskStore(store.path).complete(first.id)
    assert not changed and again.completed_at == completed.completed_at
    assert TaskStore(store.path).list_tasks() == [completed, second]


@pytest.mark.parametrize("priority", ["low", "medium", "high", "urgent"])
def test_priorities(store, priority):
    assert store.add("x", priority).priority == priority


@pytest.mark.parametrize(
    "title",
    ["", "   ", "\n\t", "has\x00null", "x\x1b[31m", "x\nnext", "x\x7f", "x\x85"],
)
def test_invalid_titles_make_no_database(store, title):
    with pytest.raises(ValueError):
        store.add(title)
    assert not store.path.exists()


def test_invalid_priority_makes_no_database(store):
    with pytest.raises(ValueError):
        store.add("x", "super")
    assert not store.path.exists()


@pytest.mark.parametrize("task_id", [0, -1, MAX_TASK_ID + 1, True, "1", 1.5])
def test_invalid_id(store, task_id):
    with pytest.raises(ValueError):
        store.complete(task_id)
    assert not store.path.exists()


def test_missing_id_does_not_modify_store(store):
    store.add("one")
    before = store.path.read_bytes()
    with pytest.raises(TaskNotFound):
        store.complete(2)
    assert store.path.read_bytes() == before


def test_corrupt_database_is_preserved(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    original = b"not a database: irreplaceable user data"
    path.write_bytes(original)
    store = TaskStore(path)
    for action in (store.list_tasks, lambda: store.add("x"), lambda: store.complete(1)):
        with pytest.raises(StorageError):
            action()
        assert path.read_bytes() == original


@pytest.mark.parametrize("case", ["unrelated", "future", "wrong-schema"])
def test_unsupported_store_is_preserved(tmp_path, case):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(str(path)) as con:
        con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, secret TEXT)")
        con.execute("INSERT INTO tasks VALUES (1, 'keep me')")
        if case != "unrelated":
            con.execute("PRAGMA application_id={}".format(APPLICATION_ID))
            con.execute("PRAGMA user_version={}".format(99 if case == "future" else 1))
    before = path.read_bytes()
    store = TaskStore(path)
    for action in (store.list_tasks, lambda: store.add("x"), lambda: store.complete(1)):
        with pytest.raises(StorageError):
            action()
        assert path.read_bytes() == before


def test_directory_path_error(tmp_path):
    with pytest.raises(StorageError):
        TaskStore(tmp_path).add("x")


def test_parent_is_file(tmp_path):
    parent = tmp_path / "file"
    parent.write_text("keep")
    with pytest.raises(StorageError):
        TaskStore(parent / "db").add("x")
    assert parent.read_text() == "keep"


def test_locked_database_rolls_back(store):
    store.add("first")
    locked_store = TaskStore(store.path, timeout=0.01)
    con = sqlite3.connect(str(store.path))
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("UPDATE tasks SET title = 'uncommitted'")
        with pytest.raises(StorageError, match="locked"):
            locked_store.add("second")
    finally:
        con.rollback()
        con.close()
    assert [t.title for t in store.list_tasks()] == ["first"]


def test_abort_trigger_rolls_back(store):
    store.add("first")
    with sqlite3.connect(str(store.path)) as con:
        con.execute(
            "CREATE TRIGGER fail BEFORE INSERT ON tasks BEGIN SELECT RAISE(ABORT, 'disk error'); END"
        )
    before = store.path.read_bytes()
    with pytest.raises(StorageError):
        store.add("second")
    assert store.path.read_bytes() == before


def test_filename_with_uri_characters(tmp_path):
    path = tmp_path / ("literal#.sqlite3" if os.name == "nt" else "literal?#.sqlite3")
    store = TaskStore(path)
    store.add("title '); DROP TABLE tasks; --")
    assert path.is_file()
    assert len(TaskStore(path).list_tasks()) == 1


def test_default_path_uses_app_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "project_manager.storage.click.get_app_dir", lambda _: str(tmp_path)
    )
    assert TaskStore().path == tmp_path / "tasks.sqlite3"


@pytest.mark.parametrize("name", ["guard", "sqliteXguard"])
@pytest.mark.parametrize(
    "body",
    [
        "BEFORE INSERT ON tasks BEGIN SELECT RAISE(IGNORE); END",
        "AFTER INSERT ON tasks BEGIN DELETE FROM tasks WHERE id=NEW.id; END",
        "BEFORE UPDATE ON tasks BEGIN SELECT RAISE(IGNORE); END",
        "AFTER UPDATE ON tasks BEGIN UPDATE tasks SET title='changed' WHERE id=NEW.id; END",
    ],
)
def test_altered_schema_cannot_report_fake_success(store, name, body):
    store.add("original")
    with sqlite3.connect(str(store.path)) as con:
        con.execute("CREATE TRIGGER {} {}".format(name, body))
    before = store.path.read_bytes()
    for action in (
        store.list_tasks,
        lambda: store.add("new"),
        lambda: store.complete(1),
    ):
        with pytest.raises(StorageError):
            action()
        assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    "column, value",
    [
        ("title", b"blob"),
        ("title", "x\x1b[31m"),
        ("title", "\t"),
        ("priority", "other"),
        ("done", 2),
        ("done", "no"),
        ("created_at", "invalid"),
        ("created_at", "2026-01-01"),
        ("completed_at", "2026-01-01T00:00:00+00:00"),
    ],
)
def test_invalid_saved_data_fails_cleanly(store, column, value):
    store.add("original")
    with sqlite3.connect(str(store.path)) as con:
        con.execute("PRAGMA ignore_check_constraints=ON")
        con.execute("UPDATE tasks SET {}=? WHERE id=1".format(column), (value,))
    before = store.path.read_bytes()
    for action in (store.list_tasks, lambda: store.complete(1)):
        with pytest.raises(StorageError):
            action()
        assert store.path.read_bytes() == before


def test_dangling_symlink_is_not_reported_as_empty(tmp_path):
    path = tmp_path / "db"
    try:
        path.symlink_to(tmp_path / "missing")
    except OSError:
        pytest.skip("Symlink creation unavailable")
    store = TaskStore(path)
    with pytest.raises(StorageError):
        store.list_tasks()
    with pytest.raises(StorageError):
        store.complete(1)


def test_modified_constraints_rejected_without_mutation(tmp_path):
    path = tmp_path / "db"
    from project_manager.storage import SCHEMA_SQL

    with sqlite3.connect(str(path)) as con:
        con.execute(
            SCHEMA_SQL.replace("CHECK(done IN (0, 1))", "CHECK(done IN (0, 1, 2))")
        )
        con.execute("PRAGMA application_id={}".format(APPLICATION_ID))
        con.execute("PRAGMA user_version=1")
    before = path.read_bytes()
    with pytest.raises(StorageError):
        TaskStore(path).add("x")
    assert path.read_bytes() == before


def test_fifo_database_rejected_without_opening(tmp_path):
    import os

    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs unavailable on this platform")
    path = tmp_path / "fifo"
    os.mkfifo(str(path))
    store = TaskStore(path)
    for action in (store.list_tasks, lambda: store.add("x"), lambda: store.complete(1)):
        with pytest.raises(StorageError, match="regular file"):
            action()
