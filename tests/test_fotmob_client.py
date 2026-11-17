"""Tests for FotMob HTTP client retry behavior."""

from __future__ import annotations

import http.client
from pathlib import Path

from src.scrape import fotmob_client
from src.scrape.fotmob_client import FotMobClient


def test_remote_disconnected_is_retried_and_cached(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(fotmob_client.time, "sleep", lambda _: None)
    client = FotMobClient(tmp_path)
    calls = 0

    def fake_request(url: str):  # noqa: ANN202, ARG001
        nonlocal calls
        calls += 1
        if calls == 1:
            raise http.client.RemoteDisconnected("peer closed connection")
        return {"id": 42, "name": "Ok"}

    monkeypatch.setattr(client, "_request", fake_request)

    payload = client.player(42)
    assert payload["id"] == 42
    assert calls == 2
