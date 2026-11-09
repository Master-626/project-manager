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
        ("done", "0"),
        ("done", "-1"),
        ("done", "9223372036854775808"),
        ("done", "foo"),
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


@pytest.mark.parametrize("command", [("list",), ("add", "x"), ("done", "1")])
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
    assert run_cli("--help").returncode == 0
    assert "0.2.0" in run_cli("--version").stdout
    assert not (tmp_path / "db.sqlite3").exists()
