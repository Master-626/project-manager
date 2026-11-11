# Project Manager

## 简介

`project-manager` 是一个本地命令行任务工具，用 SQLite 保存任务。可以新增、列出、完成和删除任务。默认数据库在用户配置目录，不随当前工作目录变化。`list` 会完整显示标题；已经存在、但不是本程序创建的文件不会被覆盖。支持 Python 3.8 及以上。下文为英文说明。

## Purpose

Project Manager is a small command-line task list. Tasks are stored in a SQLite file on this machine and survive between runs. Supports Python 3.8+.

## Commands

```bash
project-manager add "Finish documentation" -p high
project-manager list
project-manager done 1
project-manager delete 1
```

- `add TITLE` saves a task and prints its new numeric ID. The default priority is `medium`. Use `-p` / `--priority` with `low`, `medium`, `high`, or `urgent`.
- `list` prints every saved task, completed ones included. Titles are printed in full and literally, so text that looks like terminal markup is not interpreted.
- `done ID` marks an existing task completed. Doing it again keeps the original completion time.
- `delete ID` removes an existing task. IDs are not reused. Deleting a missing ID is an error and does not create a database.

An empty store prints no sample tasks. Titles must contain a visible character. Leading and trailing whitespace is removed. Control characters, Unicode line separators, and titles made only of zero-width or format characters are rejected.

Projects, timers, tags, due dates, editing tasks, and reports are not implemented.

## Installation

```bash
git clone https://github.com/Master-626/project-manager.git
cd project-manager
python -m pip install .
```

## Options

Put global options **before** the command:

```bash
project-manager --help
project-manager --version
project-manager --database ./personal-tasks.sqlite3 add "Buy supplies"
project-manager --database ./personal-tasks.sqlite3 list
project-manager --database ./personal-tasks.sqlite3 done 1
project-manager --database ./personal-tasks.sqlite3 delete 1
```

| Option | Meaning |
| --- | --- |
| `--database PATH` | SQLite file to use. Overrides `PROJECT_MANAGER_DB`. |
| `PROJECT_MANAGER_DB` | Same path when `--database` is omitted. |
| `--help` | Show commands and options. |
| `--version` | Print the version. |
| `-p` / `--priority` | Priority for `add` (`low`, `medium`, `high`, `urgent`). |

A leading `~` in the database path is expanded to the home directory. Other relative paths are relative to the current directory. `list` and `delete` on a missing store do not create a file. `add` creates parent directories when the file itself does not exist yet.

## Storage

The default file is `tasks.sqlite3` in Click's per-user application directory:

- Linux: `$XDG_CONFIG_HOME/project-manager/` or `~/.config/project-manager/`
- macOS: `~/Library/Application Support/project-manager/`
- Windows: `%APPDATA%\\project-manager\\`

It does not depend on your current working directory.

Use a local disk, not a network share or cloud-sync folder. SQLite transactions prevent partial updates and serialize concurrent writers. A writer waits up to five seconds for a lock, then exits with an error. Back up the database while no command is running. Database contents are not encrypted. Keep the file in a private location and rely on your operating system's permissions for sensitive titles.

Success messages are printed only after a transaction commits. A missing task ID is an error, never a successful completion or deletion.

Unreadable, corrupt, unrelated, empty, tiny, modified-schema, or unsupported-version files fail with a nonzero exit status and are not replaced or silently reset. That includes a zero-byte file and a SQLite file that is not a project-manager database. Check the path and permissions, stop a competing writer, or restore a backup rather than deleting your only copy.

## Development

```bash
python -m pip install -e '.[dev]'
python -m ruff check src tests scripts
python -m pytest
python -m compileall -q src
python -m build
```

Tests cover independent CLI processes, concurrent additions and completions, validation, full literal titles, deletion, rollback, corrupt and foreign databases, locking, and storage path selection. CI runs Ruff and pytest on Linux (Python 3.8, 3.12, and 3.14) and on Windows and macOS (Python 3.12), then builds a wheel and checks the installed `project-manager` command.

## License

MIT License
