"""Record real agent responses once; replay them in tests.

Recording runs the real orchestrator against the live services and saves every
agent call it makes (tests/record_fixtures.py). Replay serves those responses
back through an httpx transport, so adapter, fusion and API tests exercise
real agent output with no data, no network and no running services.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

import httpx

from app.config import load_agents

FIXTURES = Path(__file__).parent / "fixtures" / "recorded.json"
_AGENT_BY_NETLOC = {urlsplit(cfg.base_url).netloc: name for name, cfg in load_agents().items()}


def request_key(request: httpx.Request) -> str:
    agent = _AGENT_BY_NETLOC.get(request.url.netloc.decode() if isinstance(request.url.netloc, bytes) else request.url.netloc, request.url.host)
    query = "&".join(sorted(f"{k}={v}" for k, v in request.url.params.multi_items()))
    key = f"{agent} {request.method} {request.url.path}"
    if query:
        key += f"?{query}"
    if request.content:
        try:
            key += " " + json.dumps(json.loads(request.content), sort_keys=True)
        except ValueError:
            key += " <binary>"
    return key


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.records: dict[str, dict] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        content = await response.aread()
        try:
            payload = json.loads(content)
        except ValueError:
            payload = None
        self.records[request_key(request)] = {"status": response.status_code, "json": payload}
        return httpx.Response(response.status_code, headers=response.headers, content=content, request=request)


class ReplayTransport(httpx.AsyncBaseTransport):
    """Serves recorded responses. Agents in ``down`` refuse connections;
    agents in ``slow`` stall for ``delay`` seconds first; ``responses`` replaces
    individual recorded responses."""

    def __init__(self, records: dict, down: Iterable[str] = (), slow: Iterable[str] = (), delay: float = 5.0, responses: Optional[dict] = None):
        self.records = records
        self.down, self.slow, self.delay = set(down), set(slow), delay
        self.responses = responses or {}
        self.missing: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = request_key(request)
        agent = key.split(" ", 1)[0]
        if agent in self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if agent in self.slow:
            await asyncio.sleep(self.delay)
        record = self.responses.get(key) or self.records.get(key)
        if record is None:
            self.missing.append(key)
            return httpx.Response(404, json={"detail": f"no fixture for {key}"}, request=request)
        return httpx.Response(record["status"], json=record["json"], request=request)


def load_records() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))
