from __future__ import annotations

import json
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

from .analysis import analyze_timeframe, combine
from .tradingview import fetch_candles


def local_ipv4():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


class SignalService:
    def __init__(self, config_path: Path):
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.lan_url = f"http://{local_ipv4()}:{self.config['port']}"
        self.lock = threading.Lock()
        self.state = {"status": "starting", "updated_at": None, "error": None, "result": None,
                      "charts": {}, "lan_url": self.lan_url}
        self.stop_event = threading.Event()
        self.last_notification = {"key": None, "time": 0.0}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state, ensure_ascii=False))

    def refresh(self):
        analyses = {}; charts = {}; errors = []
        for timeframe, settings in self.config["timeframes"].items():
            if not settings.get("enabled", True): continue
            try:
                candles = fetch_candles(self.config["symbol"], timeframe, self.config["history_bars"])
                analyses[timeframe] = analyze_timeframe(candles, timeframe)
                charts[timeframe] = [{"t": x.time, "c": x.close} for x in candles[-120:]]
            except Exception as exc:
                errors.append(f"{timeframe}: {exc}")
        if not analyses:
            raise RuntimeError("全時間足の取得に失敗しました: " + " / ".join(errors))
        weights = {tf: value["weight"] for tf, value in self.config["timeframes"].items()}
        summary = combine(analyses, weights, float(self.config["signal_threshold"]))
        result = {"summary": summary, "timeframes": {tf: vars(value) for tf, value in analyses.items()}}
        with self.lock:
            self.state = {"status": "ok" if not errors else "partial", "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                          "error": " / ".join(errors) if errors else None, "result": result, "charts": charts,
                          "lan_url": self.lan_url}
        self._notify(summary)

    def _notify(self, summary):
        if summary["decision"] == "WAIT" or summary["signal_confidence"] < self.config["notify_threshold"]: return
        key = f"{summary['decision']}:{round(summary['price'], 2)}"
        cooldown = self.config["cooldown_minutes"] * 60
        if self.last_notification["key"] == key and time.time() - self.last_notification["time"] < cooldown: return
        try:
            from plyer import notification
            notification.notify(title=f"USD/JPY {summary['decision']}候補", message=f"確度 {summary['signal_confidence']:.1f}% / 価格 {summary['entry_price']:.3f}", timeout=10)
        except Exception:
            pass
        self.last_notification = {"key": key, "time": time.time()}

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.refresh()
            except Exception as exc:
                with self.lock:
                    self.state.update(status="error", error=str(exc), updated_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            self.stop_event.wait(max(15, int(self.config["refresh_seconds"])))
