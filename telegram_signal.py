"""30-minute USD/JPY environment report for GitHub Actions + Telegram."""
from __future__ import annotations

import html
import json
import os
import urllib.parse
import urllib.request
from datetime import timedelta, timezone
from pathlib import Path

from bot.analysis import analyze_timeframe, combine
from bot.economic_calendar import safe_fetch_calendar
from bot.tradingview import fetch_candles


ROOT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


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


def telegram_message(summary, analyses, calendar=None):
    calendar = calendar or {"danger": [], "upcoming": [], "error": None}
    direction = summary["decision"]; plan = summary["trade_plan"]
    h1, m15, m5 = analyses["1h"], analyses["15m"], analyses["5m"]
    icon = "🟢" if direction == "LONG" else "🔴"
    if _match(h1, direction) and not _match(m5, direction):
        outlook = "押し目待ち" if direction == "LONG" else "戻り待ち"
    else:
        outlook = "買い寄り" if direction == "LONG" else "売り寄り"
    if calendar["danger"]:
        verdict = "重要指標時間帯のため新規エントリー見送り"
    else:
        verdict = summary["rating"]
    bos_key = "bull_bos" if direction == "LONG" else "bear_bos"
    choch_key = "bull_choch" if direction == "LONG" else "bear_choch"
    fvg = m5.metrics["bull_fvg" if direction == "LONG" else "bear_fvg"]
    round_number = m5.metrics["round_above"] if direction == "LONG" else m5.metrics["round_below"]
    breakdown = "\n".join(f"・{name}：{value[0]}/{value[1]}（{html.escape(value[2])}）" for name,value in summary["score_breakdown"].items())
    event_lines = _event_lines(calendar)
    event_block = ("\n".join(event_lines) + "\n") if event_lines else ""
    if calendar.get("error"): event_block += "⚠️ 経済指標カレンダー取得失敗。手動確認必須。\n"
    action_warning = "FVG反発確認待ち。" if plan["fvg_wait"] else "反発確認待ち。"
    return (
        f"{icon} <b>USD/JPY 短期目線：{outlook}</b>\n\n"
        f"LONG {summary['long_percent']:.1f}% / SHORT {summary['short_percent']:.1f}%\n"
        f"方向優勢度評価：{summary['bias_rating']}\n"
        f"総合評価：<b>{summary['total_score']}点</b>\n"
        f"判定：{verdict}。即エントリー非推奨。\n"
        f"{event_block}\n"
        f"現在価格：<code>{summary['entry_price']:.3f}</code>\n"
        f"<b>エントリー条件：</b>\n"
        f"・条件A：5m {'高値' if direction == 'LONG' else '安値'} <code>{plan['trigger']:.3f}</code> {'上' if direction == 'LONG' else '下'}抜けをローソク足確定で確認\n"
        f"・条件B：{plan['pullback']}\n"
        f"・共通：{action_warning}損切り位置確認必須\n\n"
        f"利確候補：<code>{summary['take_profit_price']:.3f}</code>\n"
        f"損切り：<code>{summary['stop_price']:.3f}</code>（5m ATR×1.5）\n"
        f"RR：1:2\n\n"
        f"<b>根拠：</b>\n"
        f"・1h：{_bias(h1)} / {html.escape(h1.metrics['dow_label'])}\n"
        f"・15m：{_bias(m15)} / {html.escape(m15.metrics['dow_label'])}\n"
        f"・5m：{_bias(m5)} / {html.escape(m5.metrics['dow_label'])}\n"
        f"・EMA：20 {m5.metrics['ema20']:.3f} / 75 {m5.metrics['ema75']:.3f} / 200 {m5.metrics['ema200']:.3f}\n"
        f"・5m CHOCH：{'発生' if m5.metrics[choch_key] else '未発生'}\n"
        f"・5m BOS：{'発生' if m5.metrics[bos_key] else '未発生'} / 1h BOS：{'発生' if h1.metrics[bos_key] else '未発生'}\n"
        f"・5m転換価格：<code>{plan['trigger']:.3f}</code>\n"
        f"・上昇FVG：{fvg_text(m5.metrics['bull_fvg'])}\n"
        f"・下降FVG：{fvg_text(m5.metrics['bear_fvg'])}\n"
        f"・ATR：{m5.metrics['atr']:.3f} / TPはATR {plan['tp_atr']:.1f}倍先\n\n"
        f"<b>レジサポ：</b>\n"
        f"・直近高値：<code>{m5.metrics['last_swing_high']:.3f}</code> / 直近安値：<code>{m5.metrics['last_swing_low']:.3f}</code>\n"
        f"・レンジ上限：<code>{m5.metrics['range_high']:.3f}</code> / レンジ下限：<code>{m5.metrics['range_low']:.3f}</code>\n"
        f"・ラウンドナンバー：<code>{round_number:.3f}</code>\n"
        f"・{plan['resistance_note']}\n\n"
        f"<b>スコア内訳：</b>\n{breakdown}\n\n"
        f"<b>警戒：</b>\n"
        f"・5mが逆方向なら飛び乗り注意\n"
        f"・直近{'安値' if direction == 'LONG' else '高値'} <code>{plan['invalidation']:.3f}</code> {'割れ' if direction == 'LONG' else '超え'}で見送り\n"
        f"・{plan['resistance_note']}\n"
        f"・重要指標前60分〜発表後30分はロット低下ではなく新規見送り\n\n"
        f"<b>注目価格：</b>\n"
        f"・{'上' if direction == 'LONG' else '下'}抜けで伸びそう：<code>{plan['trigger']:.3f}</code>\n"
        f"・割れたら見送り：<code>{plan['invalidation']:.3f}</code>\n"
        f"・押し戻り候補：EMA20〜EMA75\n"
    )


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
    print(json.dumps({"summary": summary, "calendar_error": calendar["error"]}, ensure_ascii=False, default=str))
    send_telegram(token, chat_id, telegram_message(summary, analyses, calendar))
    print("30-minute environment report sent")


if __name__ == "__main__": main()
