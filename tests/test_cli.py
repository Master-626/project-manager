import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from click.testing import CliRunner

from project_manager.cli import main
from project_manager.storage import TaskStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def run_cli(tmp_path):
    def run(*args, database=True, env_updates=None, cwd=None):
        env = dict(
            os.environ,
            PYTHONPATH=str(ROOT / "src"),
            NO_COLOR="1",
            PYTHONIOENCODING="utf-8",
            PYTHONUTF8="1",
            COLUMNS="140",
            HOME=str(tmp_path / "home"),
            USERPROFILE=str(tmp_path / "home"),
            APPDATA=str(tmp_path / "appdata"),
            XDG_CONFIG_HOME=str(tmp_path / "config"),
        )
        env.pop("PROJECT_MANAGER_DB", None)
        if env_updates:
            env.update(env_updates)
        command = [sys.executable, "-m", "project_manager.cli"]
        if database:
            command.extend(["--database", str(tmp_path / "db.sqlite3")])
        return subprocess.run(
            command + list(args),
            env=env,
            cwd=str(cwd or tmp_path),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
        )

    return run


def test_cross_process_persistence(run_cli, tmp_path):
    initial = run_cli("list")
    assert initial.returncode == 0 and "No tasks yet" in initial.stdout
    assert "Example task" not in initial.stdout
    assert not (tmp_path / "db.sqlite3").exists()
    added = run_cli("add", "Persist 中文", "-p", "high")
    assert added.returncode == 0 and "Added task #1" in added.stdout
    listed = run_cli("list")
    assert listed.returncode == 0
    assert all(s in listed.stdout for s in ("Persist 中文", "high", "Pending"))
    done = run_cli("done", "1")
    assert done.returncode == 0 and "Completed task #1" in done.stdout
    listed = run_cli("list")
    assert "Completed" in listed.stdout and "Pending" not in listed.stdout
    repeat = run_cli("done", "1")
    assert repeat.returncode == 0 and "already completed" in repeat.stdout
    missing = run_cli("done", "999")
    assert missing.returncode != 0 and "does not exist" in missing.stderr
    assert "Completed task" not in missing.stdout


def test_parallel_additions_and_completions(run_cli, tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda n: run_cli("add", "parallel-{}".format(n)), range(16))
        )
    assert all(r.returncode == 0 for r in results), [
        (r.stdout, r.stderr) for r in results
    ]
    store = TaskStore(tmp_path / "db.sqlite3")
    tasks = store.list_tasks()
    assert len(tasks) == 16 and len({t.id for t in tasks}) == 16
    assert {t.title for t in tasks} == {"parallel-{}".format(n) for n in range(16)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: run_cli("done", "1"), range(8)))
    assert all(r.returncode == 0 for r in results)
    assert sum("Completed task #1" in r.stdout for r in results) == 1
    assert sum("already completed" in r.stdout for r in results) == 7
    assert store.list_tasks()[0].done


@pytest.mark.parametrize(
    "args",
    [
        ("add", " "),
        ("add", "x", "-p", "bad"),
        ("add", "x\x1b[31m"),
        ("add", "\u200b"),
        ("add", "a\u2028b"),
        ("done", "0"),
        ("done", "-1"),
        ("done", "9223372036854775808"),
        ("done", "foo"),
        ("delete", "0"),
        ("delete", "foo"),
    ],
)
def test_invalid_cli_inputs(run_cli, tmp_path, args):
    result = run_cli(*args)
    assert result.returncode != 0 and "Error:" in result.stderr
    assert "Added task" not in result.stdout and "Completed task" not in result.stdout
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "db.sqlite3").exists()


def test_missing_id_on_fresh_database(run_cli, tmp_path):
    result = run_cli("done", "1")
    assert result.returncode == 1 and "does not exist" in result.stderr
    assert not (tmp_path / "db.sqlite3").exists()


def test_literal_markup_is_not_executed(run_cli):
    title = "[bold]literal[/bold] [link=https://example.com]link[/link]"
    result = run_cli("add", title)
    assert result.returncode == 0 and title in result.stdout
    result = run_cli("list")
    assert result.returncode == 0 and title in result.stdout
    assert "\x1b" not in result.stdout


