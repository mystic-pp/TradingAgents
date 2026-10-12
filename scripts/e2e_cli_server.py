"""Serve the TradingAgents CLI to browser end-to-end tests.

The app is an interactive terminal wizard. This server gives each browser a
fresh pseudoterminal running ``python -m cli.main`` and mirrors that screen
into an HTML page the e2e web engine can read and type into.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLS = 110
ROWS = 48
IDLE_SECONDS = 20


def ensure_project_python() -> None:
    """Re-exec into the project venv when the runner starts system Python.

    ``.venv/bin/python`` is a symlink to the system interpreter. Python decides
    it is a venv from ``argv[0]``, so compare prefixes instead of resolved paths.
    """
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.prefix).resolve() == (ROOT / ".venv").resolve():
        return
    os.execv(venv_python, [str(venv_python), *sys.argv])


ensure_project_python()

import pyte  # noqa: E402

sessions: dict[str, "CliSession"] = {}
sessions_lock = threading.Lock()


class CliSession:
    def __init__(self) -> None:
        self.last_seen = time.time()
        self.lock = threading.Lock()
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self.screen = pyte.Screen(COLS, ROWS)
        self.stream = pyte.ByteStream(self.screen)
        self.query_buf = b""
        self.closed = False
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "cli.main"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=ROOT,
            env=cli_env(),
        )
        os.close(slave)
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()

    def touch(self) -> None:
        self.last_seen = time.time()

    def text(self) -> str:
        with self.lock:
            return "\n".join(line.rstrip() for line in self.screen.display).rstrip()

    def write(self, data: bytes) -> None:
        if not data or self.closed:
            return
        try:
            os.write(self.master, data)
        except OSError:
            return

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            os.close(self.master)
        except OSError:
            pass

    def _read_output(self) -> None:
        while not self.closed:
            try:
                ready, _, _ = select.select([self.master], [], [], 0.2)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if not data:
                return
            replies = b""
            with self.lock:
                self.stream.feed(data)
                replies = self._terminal_replies(data)
            if replies:
                self.write(replies)

    def _terminal_replies(self, data: bytes) -> bytes:
        self.query_buf = (self.query_buf + data)[-64:]
        replies = b""
        if b"\x1b[6n" in self.query_buf:
            self.query_buf = self.query_buf.replace(b"\x1b[6n", b"", 1)
            row = self.screen.cursor.y + 1
            col = self.screen.cursor.x + 1
            replies += f"\x1b[{row};{col}R".encode()
        for query in (b"\x1b[0c", b"\x1b[c", b"\x1b[>0c", b"\x1b[>c"):
            if query in self.query_buf:
                self.query_buf = self.query_buf.replace(query, b"", 1)
                replies += b"\x1b[?1;2c"
        return replies


def cli_env() -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL")
        if key in os.environ
    }
    env.update(
        {
            "TERM": "xterm-256color",
            "COLUMNS": str(COLS),
            "LINES": str(ROWS),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(ROOT),
            "PROMPT_TOOLKIT_NO_CPR": "1",
            "LANG": env.get("LANG", "C.UTF-8"),
            "LC_ALL": env.get("LC_ALL", "C.UTF-8"),
        }
    )
    return env


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>TradingAgents 终端</title>
  <style>
    :root { color-scheme: dark; }
    html, body { margin: 0; height: 100%; background: #0d1117; color: #e6edf3; }
    header { padding: 8px 12px; background: #161b22; border-bottom: 1px solid #30363d; }
    h1 { margin: 0; font: 600 16px/1.4 sans-serif; }
    main { height: calc(100vh - 73px); display: flex; flex-direction: column; }
    pre {
      flex: 1;
      margin: 0;
      padding: 8px 12px;
      overflow: auto;
      white-space: pre;
      font: 13px/16px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    textarea {
      height: 36px;
      margin: 0;
      border: 0;
      border-top: 1px solid #30363d;
      background: #010409;
      color: #e6edf3;
      padding: 0 12px;
      resize: none;
      font: 14px/36px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
  </style>
</head>
<body>
  <header><h1>TradingAgents 分析终端</h1></header>
  <main>
    <pre id="screen" role="region" aria-label="TradingAgents 终端"></pre>
    <textarea id="term-input" aria-label="终端输入" placeholder="在此输入，回车确认" autofocus autocomplete="off" spellcheck="false"></textarea>
  </main>
  <script>
    const screen = document.getElementById("screen");
    const input = document.getElementById("term-input");
    async function refresh() {
      try {
        const response = await fetch("/screen");
        if (!response.ok) return;
        screen.textContent = await response.text();
      } catch (error) {
        return;
      }
    }
    refresh();
    setInterval(refresh, 150);
    let queue = Promise.resolve();
    function send(key) {
      queue = queue
        .then(() => fetch("/keys", {
          method: "POST",
          headers: { "Content-Type": "text/plain; charset=utf-8" },
          body: key,
        }))
        .catch(() => {});
    }
    input.addEventListener("keydown", (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      let key = null;
      switch (event.key) {
        case "Enter": key = "\\r"; break;
        case "Backspace": key = "\\x7f"; break;
        case "Tab": key = "\\t"; break;
        case "ArrowUp": key = "\\x1b[A"; break;
        case "ArrowDown": key = "\\x1b[B"; break;
        case "ArrowRight": key = "\\x1b[C"; break;
        case "ArrowLeft": key = "\\x1b[D"; break;
        case "Escape": key = "\\x1b"; break;
        default:
          if (event.key.length === 1) key = event.key;
      }
      if (key === null) return;
      event.preventDefault();
      send(key);
    });
  </script>
</body>
</html>
"""


