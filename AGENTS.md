# Repository Guidelines

## Project Structure & Module Organization
Core Python packages live in `hummingbot/`, grouped by connectors, strategies, client services, and shared utilities. Agent-oriented V2 controllers are in `controllers/`, while executable entry points such as `hummingbot_quickstart.py` sit in `bin/`. Configuration templates and secrets live under `conf/`; never commit personalized API keys. Reusable scripts are stored in `scripts/`, compiled assets in `build/`, and comprehensive tests in `test/` alongside fixtures in `test/mock`.

## Build, Test, and Development Commands
Run `./install` to bootstrap dependencies in a fresh environment. Use `make build` (wrapper over `./compile`) to regenerate Cython extensions after source changes. Execute `make test` for the full pytest + coverage suite; add `pytest path/to/test_file.py -k filter` for targeted runs during development. Launch the quickstart agent harness with `make run-v2 key=value`, for example `make run-v2 strategy=v2_with_controllers`.

## Coding Style & Naming Conventions
Follow Python 3.11 standards with 4-space indentation and descriptive, snake_case module/function names. The project formats code with Black (`line-length = 120`) and sorts imports with isort (mode 3, trailing commas). Type hints are encouraged for new modules, matching existing connector and controller patterns. Keep module docstrings concise and align logging tags with the surrounding package namespace.

## Testing Guidelines
Pytest drives the suite located in `test/`; mimic the directory layout of the code under test. Each new feature must meet the 80% coverage minimum and include scenario-focused tests (async connectors often require fixtures from `test/hummingbot/connector`). Name tests `test_<feature>()` and group them into files mirroring the module under test. Use `make development-diff-cover` after running tests to validate per-change coverage before opening a PR.

## Commit & Pull Request Guidelines
Branch from `development` using prefixes like `feat/<topic>` or `fix/<issue>`. Commit subjects stay under ~70 characters and adopt the `(feat)`, `(fix)`, `(refactor)`, `(doc)`, or `(cleanup)` prefixes described in `CONTRIBUTING.md`. Squash incidental noise and ensure each commit represents a logical unit. Pull requests must summarize the change, link related issues, list test evidence (`make test`, targeted pytest commands), and enable "Allow edits by maintainers" for faster iteration.

## Security & Configuration Tips
Store exchange credentials only in local `conf/*-conf.yml` files or environment variables; redact secrets from logs before sharing. Review `mcp.env` and sample configs to understand required keys, and rotate credentials after testing on shared hosts. When working with Docker, mount `./conf` and `./logs` explicitly to avoid leaking data outside controlled volumes.