def test_env_override_and_option_precedence(run_cli, tmp_path):
    env_path = tmp_path / "env.sqlite3"
    env = {"PROJECT_MANAGER_DB": str(env_path)}
    result = run_cli("add", "env task", database=False, env_updates=env)
    assert result.returncode == 0 and env_path.exists()
    result = run_cli("add", "explicit task", env_updates=env)
    assert result.returncode == 0
    assert [t.title for t in TaskStore(env_path).list_tasks()] == ["env task"]
    assert [t.title for t in TaskStore(tmp_path / "db.sqlite3").list_tasks()] == [
        "explicit task"
    ]


def test_default_store_survives_working_directory_change(run_cli, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    added = run_cli("add", "stable default", database=False, cwd=first)
    listed = run_cli("list", database=False, cwd=second)
    assert added.returncode == listed.returncode == 0
    assert "stable default" in listed.stdout
    assert list(first.iterdir()) == list(second.iterdir()) == []


@pytest.mark.parametrize(
    "command", [("list",), ("add", "x"), ("done", "1"), ("delete", "1")]
)
def test_corruption_fails_without_false_success(run_cli, tmp_path, command):
    path = tmp_path / "db.sqlite3"
    original = b"corrupt data should not be erased"
    path.write_bytes(original)
    result = run_cli(*command)
    assert result.returncode == 1 and "Error:" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Added task" not in result.stdout and "Completed task" not in result.stdout
    assert path.read_bytes() == original


def test_write_failure_is_clean(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", fail)
    result = CliRunner().invoke(main, ["--database", str(tmp_path / "db"), "add", "x"])
    assert result.exit_code == 1 and "permission denied" in result.output
    assert "Added task" not in result.output


def test_help_and_version_do_not_touch_database(run_cli, tmp_path):
    help_result = run_cli("--help")
    assert help_result.returncode == 0
    assert "delete" in help_result.stdout
    assert "0.3.0" in run_cli("--version").stdout
    assert not (tmp_path / "db.sqlite3").exists()


def test_long_title_is_not_truncated(run_cli):
    title = "A" * 120
    added = run_cli("add", title)
    assert added.returncode == 0 and title in added.stdout
    listed = run_cli("list", env_updates={"COLUMNS": "40"})
    assert listed.returncode == 0 and title in listed.stdout
    assert "…" not in listed.stdout


def test_delete_removes_one_task_and_does_not_reuse_id(run_cli, tmp_path):
    missing = run_cli("delete", "1")
    assert missing.returncode != 0 and "does not exist" in missing.stderr
    assert not (tmp_path / "db.sqlite3").exists()
    assert run_cli("add", "keep").returncode == 0
    assert run_cli("add", "drop me").returncode == 0
    deleted = run_cli("delete", "2")
    assert deleted.returncode == 0 and "Deleted task #2" in deleted.stdout
    listed = run_cli("list")
    assert "keep" in listed.stdout and "drop me" not in listed.stdout
    again = run_cli("delete", "2")
    assert again.returncode != 0 and "does not exist" in again.stderr
    added = run_cli("add", "next")
    assert added.returncode == 0 and "Added task #3" in added.stdout


def test_tilde_database_path(run_cli, tmp_path):
    home = tmp_path / "home"
    added = run_cli(
        "--database", "~/tasks.sqlite3", "add", "tilde task", database=False
    )
    assert added.returncode == 0, added.stderr
    assert (home / "tasks.sqlite3").is_file()
    assert not (tmp_path / "~").exists()
    listed = run_cli("--database", "~/tasks.sqlite3", "list", database=False)
    assert listed.returncode == 0 and "tilde task" in listed.stdout
    from_env = run_cli(
        "add",
        "from env",
        database=False,
        env_updates={"PROJECT_MANAGER_DB": "~/env-tasks.sqlite3"},
    )
    assert from_env.returncode == 0, from_env.stderr
    assert (home / "env-tasks.sqlite3").is_file()


def test_existing_non_database_is_not_replaced(run_cli, tmp_path):
    path = tmp_path / "db.sqlite3"
    path.write_bytes(b"x")
    result = run_cli("add", "x")
    assert result.returncode != 0 and "Error:" in result.stderr
    assert "Added task" not in result.stdout
    assert path.read_bytes() == b"x"