def session_from_cookie(header: str | None) -> CliSession | None:
    if not header:
        return None
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == "e2e_session" and value:
            with sessions_lock:
                return sessions.get(value)
    return None


def new_session() -> tuple[str, CliSession]:
    sid = uuid.uuid4().hex
    session = CliSession()
    with sessions_lock:
        sessions[sid] = session
    print(f"session {sid} pid={session.proc.pid}", flush=True)
    return sid, session


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send(200, b"ok\n", "text/plain; charset=utf-8")
            return
        if path == "/":
            sid, _session = new_session()
            self._send(
                200,
                PAGE.encode(),
                "text/html; charset=utf-8",
                cookie=f"e2e_session={sid}; Path=/; HttpOnly; SameSite=Lax",
            )
            return
        if path == "/screen":
            session = session_from_cookie(self.headers.get("Cookie"))
            if session is None:
                self._send(404, b"", "text/plain; charset=utf-8")
                return
            session.touch()
            self._send(200, session.text().encode(), "text/plain; charset=utf-8")
            return
        self._send(404, b"not found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/keys":
            self._send(404, b"not found\n", "text/plain; charset=utf-8")
            return
        session = session_from_cookie(self.headers.get("Cookie"))
        if session is None:
            self._send(404, b"", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > 64:
            self._send(400, b"bad length\n", "text/plain; charset=utf-8")
            return
        data = self.rfile.read(length)
        session.touch()
        session.write(data)
        self._send(204, b"", "text/plain; charset=utf-8")

    def _send(self, status: int, body: bytes, content_type: str, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if body:
            self.wfile.write(body)


def reap_idle_sessions() -> None:
    while True:
        time.sleep(2)
        now = time.time()
        stale: list[str] = []
        with sessions_lock:
            for sid, session in sessions.items():
                if now - session.last_seen > IDLE_SECONDS:
                    stale.append(sid)
            closing = [sessions.pop(sid) for sid in stale]
        for session in closing:
            session.close()


def shutdown(signum: int, _frame: object) -> None:
    with sessions_lock:
        running = list(sessions.values())
        sessions.clear()
    for session in running:
        session.close()
    raise SystemExit(128 + signum)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=reap_idle_sessions, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"e2e cli server listening on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
