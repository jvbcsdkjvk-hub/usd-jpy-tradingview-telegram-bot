"""Small read-only TradingView chart data client.

TradingView does not publish this websocket as a stable public API. The client is
therefore isolated here so a future data-provider replacement does not affect the
analysis engine.
"""
from __future__ import annotations

import json
import random
import string
import time
from typing import Any

import websocket

from .models import Candle


class TradingViewError(RuntimeError):
    pass


TV_INTERVALS = {"5m": "5", "1h": "60", "4h": "240", "1d": "1D"}


def _session(prefix: str) -> str:
    tail = "".join(random.choice(string.ascii_lowercase) for _ in range(12))
    return f"{prefix}_{tail}"


def _frame(method: str, params: list[Any]) -> str:
    raw = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(raw)}~m~{raw}"


def _messages(packet: str):
    cursor = 0
    marker = "~m~"
    while cursor < len(packet):
        start = packet.find(marker, cursor)
        if start < 0:
            break
        length_end = packet.find(marker, start + len(marker))
        if length_end < 0:
            break
        try:
            size = int(packet[start + len(marker):length_end])
        except ValueError:
            cursor = length_end + len(marker)
            continue
        payload_start = length_end + len(marker)
        payload = packet[payload_start:payload_start + size]
        cursor = payload_start + size
        if payload.startswith("{"):
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue


def fetch_candles(symbol: str, timeframe: str, count: int = 500, timeout: int = 18) -> list[Candle]:
    if timeframe not in TV_INTERVALS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    chart = _session("cs")
    url = "wss://data.tradingview.com/socket.io/websocket?from=symbols%2FUSDJPY%2F"
    try:
        ws = websocket.create_connection(
            url,
            timeout=timeout,
            origin="https://data.tradingview.com",
            cookie="",
            header=["User-Agent: Mozilla/5.0"],
        )
        ws.send(_frame("set_auth_token", ["unauthorized_user_token"]))
        ws.send(_frame("chart_create_session", [chart, ""]))
        descriptor = "=" + json.dumps(
            {"symbol": symbol, "adjustment": "splits", "session": "regular"},
            separators=(",", ":"),
        )
        ws.send(_frame("resolve_symbol", [chart, "symbol_1", descriptor]))
        ws.send(_frame("create_series", [chart, "s1", "s1", "symbol_1", TV_INTERVALS[timeframe], count]))

        deadline = time.time() + timeout
        bars: dict[int, Candle] = {}
        seen: list[str] = []
        while time.time() < deadline:
            packet = ws.recv()
            if packet.startswith("~m~") and "~h~" in packet:
                ws.send(packet)
                continue
            for message in _messages(packet):
                seen.append(str(message.get("m") or message.get("session_id") or "message"))
                if message.get("m") == "critical_error":
                    raise TradingViewError(str(message.get("p", "TradingView error")))
                if message.get("m") == "timescale_update":
                    payload = message.get("p", [{}, {}])[1]
                    series = payload.get("s1", {}) if isinstance(payload, dict) else {}
                    for row in series.get("s", []):
                        values = row.get("v", [])
                        if len(values) >= 5 and values[0] is not None:
                            offset = 0 if float(values[0]) > 1_000_000_000 else 1
                            if len(values) < offset + 5:
                                continue
                            candle = Candle(
                                time=int(values[offset]), open=float(values[offset + 1]), high=float(values[offset + 2]),
                                low=float(values[offset + 3]), close=float(values[offset + 4]),
                                volume=float(values[offset + 5] or 0) if len(values) > offset + 5 else 0.0,
                            )
                            bars[candle.time] = candle
                if message.get("m") == "series_completed" and bars:
                    ws.close()
                    return sorted(bars.values(), key=lambda x: x.time)
        ws.close()
        if bars:
            return sorted(bars.values(), key=lambda x: x.time)
        raise TradingViewError("No candle data returned (messages: " + ", ".join(seen[-12:]) + ")")
    except TradingViewError:
        raise
    except Exception as exc:
        raise TradingViewError(f"TradingView connection failed: {exc}") from exc
