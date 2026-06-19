"""30-minute USD/JPY environment report for GitHub Actions + Telegram."""
from __future__ import annotations

import html
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import timedelta, timezone
from pathlib import Path

from bot.analysis import analyze_timeframe, combine
from bot.economic_calendar import safe_fetch_calendar
from bot.tradingview import fetch_candles


ROOT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
STATE_PATH = ROOT / ".bot-state.json"


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def _bias(item):
    return "LONG" if item.score >= 0 else "SHORT"


def _match(item, direction):
    return _bias(item) == direction


def analyze(config):
    analyses = {}
    weights = config["telegram_short_term"]["weights"]
    for timeframe in weights:
        candles = fetch_candles(config["symbol"], timeframe, config["history_bars"])
        analyses[timeframe] = analyze_timeframe(candles, timeframe)
    summary = combine(analyses, weights, 50)
    summary.update(score_environment(summary, analyses))
    return summary, analyses


def score_environment(summary, analyses):
    direction = summary["decision"]
    h1, m15, m5 = analyses["1h"], analyses["15m"], analyses["5m"]
    sign = 1 if direction == "LONG" else -1
    details = {}

    alignment = (10 if _match(h1, direction) else 0) + (7 if _match(m15, direction) else 0) + (5 if _match(m5, direction) else 0)
    if all(_match(x, direction) for x in (h1, m15, m5)):
        alignment += 3
    alignment_notes = f"1h {_bias(h1)} / 15m {_bias(m15)} / 5m {_bias(m5)}"
    if _match(h1, direction) and _match(m15, direction) and not _match(m5, direction):
        alignment_notes += "（5m短期逆行で減点）"
    details["上位足・時間足整合性"] = (alignment, 25, alignment_notes)

    m = m5.metrics
    ema_score = 0; ema_notes = []
    if (m["price"] - m["ema20"]) * sign > 0: ema_score += 4; ema_notes.append("価格とEMA20が順方向")
    stacked = m["ema20"] > m["ema75"] > m["ema200"] if direction == "LONG" else m["ema20"] < m["ema75"] < m["ema200"]
    if stacked: ema_score += 8; ema_notes.append("EMA20/75/200が順配列")
    else: ema_notes.append("EMA順配列は未成立")
    if m["ema20_slope"] * sign > 0 and m["ema75_slope"] * sign > 0: ema_score += 4; ema_notes.append("EMA20・75の傾きが順方向")
    else: ema_notes.append("EMA20または75の傾きが弱い／逆方向")
    zone_low, zone_high = sorted((m["ema20"], m["ema75"]))
    if zone_low - m["atr"] * .25 <= m["price"] <= zone_high + m["atr"] * .25: ema_score += 4; ema_notes.append("EMA20〜75の押し戻り帯")
    if (m["price"] - m["ema200"]) * sign < 0: ema_notes.append("価格がEMA200の逆側")
    if m["ema200_slope"] * sign < 0: ema_notes.append("EMA200が逆方向へ傾斜")
    details["EMA"] = (ema_score, 20, "、".join(ema_notes) or "EMA条件未成立")

    dow_score = 0; dow_notes = []
    for tf, item, points in (("1h", h1, 6), ("15m", m15, 6), ("5m", m5, 4)):
        wanted = "BULLISH" if direction == "LONG" else "BEARISH"
        if item.metrics["dow_trend"] == wanted: dow_score += points
        dow_notes.append(f"{tf}:{item.metrics['dow_label']}")
    bos_key = "bull_bos" if direction == "LONG" else "bear_bos"
    choch_key = "bull_choch" if direction == "LONG" else "bear_choch"
    if m5.metrics[bos_key]: dow_score += 4
    if h1.metrics[bos_key]: dow_score += 3
    if m5.metrics[choch_key]: dow_score += 2
    details["ダウ理論・BOS・CHOCH"] = (dow_score, 25, " / ".join(dow_notes))

    fvg_key = "bull_fvg" if direction == "LONG" else "bear_fvg"
    fvg = m5.metrics[fvg_key]
    fvg_score = 0; fvg_note = "方向一致FVGなし"
    if fvg:
        fvg_score += 3
        if fvg["status"] != "filled": fvg_score += 2
        if fvg["inside"] or fvg["status"] == "touched": fvg_score += 3
        if fvg.get("after_bos"): fvg_score += 2
        fvg_note = f"{fvg['low']:.3f}-{fvg['high']:.3f} / {fvg_status_jp(fvg)}"
    details["FVG"] = (min(fvg_score, 10), 10, fvg_note)

    plan = trade_plan(summary, analyses)
    resistance_score = 10 if not plan["resistance_levels"] else 6 if len(plan["resistance_levels"]) == 1 else 3
    if plan["near_round"]: resistance_score = max(0, resistance_score - 2)
    details["レジサポ・抵抗余地"] = (resistance_score, 10, plan["resistance_note"])

    atr_score = 4
    if plan["tp_atr"] <= 2.5: atr_score += 3
    elif plan["tp_atr"] <= 3.1: atr_score += 1
    if not plan["resistance_levels"]: atr_score += 3
    details["ATR・RR妥当性"] = (atr_score, 10, f"RR 1:2、TPはATR {plan['tp_atr']:.1f}倍先")

    total = max(0, min(100, sum(value[0] for value in details.values())))
    if total <= 54: rating = "見送り"
    elif total <= 59: rating = "監視"
    elif total <= 69: rating = "条件付きエントリー候補"
    elif total <= 79: rating = "強め候補"
    else: rating = "かなり強い"
    confidence = summary["signal_confidence"]
    if confidence <= 55: bias_rating = "弱い・見送り寄り"
    elif confidence < 60: bias_rating = "監視"
    elif confidence < 70: bias_rating = "条件付きエントリー候補"
    else: bias_rating = "強め"
    return {"total_score": total, "rating": rating, "bias_rating": bias_rating,
            "score_breakdown": details, "trade_plan": plan}


