# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Russian README (`README.ru.md`).

## [0.1.0] - 2026-11-16

### Added

- `Session` (a `requests.Session`) and `BrowserAdapter` (mountable on any session) with one browser
  identity per session.
- Chrome 155–156 profile for Windows, macOS and Linux: reduced User-Agent, GREASE brand algorithm,
  low- and high-entropy client hints, navigation, form and fetch header templates and order, and
  HTTP/1.1 casing. The navigation headers are verified byte for byte against real Chrome 156.
- Seeded `IdentityGenerator` over verified versions, with platform weights and locale tables.
- Fetch Metadata (`Sec-Fetch-*`) and Origin rules. Referer under `strict-origin-when-cross-origin`,
  with Public Suffix List sites (bundled, offline).
- Request-kind inference (`navigate` / `fetch`) and `kind=` override. Navigation chaining within a
  site.
- `Accept-CH` store per origin and a `Critical-CH` retry.
- Engines: httpcloak (the default, a dependency on every platform it has wheels for), curl_cffi
  (`curl` extra) and wreq (`wreq` extra). Engine-side cookies, redirects and header injection are
  off.
- Challenge detection for nine anti-bot vendors, `raise_on_challenge`, `challenge_handler`.
- `Session.save()` / `Session.load()`: identity, cookies, client hints, navigation.
- Module-level `get/post/...` and re-exports, so `import browserlike as requests` works.
