# browserlike: notes for Claude Code sessions

A drop-in replacement for `requests` that keeps one browser identity per session. Read
`docs/architecture.md` before changing code.

## Rules

- **Never push, add a git remote, create a GitHub repository or upload to PyPI** unless the owner
  says so in this session. Commits stay local.
- Git identity is repo-local and neutral (`browserlike <browserlike@localhost>`). Never commit with a
  personal email.
- Code, docstrings and docs are in English. Commits follow Conventional Commits.
- **Browser facts go into `src/browserlike/data/*.json`, never into code.** Each fact names its
  evidence (a key in the file's `evidence` map: a capture, a stand run, upstream data) and stays
  `verified: false` until a real-browser capture backs it.
- Only verified versions may be generated or claimed. New version = new capture + data change; see
  "Adding a Chrome version" in `docs/architecture.md`.
- The library makes no network calls on its own: no downloads at import, no telemetry, no update
  checks.
- Do not touch TTL or TCP options in engines (see README "Limitations").
- tls.peet.ws is a shared free service: keep network test runs rare and small.

## Design conventions

- Value objects are frozen dataclasses. Browsers, engines and challenge vendors are strategies behind
  ABCs (`BrowserProfile`, `Engine`/`Transport`, `ChallengeRule`).
- Composition and constructor injection with defaults. No module-level mutable state.
- Public API is explicit via `__all__`. Full type hints, `mypy --strict` clean. Google-style
  docstrings on public API.
- Engines own nothing but the wire: no cookies, no redirects, no headers of their own.

## Commands

```bash
uv venv && uv pip install -e ".[all,dev]"
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
.venv/bin/mypy
.venv/bin/pytest                  # offline: unit + local echo-server engine tests
.venv/bin/pytest --run-network    # + one tls.peet.ws request per engine
```

The comparison stand lives outside the repo, in `../fingerprint-lab`. Its `.venv` has this package
installed in editable mode. Its clients `browserlike*` compare us with real-browser captures.
