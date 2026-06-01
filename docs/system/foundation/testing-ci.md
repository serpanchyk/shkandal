# Testing And CI

The Python workspace uses:

- `ruff` for linting and formatting;
- `mypy` in strict mode;
- `pytest` with async support;
- coverage over `apps` and `packages`;
- local pre-commit hooks run through `uv`.

GitHub Actions runs lockfile validation, dependency install, pre-commit, pytest,
and frontend lint/build checks.