def fvg_status_jp(zone):
    if zone["inside"]: return "現在価格がFVG内"
    return {"untouched": "未タッチ", "touched": "タッチ済み", "filled": "埋め済み"}.get(zone["status"], zone["status"])


def fvg_text(zone):
    return "該当なし" if not zone else f"{zone['low']:.3f}-{zone['high']:.3f}（{fvg_status_jp(zone)}）"


def _levels_between(price, target, levels, direction):
    if direction == "LONG": return sorted({x for x in levels if price < x < target})
    return sorted({x for x in levels if target < x < price}, reverse=True)


def trade_plan(summary, analyses):
    direction = summary["decision"]
    m5, h1 = analyses["5m"], analyses["1h"]
    m = m5.metrics; hm = h1.metrics
    price = summary["entry_price"]; atr = m["atr"]
    target = summary["take_profit_price"]
    tp_atr = abs(target - price) / atr if atr else 0
    if direction == "LONG":
        candidates = [m["last_swing_high"], m["range_high"], hm["last_swing_high"], hm["range_high"], m["round_above"]]
        invalidation = m["last_swing_low"]
        trigger = m["last_swing_high"]
        pullback = f"EMA20 {m['ema20']:.3f}〜EMA75 {m['ema75']:.3f}付近への押し目＋陽線確定"
    else:
        candidates = [m["last_swing_low"], m["range_low"], hm["last_swing_low"], hm["range_low"], m["round_below"]]
        invalidation = m["last_swing_high"]
        trigger = m["last_swing_low"]
        pullback = f"EMA20 {m['ema20']:.3f}〜EMA75 {m['ema75']:.3f}付近への戻り＋陰線確定"
    resistance = _levels_between(price, target, candidates, direction)
    near_round = abs(price - (m["round_above"] if direction == "LONG" else m["round_below"])) <= atr * .5
    resistance_note = "TPまで明確な抵抗帯なし" if not resistance else "TPまで: " + ", ".join(f"{x:.3f}" for x in resistance[:4])
    fvg = m["bull_fvg" if direction == "LONG" else "bear_fvg"]
    fvg_wait = bool(fvg and (fvg["inside"] or fvg["status"] in ("untouched", "touched")))
    return {"trigger": trigger, "invalidation": invalidation, "pullback": pullback,
            "tp_atr": tp_atr, "resistance_levels": resistance, "resistance_note": resistance_note,
            "near_round": near_round, "fvg_wait": fvg_wait}


def _event_lines(calendar):
    lines = []
    for event in calendar.get("danger", []):
        clock = event["time"].astimezone(JST).strftime("%H:%M")
        lines.append(f"⛔ {event['currency']} {html.escape(event['title'])}（{clock} JST）")
    return lines


def _outlook(summary, analyses):
    direction = summary["decision"]
    h1, m5 = analyses["1h"], analyses["5m"]
    if _match(h1, direction) and not _match(m5, direction):
        return "押し目待ち" if direction == "LONG" else "戻り待ち"
    return "買い寄り" if direction == "LONG" else "売り寄り"


