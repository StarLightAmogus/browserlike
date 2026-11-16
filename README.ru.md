# browserlike

[![CI](https://github.com/StarLightAmogus/browserlike/actions/workflows/ci.yml/badge.svg)](https://github.com/StarLightAmogus/browserlike/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md) | **Русский**

Замена [`requests`](https://requests.readthedocs.io/), которая подключается без переделки кода.
Сервер на всех доступных ему уровнях видит один и тот же настоящий браузер. Личность одна на всю
сессию, а сам браузер запускать не нужно.

```python
import browserlike as requests

s = requests.Session(country="RU")
r = s.get("https://example.com/")
```

Обычный `requests` выдаёт себя на каждом уровне: TLS ClientHello от Python, HTTP/1.1, User-Agent
`python-requests`. Библиотеки вроде curl_cffi, httpcloak и wreq берут на себя TLS и HTTP/2, а всё
остальное остаётся на вас: User-Agent, Client Hints, порядок заголовков, значения `Sec-Fetch-*`,
Referer, `Accept-Language`, подсказки, запрошенные через `Accept-CH`. Все эти признаки должны
сходиться с TLS-отпечатком и между собой, а посреди сессии не должны меняться. Этот слой и есть
browserlike.
Он один раз выбирает личность (версию браузера, ОС, языки) и собирает каждый запрос так, как его
отправил бы этот браузер. Под капотом работает движок, который имитирует браузер на уровне
соединения, а снаружи остаётся привычный API `requests`.

> Статус: альфа (0.1.0). Chrome 155–156 на Windows, macOS и Linux.

## Установка

На PyPI библиотеки пока нет, она ставится с GitHub. Движок по умолчанию, httpcloak, устанавливается
вместе с пакетом, остальные добавляются через extras:

```bash
pip install "browserlike @ git+https://github.com/StarLightAmogus/browserlike"        # with httpcloak, the default engine
pip install "browserlike[curl] @ git+https://github.com/StarLightAmogus/browserlike"  # + curl_cffi fallback
pip install "browserlike[wreq] @ git+https://github.com/StarLightAmogus/browserlike"  # + wreq (Python 3.11+)
pip install "browserlike[all] @ git+https://github.com/StarLightAmogus/browserlike"   # every engine
```

httpcloak выходит только готовыми сборками (wheels) для Linux x86_64 и aarch64 (glibc), macOS
и Windows x64. На других платформах, например Windows на Arm, browserlike ставится без него, и тогда
нужен extra `curl`. Два случая проходят мимо маркера платформы, и установка падает: Alpine (musl)
и 32-битный Python на 64-битной Windows. Там ставьте пакет с `--no-deps`, а остальные зависимости
и curl_cffi добавьте вручную.

## Использование

`Session` — настоящий `requests.Session`. Куки, редиректы, авторизация, хуки, прокси, `params`,
`json`, `mount` и исключения `requests` работают как раньше.

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

**Виды запросов.** Браузер никогда не шлёт «просто запрос». Он открывает страницу, отправляет форму
или вызывает `fetch()` со страницы, и у каждого из этих действий свои заголовки и свой порядок.
browserlike определяет вид сам:

- GET — переход на страницу (navigation), если только `Accept` не просит JSON.
- POST формы — тоже переход.
- JSON и остальные методы — запросы из скрипта (fetch).

Чтобы задать вид явно, передайте `kind="navigate"` или `kind="fetch"`.

**Переходы.** По умолчанию (`navigation="chain"`) переход на тот же сайт, что и предыдущая
страница, выглядит как клик по ссылке: в нём есть `Referer`, урезанный по стандартной политике
`strict-origin-when-cross-origin`, и правильный `Sec-Fetch-Site`. Переход на другой сайт
выглядит как адрес, набранный вручную. С `navigation="direct"` так выглядит каждый переход. Если
передать `Referer` самостоятельно, он задаёт страницу, с которой пришёл запрос.

**Client Hints.** Если сайт присылает `Accept-CH`, в следующих запросах к нему появляются
запрошенные подробные подсказки (полный список версий, версия платформы, архитектура…). Их значения
берутся из личности. Согласие на подсказки запоминается для каждого origin отдельно, как в Chrome. `Critical-CH` вызывает
один повтор запроса.

**Сохранение.** Сохранённая сессия для HTTP — то же, что профиль браузера на диске:

```python
s.save("profile.session.json")        # identity, cookies, client hints, current page
s = requests.Session.load("profile.session.json")
```

При загрузке просроченные куки отбрасываются. Сессионные куки остаются, как в браузере
с восстановлением сессии.

**Страницы антиботов.** У каждого ответа есть `response.challenge`: `None` или вендор, чья это
страница проверки или блокировки. Поддерживаются Cloudflare, DataDome, PerimeterX/HUMAN, Akamai,
Imperva, Kasada, Qrator, DDoS-Guard и Yandex SmartCaptcha.

- `Session(raise_on_challenge=True)` выбрасывает `ChallengeDetected`, это `requests.HTTPError`.
- `challenge_handler=` позволяет подставить куки пройденной проверки, полученные в другом месте,
  и один раз повторить запрос. Личность при этом должна остаться той же.

JavaScript-проверки browserlike не решает.

**Готовые сессии.** Адаптер подключается к любому `requests.Session`:

```python
import requests
from browserlike import BrowserAdapter

session = requests.Session()
adapter = BrowserAdapter()
session.mount("https://", adapter)
session.mount("http://", adapter)
```

## Что проверено

Каждый факт о браузере лежит в `src/browserlike/data/*.json` вместе с источником, который его
подтверждает.

| Слой | Статус | Подтверждение |
|---|---|---|
| TLS ClientHello, Chrome 152–156 | совпадает с настоящим Chrome 156: JA4 `t13d1517h2_8daaf6152771_cb7bf5808d99`, при возобновлении `…1518…_e2d80978ab2e`, peetprint | снимок настоящего Chrome 156 на tls.peet.ws, 14.11.2026 |
| Настройки HTTP/2, окно, порядок псевдозаголовков | совпадают (`1:65536;2:0;4:6291456;6:262144\|15663105\|0\|m,a,s,p`) | тот же снимок |
| Заголовки перехода: имена, значения, порядок | совпадают байт в байт для Chrome 156 / Windows / ru-RU | эталонный тест и tls.peet.ws, все три движка |
| GREASE-бренд в `sec-ch-ua` | алгоритм Chromium | совпадает с нашим снимком Chrome 156 и со значениями для 152 / 154 / 155 из curl_cffi, wreq и httpcloak |
| Порядок заголовков в fetch, формах и после Accept-CH | из данных пресетов httpcloak 1.7.3, сами мы его ещё не снимали | в данных помечено как непроверенное |
| Детали macOS / Linux / Windows 10, таблицы языков | приблизительно | помечено в данных |

## Движки

| Движок | TLS по сравнению с Chrome 156 | Известные отличия |
|---|---|---|
| `httpcloak` (по умолчанию) | совпадает | не найдены; куки в HTTP/2 разбиваются так же, как в Chromium |
| `wreq` | совпадает | заголовок cookie в HTTP/2 не разбивается; место `Host` в HTTP/1.1 |
| `curl_cffi` | JA4 совпадает, peetprint отличается | нет GREASE в `signature_algorithms`; заголовок cookie в HTTP/2 не разбивается |

Движки сами не ходят по редиректам и не хранят куки: этим состоянием владеет `requests`. DNS-запросы
httpcloak за ключами ECH уходят на публичные резолверы, поэтому по умолчанию они выключены.
ClientHello при этом всё равно содержит GREASE-расширение ECH, как у Chrome.

## Ограничения

- **Отпечаток TCP/IP.** Отпечаток уровня ОС (TTL, опции TCP) принадлежит вашей машине. Инструменты
  вроде p0f видят Linux-сервер за «Windows»-браузером, и так же выглядит любой пользователь VPN или
  прокси. browserlike намеренно не меняет TTL: если поменять только TTL, получится гибрид, который
  не отправляет ни одно настоящее устройство. За прокси сайт видит сетевой стек прокси.
- **JavaScript-проверки** (сенсорные скрипты, proof of work) без JS-движка не пройти.
  С согласованным пассивным отпечатком они встречаются реже.
- Ответы буферизуются: `stream=True` принимается, но тело читается целиком.
- HTTP/3 пока выключен.
- На серверах, которые отвечают только по HTTP/1.1, в первом запросе есть заголовок `Priority`
  (Chrome его там не отправляет). В следующих запросах его уже нет.
- Только Chrome. Объект `Session`, как и `requests.Session`, не потокобезопасен.

## Планы

- профили Firefox, Safari, Edge и Яндекс Браузера
- запросы картинок, скриптов и стилей
- настоящий потоковый режим
- HTTP/3
- HTTP-кеш (`ETag` / `If-None-Match` при повторных визитах)
- проверка TCP через прокси, чтобы ОС личности совпадала с выходным узлом
- пул сессий (личность + прокси + куки; заблокированные выводятся из оборота)
- интеграции с сервисами-решателями проверок

## Разработка

```bash
uv venv && uv pip install -e ".[all,dev]"
ruff check src tests && ruff format --check src tests
mypy
pytest                  # unit + local engine tests, offline
pytest --run-network    # + one request per engine to tls.peet.ws
```

Устройство библиотеки описано в [docs/architecture.md](docs/architecture.md), как участвовать
в проекте (в том числе как добавить версию Chrome) — в [CONTRIBUTING.md](CONTRIBUTING.md), история
изменений — в [CHANGELOG.md](CHANGELOG.md). О проблемах безопасности сообщайте закрыто, как описано
в [SECURITY.md](SECURITY.md).

## Ответственное использование

browserlike делает HTTP-клиент неотличимым от браузера на уровне протоколов. Используйте его только
для трафика, который вам разрешено отправлять: для своих сервисов, тестирования, исследований и сбора
данных с соблюдением условий сайта, правил robots и действующего законодательства. Инструментов для
обхода аутентификации или атак на сервисы в нём нет и не будет.

## Контакты

Вопросы и отзывы: Telegram [t.me/RickSoftware](https://t.me/RickSoftware). Об ошибках и пожеланиях
пишите в [GitHub issues](https://github.com/StarLightAmogus/browserlike/issues), о проблемах
безопасности — по правилам из [SECURITY.md](SECURITY.md).

## Лицензия

MIT
