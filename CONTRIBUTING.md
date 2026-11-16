# Contributing

Bug reports, captures from new Chrome versions and focused pull requests are welcome.

## Set up

```bash
git clone https://github.com/StarLightAmogus/browserlike
cd browserlike
uv venv && uv pip install -e ".[all,dev]"
```

Python 3.10 or newer; the `wreq` extra needs 3.11+.

## Checks

CI runs the same commands; run them before opening a pull request:

```bash
ruff check src tests
ruff format --check src tests
mypy
pytest                  # offline: unit tests and engine tests against a local echo server
```

`pytest --run-network` adds one request per engine to tls.peet.ws. It is a shared free service, so
run it only when a change affects what goes on the wire.

## Ground rules

- Read [docs/architecture.md](docs/architecture.md) before changing code.
- Browser facts (versions, TLS eras, header values and order) live in `src/browserlike/data/*.json`,
  never in code. Each fact names its evidence and stays `verified: false` until a capture from a real
  browser backs it.
- Code, docstrings and docs are in English. Full type hints, `mypy --strict` clean.
- `README.ru.md` is the Russian translation of `README.md`: when you change one, update the other.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
  `docs:`, `test:`, `ci:`, `chore:`.
- The library makes no network calls on its own.

## Adding a Chrome version

1. Open `https://tls.peet.ws/api/all` in that Chrome (a regular window, no extensions that change
   headers) and save the JSON under `tests/fixtures/`. Replace your IP address with `"redacted"`: the
   top-level `ip` and every `src_ip`.
2. Compare its JA4 (without `pre_shared_key`) with the TLS eras in `src/browserlike/data/chrome.json`.
   Extend an era's `until`, or add a new era and an engine profile that reproduces it.
3. Add or update the version entry: `verified`, `weight`, full versions from the Chrome version
   history API, evidence.
4. Extend the golden test with the new capture.

If you cannot do every step, open a "New Chrome version" issue with the capture: it already helps.

## Pull requests

Keep each one focused on a single change. Add tests for behaviour changes and a line in
[CHANGELOG.md](CHANGELOG.md) for anything users will notice.
