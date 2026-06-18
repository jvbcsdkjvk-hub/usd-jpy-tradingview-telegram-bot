"""One-shot USD/JPY analysis for GitHub Actions + Telegram."""
from __future__ import annotations

import html
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from bot.analysis import analyze_timeframe, combine
from bot.tradingview import fetch_candles


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".bot-state.json"


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def analyze(config):
    analyses = {}
    for timeframe, settings in config["timeframes"].items():
        if not settings.get("enabled", True):
            continue
        candles = fetch_candles(config["symbol"], timeframe, config["history_bars"])
        analyses[timeframe] = analyze_timeframe(candles, timeframe)
    weights = {tf: settings["weight"] for tf, settings in config["timeframes"].items()}
    return combine(analyses, weights, float(config["signal_threshold"])), analyses


def read_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"direction": None, "notified_at": 0}


def save_state(direction, timestamp):
    STATE_PATH.write_text(json.dumps({"direction": direction, "notified_at": timestamp}), encoding="utf-8")


def should_notify(summary, config, now):
    if summary["decision"] == "WAIT":
        return False
    previous = read_state()
    cooldown = int(config["cooldown_minutes"]) * 60
    return previous.get("direction") != summary["decision"] or now - previous.get("notified_at", 0) >= cooldown


def telegram_message(summary, analyses):
    direction = summary["decision"]
    confidence = summary["long_percent"] if direction == "LONG" else summary["short_percent"]
    icon = "🟢" if direction == "LONG" else "🔴"
    tf_lines = "\n".join(
        f"• {html.escape(tf)}: {item.direction} ({item.score:+.1f})"
        for tf, item in analyses.items()
    )
    return (
        f"{icon} <b>USD/JPY {direction}候補</b>\n\n"
        f"LONG {summary['long_percent']:.1f}% / SHORT {summary['short_percent']:.1f}%\n"
        f"判定確度: <b>{confidence:.1f}%</b>\n\n"
        f"エントリー: <code>{summary['entry_price']:.3f}</code>\n"
        f"利確: <code>{summary['take_profit_price']:.3f}</code>\n"
        f"損切り: <code>{summary['stop_price']:.3f}</code>\n"
        f"RR: 1:2\n\n"
        f"<b>時間足</b>\n{tf_lines}\n\n"
        "分析支援用の参考シグナルです。"
    )


def send_telegram(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "HTML"}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    config = load_config()
    summary, analyses = analyze(config)
    print(json.dumps(summary, ensure_ascii=False))
    now = int(time.time())
    if should_notify(summary, config, now):
        send_telegram(token, chat_id, telegram_message(summary, analyses))
        save_state(summary["decision"], now)
        print("Telegram notification sent")
    else:
        print("No notification: WAIT or cooldown active")


if __name__ == "__main__":
    main()

