"""One-shot USD/JPY analysis for GitHub Actions + Telegram."""
from __future__ import annotations

import html
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from bot.analysis import analyze_timeframe, combine
from bot.tradingview import fetch_candles


ROOT = Path(__file__).resolve().parent
def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def analyze(config):
    analyses = {}
    weights = config["telegram_short_term"]["weights"]
    for timeframe in weights:
        candles = fetch_candles(config["symbol"], timeframe, config["history_bars"])
        analyses[timeframe] = analyze_timeframe(candles, timeframe)
    summary = combine(analyses, weights, 50)
    summary["weak"] = summary["signal_confidence"] < float(config["telegram_short_term"]["weak_threshold"])
    return summary, analyses


def telegram_message(summary, analyses):
    direction = summary["decision"]
    confidence = summary["long_percent"] if direction == "LONG" else summary["short_percent"]
    icon = "🟢" if direction == "LONG" else "🔴"
    side = "買い" if direction == "LONG" else "売り"
    strength = "⚠️ 判断は弱めです" if summary["weak"] else "判断強度は通常以上です"
    tf_lines = "\n".join(
        f"• {html.escape(tf)}: {item.direction} ({item.score:+.1f})"
        for tf, item in analyses.items()
    )
    return (
        f"{icon} <b>USD/JPY 短期目線：{side} ({direction})</b>\n\n"
        f"LONG {summary['long_percent']:.1f}% / SHORT {summary['short_percent']:.1f}%\n"
        f"優勢度: <b>{confidence:.1f}%</b>\n"
        f"{strength}\n\n"
        f"現在価格: <code>{summary['entry_price']:.3f}</code>\n"
        f"エントリー目安: <code>{summary['entry_price']:.3f}</code>\n"
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
    send_telegram(token, chat_id, telegram_message(summary, analyses))
    print("30-minute Telegram report sent")


if __name__ == "__main__":
    main()
