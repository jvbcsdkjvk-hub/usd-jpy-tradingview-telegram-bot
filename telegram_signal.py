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
    side = "買い寄り" if direction == "LONG" else "売り寄り"
    strength = "弱め" if summary["weak"] else "通常以上"
    verdict = f"弱い{'買い' if direction == 'LONG' else '売り'}。即エントリー非推奨。" if summary["weak"] else f"{'買い' if direction == 'LONG' else '売り'}優勢。条件成立後のエントリーを検討。"
    plan = trade_plan(summary, analyses)
    h1 = analyses["1h"]; m5 = analyses["5m"]
    h1_side = "LONG" if h1.score >= 0 else "SHORT"
    m5_side = "LONG" if m5.score >= 0 else "SHORT"
    adjustment = "で短期調整中" if h1_side != m5_side else "で方向一致"
    return (
        f"{icon} <b>USD/JPY 短期目線：{side}（{strength}）</b>\n"
        f"LONG {summary['long_percent']:.1f}% / SHORT {summary['short_percent']:.1f}%\n"
        f"優勢度：<b>{confidence:.1f}%</b>\n"
        f"判定：{verdict}\n\n"
        f"現在価格：<code>{summary['entry_price']:.3f}</code>\n"
        f"エントリー目安：{plan['entry']}\n"
        f"利確候補：<code>{summary['take_profit_price']:.3f}</code>（ATR {plan['tp_atr']:.1f}倍先：{plan['tp_assessment']}）\n"
        f"損切り：<code>{summary['stop_price']:.3f}</code>（5分足ATR×1.5）\n\n"
        f"<b>根拠：</b>\n"
        f"・1hは{h1_side}／ダウ理論：{html.escape(h1.metrics['dow_label'])}\n"
        f"・5mは{m5_side}{adjustment}／ダウ理論：{html.escape(m5.metrics['dow_label'])}\n"
        f"・RR 1:2\n"
        f"・{plan['timing']}\n\n"
        f"<b>警戒：</b>\n"
        f"・{plan['chase_warning']}\n"
        f"・{plan['invalidation']}\n"
        f"・{plan['opposition']}\n\n"
        "分析支援用の参考シグナルです。"
    )


def trade_plan(summary, analyses):
    m5 = analyses["5m"]
    h1 = analyses["1h"]
    price = summary["entry_price"]
    atr = m5.metrics["atr"]
    tp_atr = abs(summary["take_profit_price"] - price) / atr if atr else 0
    if tp_atr <= 2:
        tp_assessment = "平均値幅に対して無理の少ない範囲"
    elif tp_atr <= 3.1:
        tp_assessment = "やや遠め。値幅拡大を確認"
    else:
        tp_assessment = "遠い目標。分割利確を推奨"
    m5_high = m5.metrics["last_swing_high"]
    m5_low = m5.metrics["last_swing_low"]
    h1_high = h1.metrics["last_swing_high"]
    h1_low = h1.metrics["last_swing_low"]
    ema20 = m5.metrics["ema20"]
    m5_side = "LONG" if m5.score >= 0 else "SHORT"
    if summary["decision"] == "LONG":
        return {
            "entry": f"5m高値 {m5_high:.3f} の上抜け確定後、またはEMA20 {ema20:.3f}付近への押し目を検討",
            "tp_atr": tp_atr,
            "tp_assessment": tp_assessment,
            "timing": "5mの上昇転換待ち" if m5_side == "SHORT" else "高値更新後の押し目待ち",
            "chase_warning": "5mがSHORTのため飛び乗り注意" if m5_side == "SHORT" else "高値追いの飛び乗り注意",
            "invalidation": f"5m直近安値 {m5_low:.3f} 割れなら買いは見送り",
            "opposition": f"1h直近高値 {h1_high:.3f} 付近の売り戻しに注意",
        }
    return {
        "entry": f"5m安値 {m5_low:.3f} の下抜け確定後、またはEMA20 {ema20:.3f}付近への戻りを検討",
        "tp_atr": tp_atr,
        "tp_assessment": tp_assessment,
        "timing": "5mの下降転換待ち" if m5_side == "LONG" else "安値更新後の戻り待ち",
        "chase_warning": "5mがLONGのため飛び乗り注意" if m5_side == "LONG" else "安値追いの飛び乗り注意",
        "invalidation": f"5m直近高値 {m5_high:.3f} 超えなら売りは見送り",
        "opposition": f"1h直近安値 {h1_low:.3f} 付近の買い戻しに注意",
    }


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
