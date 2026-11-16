# browserlike

[![CI](https://github.com/StarLightAmogus/browserlike/actions/workflows/ci.yml/badge.svg)](https://github.com/StarLightAmogus/browserlike/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A drop-in replacement for [`requests`](https://requests.readthedocs.io/) that looks like one real
browser on every layer the server can see, with one consistent identity per session and no browser
to launch.

```python
import browserlike as requests

s = requests.Session(country="RU")
r = s.get("https://example.com/")
```

A plain `requests` call announces itself on every layer: a Python TLS ClientHello, HTTP/1.1, a
`python-requests` User-Agent. Libraries such as curl_cffi, httpcloak and wreq fix TLS and HTTP/2,
but the rest is left to you: User-Agent, client hints, header order, `Sec-Fetch-*` values, Referer,
`Accept-Language`, `Accept-CH` follow-ups. Every one of these must agree with the TLS fingerprint and
with each other, and must not change mid-session. browserlike is that layer. It picks an identity
once (browser version, OS, languages) and renders every request the way that browser would send it,
on top of an impersonating engine, behind the `requests` API.

> Status: alpha (0.1.0). Chrome 155–156 on Windows, macOS and Linux.

## Install

Not on PyPI yet; install from GitHub. The default engine, httpcloak, comes with the package;
the extras add the others:

```bash
pip install "browserlike @ git+https://github.com/StarLightAmogus/browserlike"        # with httpcloak, the default engine
pip install "browserlike[curl] @ git+https://github.com/StarLightAmogus/browserlike"  # + curl_cffi fallback
pip install "browserlike[wreq] @ git+https://github.com/StarLightAmogus/browserlike"  # + wreq (Python 3.11+)
pip install "browserlike[all] @ git+https://github.com/StarLightAmogus/browserlike"   # every engine
```

httpcloak ships wheels only, for Linux x86_64 and aarch64 (glibc), macOS and Windows x64. On other
platforms, such as Windows on Arm, browserlike installs without it: add the `curl` extra. Two cases
slip past the platform marker and fail to install: Alpine (musl) and 32-bit Python on 64-bit
Windows. There, install with `--no-deps` and add the other dependencies and curl_cffi by hand.

## Usage

`Session` is a real `requests.Session`. Cookies, redirects, auth, hooks, proxies, `params`, `json`,
`mount` and the `requests` exceptions all work as before.

```python
import browserlike as requests

s = requests.Session(
    seed=42,               # reproducible identity
    platform="windows",    # windows | macos | linux
    locale="ru-RU",        # or country="RU"
    engine="httpcloak",    # httpcloak | curl_cffi | wreq; best installed by default
)
print(s.identity)          # browser version, OS details and languages chosen for this session

page = s.get("https://shop.example.com/catalog")            # navigation
api = s.get("https://shop.example.com/api/items", kind="fetch")  # fetch() from that page
s.post("https://shop.example.com/login", data={"u": "me"})       # form submission
s.post("https://shop.example.com/api/cart", json={"id": 1})       # fetch() POST
```

**Request kinds.** A browser never sends a bare "request". It opens a page, submits a form or runs
`fetch()` from a page, and each of these has its own headers and order. browserlike infers the kind:

- GET is a navigation, unless `Accept` asks for JSON.
- A form POST is a navigation.
- JSON and other methods are fetches.

Pass `kind="navigate"` or `kind="fetch"` to set it yourself.

**Navigation.** By default (`navigation="chain"`), a navigation to the same site as the previous
page looks like a link click: it carries `Referer` (trimmed by the default
`strict-origin-when-cross-origin` policy) and the right `Sec-Fetch-Site`. A jump to another site
looks like a typed URL. With `navigation="direct"`, every navigation looks typed. A `Referer` you
pass yourself sets the page the request comes from.

**Client hints.** When a site sends `Accept-CH`, later requests to it carry the requested high-entropy
hints (full version list, platform version, architecture…), taken from the identity. The opt-in is
remembered per origin, as in Chrome. `Critical-CH` triggers one retry.

**Persistence.** A saved session is the HTTP equivalent of a browser profile on disk:

```python
s.save("profile.session.json")        # identity, cookies, client hints, current page
s = requests.Session.load("profile.session.json")
```

Expired cookies are dropped on load. Session cookies are kept, as a browser with session restore
does.

**Anti-bot pages.** Each response has `response.challenge`: `None`, or the vendor whose
challenge/block page it is. Vendors covered: Cloudflare, DataDome, PerimeterX/HUMAN, Akamai, Imperva,
Kasada, Qrator, DDoS-Guard and Yandex SmartCaptcha.

- `Session(raise_on_challenge=True)` raises `ChallengeDetected`, a `requests.HTTPError`.
- `challenge_handler=` lets you import clearance cookies from elsewhere and retry once. The import
  must keep the same identity.

browserlike does not solve JavaScript challenges.

**Existing sessions.** The adapter works on any `requests.Session`:

```python
import requests
from browserlike import BrowserAdapter

session = requests.Session()
adapter = BrowserAdapter()
session.mount("https://", adapter)
session.mount("http://", adapter)
```

## What is verified

Every browser fact lives in `src/browserlike/data/*.json` with the evidence behind it.

| Layer | Status | Evidence |
|---|---|---|
| TLS ClientHello, Chrome 152–156 | identical to real Chrome 156: JA4 `t13d1517h2_8daaf6152771_cb7bf5808d99`, resumed `…1518…_e2d80978ab2e`, peetprint | real Chrome 156 capture on tls.peet.ws, 2026-11-14 |
| HTTP/2 settings, window, pseudo-header order | identical (`1:65536;2:0;4:6291456;6:262144\|15663105\|0\|m,a,s,p`) | same capture |
| Navigation headers: names, values, order | identical, byte for byte, for Chrome 156 / Windows / ru-RU | golden test + tls.peet.ws, all three engines |
| `sec-ch-ua` GREASE brand | Chromium's algorithm | matches our Chrome 156 capture and the 152 / 154 / 155 values shipped by curl_cffi, wreq and httpcloak |
| Fetch / form / Accept-CH header order | from httpcloak 1.7.3 preset data, not captured by us yet | marked unverified in the data |
| macOS / Linux / Windows-10 details, locale tables | approximate | marked in the data |

## Engines

| Engine | TLS vs Chrome 156 | Known differences |
|---|---|---|
| `httpcloak` (default) | exact | none found; HTTP/2 cookies are split like Chromium does |
| `wreq` | exact | HTTP/2 cookie header not split; `Host` placement on HTTP/1.1 |
| `curl_cffi` | JA4 exact, peetprint differs | no GREASE in `signature_algorithms`; HTTP/2 cookie header not split |

Engines never follow redirects and never keep cookies: `requests` owns that state. httpcloak's ECH
DNS lookups go to public resolvers, so they are off by default; the ClientHello still carries
Chrome's GREASE ECH extension.

## Limitations

- **TCP/IP fingerprint.** The OS-level fingerprint (TTL, TCP options) is your machine's. Tools such
  as p0f see a Linux server behind a "Windows" browser, which is also what every VPN or proxy user
  looks like. browserlike deliberately does not change the TTL: a TTL-only change produces a hybrid
  that no real device sends. Behind a proxy, the site sees the proxy's stack.
- **JavaScript challenges** (sensor scripts, proof of work) cannot be passed without a JS runtime.
  A consistent passive fingerprint makes them rarer.
- Responses are buffered: `stream=True` is accepted, but the body is read fully.
- HTTP/3 is disabled for now.
- On HTTP/1.1-only origins, the first request carries a `Priority` header (Chrome omits it there).
  Later requests don't.
- Chrome only. A `Session` is not thread-safe, like `requests.Session`.

## Roadmap

- Firefox, Safari, Edge and Yandex Browser profiles
- image, script and style destinations
- true streaming
- HTTP/3
- HTTP cache (`ETag` / `If-None-Match` on repeat visits)
- a proxy TCP probe that picks the identity's OS to match the exit node
- a session pool (identity + proxy + cookies, retired when blocked)
- solver integrations

## Development

```bash
uv venv && uv pip install -e ".[all,dev]"
ruff check src tests && ruff format --check src tests
mypy
pytest                  # unit + local engine tests, offline
pytest --run-network    # + one request per engine to tls.peet.ws
```

See [docs/architecture.md](docs/architecture.md) for the design, [CONTRIBUTING.md](CONTRIBUTING.md)
for how to contribute (including adding a Chrome version) and [CHANGELOG.md](CHANGELOG.md). Report
security issues privately, as described in [SECURITY.md](SECURITY.md).

## Responsible use

browserlike makes HTTP clients indistinguishable from a browser at the protocol level. Use it only for
traffic you are authorized to send: your own services, testing, research, and data collection that
respects the target site's terms, robots rules and applicable law. It does not and will not include
tools for bypassing authentication or attacking services.

## Contact

Questions and feedback: Telegram [t.me/RickSoftware](https://t.me/RickSoftware). Bugs and feature requests go to
[GitHub issues](https://github.com/StarLightAmogus/browserlike/issues); security issues follow
[SECURITY.md](SECURITY.md).

## License

MIT
