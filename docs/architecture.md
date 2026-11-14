# Architecture

## Pipeline

```
requests.Session.request()                      (browserlike.Session adds kind=)
  └─ PreparedRequest ─► BrowserAdapter.send()
        1. caller headers      drop requests' defaults (python-requests UA, Accept: */*, ...)
        2. RequestContext      ContextResolver (kind) + NavigationState (initiator) or a pending redirect
        3. FetchMetadata       FetchMetadataPolicy: Sec-Fetch-Site, Referer (strict-origin-when-cross-origin), Origin
        4. HeaderList          HeaderBuilder: BrowserProfile template + caller headers, profile order
        5. WireRequest ─► Transport.send()      engine: TLS ClientHello + HTTP/2 framing, no cookies/redirects
        6. WireResponse ─► requests.Response    raw with HTTPMessage, so requests extracts every Set-Cookie
        7. state updates       Accept-CH store (+ one Critical-CH retry), navigation history, redirect context
        8. response.challenge  ChallengeDetector
  ◄─ requests handles redirects (calls send() per hop), cookies, hooks
```

## Responsibilities

| Module | Class | Owns |
|---|---|---|
| `identity/model.py` | `Identity`, `OperatingSystem`, `Locale` | immutable description of the pretended browser |
| `identity/generator.py` | `IdentityGenerator` | seeded, weighted choice over verified versions only |
| `browsers/base.py` | `BrowserProfile` (ABC), `TlsEra`, `VersionInfo` | what differs between browsers |
| `browsers/chrome.py` | `ChromeProfile` | Chrome's UA, client hints, GREASE brands, header templates, order, HTTP/1.1 casing |
| `context.py` | `RequestContext`, `ContextResolver` | what kind of browser request a call is |
| `sites.py` | `Origin`, `SiteResolver`, `referrer_for` | origins, PSL sites, referrer policy |
| `fetch_metadata.py` | `FetchMetadataPolicy` | Sec-Fetch-Site / Referer / Origin per context |
| `headers.py` | `HeaderList`, `HeaderBuilder` | merging and ordering, HTTP/2 rendering |
| `navigation.py` | `NavigationState` | current document, chain/direct policy |
| `client_hints.py` | `ClientHintsStore` | Accept-CH per origin |
| `engines/base.py` | `Engine`, `Transport` (ABCs), `WireRequest`, `WireResponse` | engine contract, error classes |
| `engines/*_engine.py` | `HttpcloakEngine`, `CurlCffiEngine`, `WreqEngine` | one engine each, known gaps documented |
| `adapters.py` | `BrowserAdapter` | the orchestration above, retries, error mapping |
| `sessions.py` | `Session` | requests integration, `kind=`, challenges, save/load |
| `persistence.py` | `SessionState` | the on-disk profile format |
| `challenges.py` | `ChallengeDetector`, `ChallengeRule` | vendor markers |

## Principles

- **One identity per session.** Everything that varies by browser comes from the `Identity` plus the
  `BrowserProfile`. Caller overrides of identity headers are allowed but warn
  (`IdentityConflictWarning`).
- **Data, not code, for browser facts.** `data/chrome.json` holds versions, TLS eras, Accept strings,
  header orders and casing, each with the evidence that backs it. Supporting a new Chrome version
  after capturing a reference is a data change.
- **Verified versions only.** A UA may claim a major version only if it is verified for both the TLS
  era and the header data (`UnverifiedVersionError` otherwise; `allow_unverified=True` to opt out).
- **requests stays the owner of state.** Engines run with their cookie jars, redirects, caches and
  header injection off. Cookies, redirects, auth and hooks are plain `requests`.
- **No network on its own.** The PSL is bundled; nothing is fetched at import or in the background.
- **Strategies behind ABCs.** New browsers implement `BrowserProfile`, new engines `Engine`/`Transport`,
  new vendors `ChallengeRule`; nothing else changes.

## Adding a Chrome version

1. Capture `https://tls.peet.ws/api/all` in that Chrome and save it under `tests/fixtures/`.
2. Compare its JA4 (without `pre_shared_key`) with the TLS eras in `data/chrome.json`. Extend an era's
   `until`, or add a new era and an engine profile that reproduces it.
3. Add or flip the version entry: `verified`, `weight`, full versions from the versionhistory API,
   evidence.
4. Extend the golden test with the new capture.
