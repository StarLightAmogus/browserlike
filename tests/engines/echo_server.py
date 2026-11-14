"""Local HTTPS echo server for engine tests: HTTP/1.1 and HTTP/2, no internet.

The server reports the request header block exactly as it arrived on the wire:
pseudo-headers included, original order, original casing on HTTP/1.1, repeated
fields not merged (so HTTP/2 cookie crumbs stay visible). Tests use it to check
that an engine sends our header list verbatim and injects nothing.

It also serves the cases an engine must handle: Set-Cookie, redirects,
compressed bodies, Accept-CH, slow responses and a fake challenge page.
"""

from __future__ import annotations

import gzip
import json
import socket
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h2.config
import h2.connection
import h2.events
import trustme

Header = tuple[str, str]


def _zstd(data: bytes) -> bytes | None:
    try:
        from compression import zstd  # type: ignore[import-not-found]  # Python 3.14+
    except ImportError:
        return None
    return bytes(zstd.compress(data))


def respond(
    version: str, method: str, target: str, headers: list[Header], body: bytes
) -> tuple[int, list[Header], bytes]:
    """Builds the response for one request: (status, headers, payload)."""
    parts = urllib.parse.urlsplit(target)
    path = parts.path
    query = dict(urllib.parse.parse_qsl(parts.query))
    report: dict[str, Any] = {
        "http_version": version,
        "method": method,
        "path": path,
        "query": query,
        "headers": [list(h) for h in headers],
        "body": body.decode("utf-8", "replace"),
    }
    payload = json.dumps(report).encode()
    status = 200
    out: list[Header] = [("content-type", "application/json")]

    if path == "/set-cookies":
        out += [
            ("set-cookie", "a=1; Path=/"),
            ("set-cookie", "b=2; Path=/; HttpOnly"),
            ("set-cookie", "short=x; Path=/; Max-Age=1"),
        ]
    elif path == "/redirect":
        status = int(query.get("code", "302"))
        out.append(("location", query.get("to", "/echo")))
        payload = b""
    elif path == "/gzip":
        payload = gzip.compress(payload)
        out.append(("content-encoding", "gzip"))
    elif path == "/zstd":
        compressed = _zstd(payload)
        if compressed is not None:
            payload = compressed
            out.append(("content-encoding", "zstd"))
    elif path == "/accept-ch":
        out.append(("accept-ch", "Sec-CH-UA-Full-Version-List, Sec-CH-UA-Platform-Version"))
    elif path == "/critical-ch":
        out.append(("accept-ch", "Sec-CH-UA-Platform-Version"))
        out.append(("critical-ch", "Sec-CH-UA-Platform-Version"))
    elif path == "/slow":
        time.sleep(float(query.get("delay", "3")))
    elif path == "/challenge":
        status = 403
        out += [("cf-mitigated", "challenge"), ("server", "cloudflare")]
        payload = b"<html><head><title>Just a moment...</title></head></html>"
    out.append(("content-length", str(len(payload))))
    return status, out, payload


def _serve_h2(sock: ssl.SSLSocket) -> None:
    config = h2.config.H2Configuration(
        client_side=False,
        header_encoding=None,
        normalize_inbound_headers=False,
        validate_inbound_headers=False,
    )
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    sock.sendall(conn.data_to_send())
    streams: dict[int, dict[str, Any]] = {}
    while True:
        data = sock.recv(65535)
        if not data:
            return
        for event in conn.receive_data(data):
            if isinstance(event, h2.events.RequestReceived):
                raw = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in event.headers]
                streams[event.stream_id] = {"headers": raw, "body": b""}
            elif isinstance(event, h2.events.DataReceived):
                streams[event.stream_id]["body"] += event.data
                conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            elif isinstance(event, h2.events.StreamEnded):
                req = streams.pop(event.stream_id)
                pseudo = dict(h for h in req["headers"] if h[0].startswith(":"))
                status, headers, payload = respond(
                    "2", pseudo.get(":method", ""), pseudo.get(":path", "/"), req["headers"], req["body"]
                )
                conn.send_headers(event.stream_id, [(":status", str(status)), *headers])
                conn.send_data(event.stream_id, payload, end_stream=True)
            elif isinstance(event, h2.events.ConnectionTerminated):
                sock.sendall(conn.data_to_send())
                return
        sock.sendall(conn.data_to_send())


def _serve_h1(sock: ssl.SSLSocket) -> None:
    buf = b""
    while True:
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(65535)
            if not chunk:
                return
            buf += chunk
        head, _, buf = buf.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        headers = [(name, value.strip()) for name, _, value in (line.partition(":") for line in lines[1:])]
        length = next((int(v) for k, v in headers if k.lower() == "content-length"), 0)
        while len(buf) < length:
            buf += sock.recv(65535)
        body, buf = buf[:length], buf[length:]
        status, out, payload = respond("1.1", method, target, headers, body)
        response = f"HTTP/1.1 {status} X\r\n" + "".join(f"{k}: {v}\r\n" for k, v in out) + "\r\n"
        sock.sendall(response.encode("latin-1") + payload)


@dataclass
class EchoServer:
    """Runs the echo server over TLS on 127.0.0.1 in background threads."""

    workdir: Path
    port: int = 0
    ca_path: Path = field(init=False)
    _listener: socket.socket | None = field(default=None, init=False)
    _closed: threading.Event = field(default_factory=threading.Event, init=False)

    @property
    def base_url(self) -> str:
        return f"https://localhost:{self.port}"

    def start(self) -> EchoServer:
        ca = trustme.CA()
        cert = ca.issue_cert("localhost", "127.0.0.1")
        self.ca_path = self.workdir / "ca.pem"
        ca.cert_pem.write_to_path(str(self.ca_path))
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        cert.configure_cert(ctx)
        ctx.set_alpn_protocols(["h2", "http/1.1"])

        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(16)
        self.port = self._listener.getsockname()[1]

        def handle(raw: socket.socket) -> None:
            try:
                with ctx.wrap_socket(raw, server_side=True) as tls:
                    if tls.selected_alpn_protocol() == "h2":
                        _serve_h2(tls)
                    else:
                        _serve_h1(tls)
            except (OSError, ssl.SSLError, ValueError):
                pass

        def accept_loop() -> None:
            assert self._listener is not None
            while not self._closed.is_set():
                try:
                    raw, _ = self._listener.accept()
                except OSError:
                    return
                threading.Thread(target=handle, args=(raw,), daemon=True).start()

        threading.Thread(target=accept_loop, daemon=True).start()
        return self

    def stop(self) -> None:
        self._closed.set()
        if self._listener is not None:
            self._listener.close()
