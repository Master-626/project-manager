# Project Manager

Version 0.2.0 replaces the original prototype with a small Python CLI that saves tasks locally in SQLite. Supports Python 3.8+.

## Working features

- Add tasks with stable numeric IDs and low, medium, high, or urgent priority.
- List saved tasks and their real completion status across separate runs.
- Complete existing tasks; repeated completion keeps the original timestamp.
- Transactional SQLite writes, concurrent-process locking, and explicit errors.

Projects, timers, tags, due dates, editing/deleting tasks, and reports are not
implemented. Earlier README claims for these features described a roadmap,
not working functionality. The original CLI did not save tasks, so there is
no historical data to migrate from that version.

## Installation

```bash
git clone https://github.com/Master-626/project-manager.git
cd project-manager
python -m pip install .
```

## Quick start

```bash
project-manager add "Finish documentation" -p high
project-manager list
project-manager done 1
```

Use the ID returned by `add`. A missing task ID is an error, never a successful
completion. Empty stores show no sample tasks. Titles must be nonblank and
cannot contain control characters; terminal markup is displayed literally.

## Storage

The default file is `tasks.sqlite3` in Click's per-user application directory:

- Linux: `$XDG_CONFIG_HOME/project-manager/` or `~/.config/project-manager/`
- macOS: `~/Library/Application Support/project-manager/`
- Windows: `%APPDATA%\\project-manager\\`

It does not depend on your current working directory. To select a different
file, put the global option **before** the command:

```bash
project-manager --database ./personal-tasks.sqlite3 add "Buy supplies"
project-manager --database ./personal-tasks.sqlite3 list
project-manager --database ./personal-tasks.sqlite3 done 1
```

Alternatively set `PROJECT_MANAGER_DB` (the explicit option takes precedence).
Relative overrides are relative to the current directory. `list` on a missing
store does not create a file; `add` creates its parent directories as needed.

Use a local disk, not a network share or cloud-sync folder. SQLite transactions
prevent partial updates and serialize concurrent writers; a writer waits up to
five seconds for a lock, then exits with an error. Back up the database while
no command is running. Database contents are not encrypted; use a private
location and your operating system's permissions for sensitive task titles.

Unreadable, corrupt, unrelated, modified-schema, or unsupported-version databases fail with a
nonzero exit status, without being silently reset. Check the path/permissions,
stop a competing writer, or restore a backup rather than deleting your only
copy. Success messages are printed only after a transaction commits.

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m compileall -q src
python -m build
```

Tests cover independent CLI processes, concurrent additions/completions,
validation, literal titles, rollback, database corruption/locking, and storage
path selection. CI is configured for Linux Python 3.8/3.12/3.14 and Windows/macOS Python 3.12,
including installed-wheel console command checks.

## License

MIT License
