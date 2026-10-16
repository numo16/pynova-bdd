"""Serve the example site locally and open it with a Python step."""

from __future__ import annotations

import functools
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pytest_bdd import given

from pynova_bdd import NovaSession

SITE = Path(__file__).parent / "site"


@pytest.fixture(scope="session")
def todo_url() -> Iterator[str]:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(SITE))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()


# A Python step definition: it takes precedence over Nova Act for this exact step.
@given("the todo app is open")
def open_todo_app(nova_session: NovaSession, todo_url: str) -> None:
    nova_session.navigate(todo_url)