def normal_message(summary, analyses, calendar=None):
    direction = summary["decision"]; plan = summary["trade_plan"]
    h1, m5 = analyses["1h"], analyses["5m"]
    icon = "🟢" if direction == "LONG" else "🔴"
    arrow = "↑" if direction == "LONG" else "↓"
    invalid_arrow = "↓" if direction == "LONG" else "↑"
    return (
        f"{icon} <b>USD/JPY {_outlook(summary, analyses)}</b>\n\n"
        f"価格：<code>{summary['entry_price']:.3f}</code>\n\n"
        f"1h：{_bias(h1)}\n"
        f"5m：{_bias(m5)}\n\n"
        f"<b>注目価格</b>\n"
        f"{arrow}<code>{plan['trigger']:.3f}</code>で{'買い' if direction == 'LONG' else '売り'}候補\n"
        f"{invalid_arrow}<code>{plan['invalidation']:.3f}</code>で無効\n\n"
        f"TP：<code>{summary['take_profit_price']:.3f}</code>\n"
        f"SL：<code>{summary['stop_price']:.3f}</code>\n"
    )


def strong_message(summary, analyses, calendar=None):
    direction = summary["decision"]; plan = summary["trade_plan"]
    h1, m15, m5 = analyses["1h"], analyses["15m"], analyses["5m"]
    side = "ロング" if direction == "LONG" else "ショート"
    bos_key = "bull_bos" if direction == "LONG" else "bear_bos"
    choch_key = "bull_choch" if direction == "LONG" else "bear_choch"
    fvg = m5.metrics["bull_fvg" if direction == "LONG" else "bear_fvg"]
    ema_ok = summary["score_breakdown"]["EMA"][0] >= 12
    event_lines = _event_lines(calendar or {"danger": []})
    event_warning = (" / ".join(event_lines) + "のため新規見送り") if event_lines else ""
    return (
        f"🔥 <b>USD/JPY 強{side}候補</b>\n\n"
        f"スコア：<b>{summary['total_score']}/100</b>\n\n"
        f"<b>根拠</b>\n"
        f"・1h {_bias(h1)}\n・15m {_bias(m15)}\n・5m {_bias(m5)}\n"
        f"・BOS：{'発生' if m5.metrics[bos_key] or h1.metrics[bos_key] else '未発生'}\n"
        f"・CHOCH：{'発生' if m5.metrics[choch_key] else '未発生'}\n"
        f"・EMA：{'順行' if ema_ok else '未整合'}\n"
        f"・FVG：{fvg_text(fvg)}\n\n"
        f"<b>エントリー条件</b>\n"
        f"<code>{plan['trigger']:.3f}</code>{'上' if direction == 'LONG' else '下'}抜け確定後\n\n"
        f"TP：<code>{summary['take_profit_price']:.3f}</code>\n"
        f"SL：<code>{summary['stop_price']:.3f}</code>\n\n"
        f"<b>注意</b>\n飛び乗り禁止\nローソク足確定待ち\n"
        + (f"{event_warning}\n" if event_warning else "")
    )


def read_state():
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {"direction": None, "strong_at": 0}


def write_state(state):
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def choose_notification(summary, calendar, slot, now=None, forced="auto"):
    now = int(now or time.time())
    score = summary["total_score"]
    if forced in ("normal", "strong"): return forced
    if score < 55: return None
    if calendar.get("danger"):
        return "normal" if slot in (0, 30) else None
    if score < 70:
        return "normal" if slot in (0, 30) else None
    state = read_state()
    if state.get("direction") == summary["decision"] and now - int(state.get("strong_at", 0)) < 30 * 60:
        return None
    return "strong"


def send_telegram(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "HTML"}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"): raise RuntimeError(f"Telegram API error: {payload}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id: raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    config = load_config()
    summary, analyses = analyze(config)
    calendar = safe_fetch_calendar(config["economic_calendar"])
    try: slot = int(os.environ.get("NOTIFICATION_SLOT", "0"))
    except ValueError: slot = 0
    forced = os.environ.get("NOTIFICATION_MODE", "auto").strip().lower()
    mode = choose_notification(summary, calendar, slot, forced=forced)
    write_state(read_state())  # Ensure the Actions cache always has a file to save.
    if mode == "normal":
        send_telegram(token, chat_id, normal_message(summary, analyses, calendar))
        print("Normal environment notification sent")
    elif mode == "strong":
        send_telegram(token, chat_id, strong_message(summary, analyses, calendar))
        write_state({"direction": summary["decision"], "strong_at": int(time.time())})
        print("Strong signal notification sent")
    else:
        print(f"No notification: score={summary['total_score']} slot={slot}")


if __name__ == "__main__": main()
