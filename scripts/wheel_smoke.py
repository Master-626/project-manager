"""Check the installed console script from outside the source checkout."""

import os
import subprocess
import sysconfig
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix="project-manager-wheel-") as directory:
    root = Path(directory)
    database = root / "tasks #1.sqlite3"
    scripts = Path(sysconfig.get_path("scripts"))
    entry = scripts / ("project-manager.exe" if os.name == "nt" else "project-manager")
    env = dict(
        os.environ,
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        NO_COLOR="1",
        COLUMNS="120",
    )
    env.pop("PYTHONPATH", None)

    def run(*args, success=True):
        result = subprocess.run(
            [str(entry), "--database", str(database), *args],
            cwd=str(root),
            env=env,
            encoding="utf-8",
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert (result.returncode == 0) == success, (result.stdout, result.stderr)
        return result.stdout

    assert "No tasks yet" in run("list")
    assert not database.exists()
    assert "Added task #1" in run("add", "任务 [bold]literal[/bold]", "-p", "urgent")
    assert "任务 [bold]literal[/bold]" in run("list")
    assert "Completed task #1" in run("done", "1")
    assert "Completed" in run("list")
    assert "already completed" in run("done", "1")
    run("done", "999", success=False)
    assert "Added task #2" in run("add", "temporary")
    assert "Deleted task #2" in run("delete", "2")
    listed = run("list")
    assert "temporary" not in listed
    assert "任务 [bold]literal[/bold]" in listed
    run("delete", "2", success=False)
print(
    "Installed project-manager console: persistent add/list/done/delete and error checks passed."
)
