"""Shared Chrome DevTools Protocol helpers for the LabAuth browser tests.

Every browser is launched on its own free port in its own process group and torn
down by killing that whole group. Fixed ports plus a plain ``terminate()`` used
to leak headless browsers that kept holding the debugging port, so a later run
silently attached to a zombie browser from an earlier run.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.request

import websockets

BROWSER_CANDIDATES = (
    "brave-browser",
    "chromium",
    "google-chrome",
    "chromium-browser",
    "brave",
)


def free_port() -> int:
    """Reserve an ephemeral port that is free right now."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_browser() -> str:
    for name in BROWSER_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("No Chromium-based browser found on PATH")


class CDPClient:
    """Minimal Chrome DevTools Protocol client."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0

    async def connect(self) -> "CDPClient":
        self.ws = await websockets.connect(self.ws_url, max_size=None)
        return self

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def send_command(self, method: str, params: dict | None = None):
        self._msg_id += 1
        message_id = self._msg_id
        assert self.ws is not None
        await self.ws.send(
            json.dumps({"id": message_id, "method": method, "params": params or {}})
        )
        while True:
            data = json.loads(await self.ws.recv())
            if data.get("id") == message_id:
                return data.get("result", {})

    async def evaluate(self, expression: str):
        result = await self.send_command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        value = result.get("result", {})
        return value["value"] if "value" in value else result

    async def screenshot(self, path: str) -> str:
        result = await self.send_command("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as handle:
            handle.write(base64.b64decode(result["data"]))
        return path


class Browser:
    """A headless browser bound to its own port and process group."""

    def __init__(self, url: str, *, width: int = 1440, height: int = 900):
        self.url = url
        self.width = width
        self.height = height
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.ws_url: str | None = None

    def __enter__(self) -> "Browser":
        self.proc = subprocess.Popen(
            [
                find_browser(),
                "--headless=new",
                "--disable-gpu",
                f"--window-size={self.width},{self.height}",
                f"--remote-debugging-port={self.port}",
                self.url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Own process group so we can reliably reap the whole browser tree.
            start_new_session=True,
        )
        self._wait_for_target()
        return self

    def _wait_for_target(self, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/list", timeout=2
                ) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                for target in targets:
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        self.ws_url = target["webSocketDebuggerUrl"]
                        return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(0.25)
        raise RuntimeError(f"Browser never exposed a CDP page target: {last_error}")

    async def page(self) -> CDPClient:
        assert self.ws_url, "Browser was not started"
        return await CDPClient(self.ws_url).connect()

    def __exit__(self, *exc_info) -> bool:
        if self.proc is not None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            try:
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None
        return False


async def wait_for(client: CDPClient, expression: str, timeout: float = 15.0):
    """Poll a boolean JS expression until it is truthy; return its value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = await client.evaluate(expression)
        if value:
            return value
        await asyncio.sleep(0.15)
    return None