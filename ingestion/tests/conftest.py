"""Shared test fixtures (pytest loads conftest.py automatically for every test in this folder)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeClock:
    """Fake time: sleep() records the wait and moves the clock forward instantly."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


class ScriptedHandler(BaseHTTPRequestHandler):
    """Answers each path with the next (status, body) from its script; the last one repeats."""

    def do_GET(self):
        self._answer()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.bodies.append(self.rfile.read(length))
        self._answer()

    def _answer(self):
        self.server.requests.append({"path": self.path, "headers": dict(self.headers)})
        script = self.server.scripts.get(self.path.split("?")[0], [(404, b"not found")])
        status, body = script.pop(0) if len(script) > 1 else script[0]
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture
def http_server():
    """A real HTTP server on localhost, so fetcher tests never touch the internet."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHandler)  # port 0 = any free port
    server.scripts = {}  # path -> list of (status, body) answers, set by each test
    server.requests = []  # every request received, in order
    server.bodies = []  # POST bodies received
    server.base_url = f"http://127.0.0.1:{server.server_port}"
    # poll_interval: how often serve_forever checks for shutdown (default 0.5 s slows every test)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
