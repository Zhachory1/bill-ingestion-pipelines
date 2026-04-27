"""Session-scoped live-server fixture for Playwright E2E tests.

Starts the FastAPI app on a free port using a SQLite in-memory database so
Postgres is not required.  Tests intercept API calls at the network level via
page.route(), so the DB being empty is fine.
"""

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def live_server():
    """Start the FastAPI app on a free port for the entire test session."""
    # Point to SQLite so the server boots without a running Postgres instance.
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

    port = _free_port()

    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait up to 5 s for the server to accept connections.
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(base_url + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield base_url

    server.should_exit = True
