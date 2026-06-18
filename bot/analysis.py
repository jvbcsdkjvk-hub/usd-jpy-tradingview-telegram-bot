from __future__ import annotations

import math
from statistics import mean, pstdev

from .models import Candle, TimeframeAnalysis


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def rsi(values: list[float], period: int = 14) -> list[float]:
    if len(values) < 2:
        return [50.0] * len(values)
    gains = [0.0]
    losses = [0.0]
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0.0)); losses.append(max(-change, 0.0))
    avg_gain = ema(gains, period); avg_loss = ema(losses, period)
    return [100.0 if loss == 0 else 100 - 100 / (1 + gain / loss) for gain, loss in zip(avg_gain, avg_loss)]


def atr(candles: list[Candle], period: int = 14) -> list[float]:
    tr = []
    for i, candle in enumerate(candles):
        previous = candles[i - 1].close if i else candle.close
        tr.append(max(candle.high - candle.low, abs(candle.high - previous), abs(candle.low - previous)))
    return ema(tr, period)


def _fvg_zones(candles: list[Candle], lookback: int = 100):
    zones = {"bull": None, "bear": None}
    start = max(2, len(candles) - lookback)
    for i in range(start, len(candles)):
        left, right = candles[i - 2], candles[i]
        if right.low > left.high:
            low, high = left.high, right.low
            future = candles[i + 1:]
            prior = candles[max(0, i - 12):i]
            after_bos = bool(prior and right.close > max(x.high for x in prior))
            filled = any(x.low <= low for x in future)
            touched = any(x.low <= high for x in future)
            zones["bull"] = {"side": "bull", "low": low, "high": high, "index": i,
                             "status": "filled" if filled else "touched" if touched else "untouched",
                             "inside": low <= candles[-1].close <= high, "after_bos": after_bos}
        elif right.high < left.low:
            low, high = right.high, left.low
            future = candles[i + 1:]
            prior = candles[max(0, i - 12):i]
            after_bos = bool(prior and right.close < min(x.low for x in prior))
            filled = any(x.high >= high for x in future)
            touched = any(x.high >= low for x in future)
            zones["bear"] = {"side": "bear", "low": low, "high": high, "index": i,
                             "status": "filled" if filled else "touched" if touched else "untouched",
                             "inside": low <= candles[-1].close <= high, "after_bos": after_bos}
    return zones


def _structure(candles: list[Candle], window: int = 5):
    highs, lows = [], []
    for i in range(window, len(candles) - window):
        segment = candles[i - window:i + window + 1]
        if candles[i].high == max(x.high for x in segment): highs.append((i, candles[i].high))
        if candles[i].low == min(x.low for x in segment): lows.append((i, candles[i].low))
    close = candles[-1].close
    bull_bos = bool(highs and close > highs[-1][1])
    bear_bos = bool(lows and close < lows[-1][1])
    return highs, lows, bull_bos, bear_bos


def dow_theory(highs, lows):
    """Classify the latest confirmed swing structure using Dow Theory."""
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", "スイング不足"
    higher_high = highs[-1][1] > highs[-2][1]
    higher_low = lows[-1][1] > lows[-2][1]
    lower_high = highs[-1][1] < highs[-2][1]
    lower_low = lows[-1][1] < lows[-2][1]
    if higher_high and higher_low:
        return "BULLISH", "HH・HL（高値・安値切り上げ）"
    if lower_high and lower_low:
        return "BEARISH", "LH・LL（高値・安値切り下げ）"
    return "RANGE", "高値・安値の方向が不一致"


def _order_block(candles: list[Candle], bull_bos: bool, bear_bos: bool):
    recent = candles[-20:-1]
    if bull_bos:
        for candle in reversed(recent):
            if candle.close < candle.open:
                return ("bull", candle.low, candle.high)
    if bear_bos:
        for candle in reversed(recent):
            if candle.close > candle.open:
                return ("bear", candle.low, candle.high)
    return None


def analyze_timeframe(candles: list[Candle], timeframe: str) -> TimeframeAnalysis:
    if len(candles) < 220:
        raise ValueError(f"{timeframe}: at least 220 candles required")
    close = [x.close for x in candles]
    volumes = [x.volume for x in candles]
    e20, e75, e200 = ema(close, 20), ema(close, 75), ema(close, 200)
    r = rsi(close, 14)
    fast, slow = ema(close, 12), ema(close, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    signal = ema(macd, 9)
    volatility = atr(candles, 14)
    price, unit = close[-1], max(volatility[-1], 1e-9)
    window = close[-20:]
    middle = mean(window); sd = pstdev(window)
    upper, lower = middle + 2 * sd, middle - 2 * sd
    highs, lows, bull_bos, bear_bos = _structure(candles)
    dow_trend, dow_label = dow_theory(highs, lows)
    fvgs = _fvg_zones(candles)
    ob = _order_block(candles, bull_bos, bear_bos)

    score = 0.0; reasons = []; warnings = []
    if price > e20[-1] > e75[-1] > e200[-1]: score += 24; reasons.append("EMA20>75>200の上昇配列")
    elif price < e20[-1] < e75[-1] < e200[-1]: score -= 24; reasons.append("EMA20<75<200の下降配列")
    else: warnings.append("EMAが混在しトレンド不鮮明")
    if r[-1] >= 55 and r[-1] < 75: score += 8; reasons.append(f"RSI {r[-1]:.1f}（買い優勢）")
    elif r[-1] <= 45 and r[-1] > 25: score -= 8; reasons.append(f"RSI {r[-1]:.1f}（売り優勢）")
    elif r[-1] >= 75: score -= 3; warnings.append("RSI買われ過ぎ")
    elif r[-1] <= 25: score += 3; warnings.append("RSI売られ過ぎ")
    if macd[-1] > signal[-1] and macd[-1] > macd[-2]: score += 9; reasons.append("MACD上向きクロス/拡大")
    elif macd[-1] < signal[-1] and macd[-1] < macd[-2]: score -= 9; reasons.append("MACD下向きクロス/拡大")
    if price > middle: score += 4
    else: score -= 4
    if price >= upper: warnings.append("ボリンジャー上限付近")
    if price <= lower: warnings.append("ボリンジャー下限付近")
    if bull_bos: score += 16; reasons.append("直近スイング高値を終値で突破（強気BOS）")
    if bear_bos: score -= 16; reasons.append("直近スイング安値を終値で突破（弱気BOS）")
    if dow_trend == "BULLISH": score += 10; reasons.append(f"ダウ理論: {dow_label}")
    elif dow_trend == "BEARISH": score -= 10; reasons.append(f"ダウ理論: {dow_label}")
    else: warnings.append(f"ダウ理論: {dow_label}")
    directional_fvg = fvgs["bull"] if score >= 0 else fvgs["bear"]
    if directional_fvg:
        side, low, high = directional_fvg["side"], directional_fvg["low"], directional_fvg["high"]
        distance = 0 if low <= price <= high else min(abs(price-low), abs(price-high))
        if distance <= unit * 1.5:
            score += 7 if side == "bull" else -7
            reasons.append(f"{('強気' if side == 'bull' else '弱気')}FVG付近 {low:.3f}-{high:.3f}")
    if ob:
        side, low, high = ob
        if low - unit <= price <= high + unit:
            score += 7 if side == "bull" else -7
            reasons.append(f"{('強気' if side == 'bull' else '弱気')}オーダーブロック付近")
    recent_high = max(x.high for x in candles[-21:-1]); recent_low = min(x.low for x in candles[-21:-1])
    last = candles[-1]
    if last.high > recent_high and last.close < recent_high:
        score -= 10; reasons.append("高値側流動性を掃いた後に反落")
    if last.low < recent_low and last.close > recent_low:
        score += 10; reasons.append("安値側流動性を掃いた後に反発")
    average_volume = mean(volumes[-21:-1]) if any(volumes[-21:-1]) else 0
    volume_ratio = volumes[-1] / average_volume if average_volume else 0
    if volume_ratio >= 1.5:
        score += 5 if last.close >= last.open else -5
        reasons.append(f"出来高急増 x{volume_ratio:.1f}")

    score = max(-100.0, min(100.0, score))
    direction = "LONG" if score >= 20 else "SHORT" if score <= -20 else "WAIT"
    last_high = highs[-1][1] if highs else recent_high
    last_low = lows[-1][1] if lows else recent_low
    bull_choch = dow_trend == "BEARISH" and price > last_high
    bear_choch = dow_trend == "BULLISH" and price < last_low
    range_window = candles[-50:]
    range_high, range_low = max(x.high for x in range_window), min(x.low for x in range_window)
    round_below = math.floor(price * 2) / 2
    round_above = math.ceil(price * 2) / 2
    return TimeframeAnalysis(
        timeframe=timeframe, score=round(score, 1), direction=direction,
        confidence=round(abs(score), 1), reasons=reasons, warnings=warnings,
        metrics={"price": price, "ema20": e20[-1], "ema75": e75[-1], "ema200": e200[-1],
                 "rsi": r[-1], "macd": macd[-1], "macd_signal": signal[-1], "bb_upper": upper,
                 "bb_middle": middle, "bb_lower": lower, "atr": unit, "volume_ratio": volume_ratio,
                 "recent_high": recent_high, "recent_low": recent_low, "range_high": range_high,
                 "range_low": range_low, "round_below": round_below, "round_above": round_above,
                 "dow_trend": dow_trend,
                 "dow_label": dow_label,
                 "last_swing_high": last_high, "last_swing_low": last_low,
                 "bull_bos": bull_bos, "bear_bos": bear_bos,
                 "bull_choch": bull_choch, "bear_choch": bear_choch,
                 "ema20_slope": e20[-1] - e20[-4], "ema75_slope": e75[-1] - e75[-4],
                 "ema200_slope": e200[-1] - e200[-4],
                 "bull_fvg": fvgs["bull"], "bear_fvg": fvgs["bear"]},
    )


def combine(analyses: dict[str, TimeframeAnalysis], weights: dict[str, float], threshold: float = 85):
    active = [(tf, a) for tf, a in analyses.items() if tf in weights]
    total_weight = sum(weights[tf] for tf, _ in active) or 1
    score = sum(a.score * weights[tf] for tf, a in active) / total_weight
    long_percent = round((score + 100) / 2, 1)
    short_percent = round(100 - long_percent, 1)
    five = analyses.get("5m"); hour = analyses.get("1h")
    aligned = bool(five and hour and five.direction == hour.direction and five.direction != "WAIT")
    decision = "WAIT"
    if long_percent >= threshold: decision = "LONG"
    elif short_percent >= threshold: decision = "SHORT"
    blockers = []
    if decision == "WAIT": blockers.append(f"LONG/SHORTのどちらも {threshold:.0f}% 未満です")
    reference = five or next(iter(analyses.values()))
    price = reference.metrics["price"]; risk = reference.metrics["atr"] * 1.5
    stop = price - risk if decision == "LONG" else price + risk if decision == "SHORT" else None
    target = price + risk * 2 if decision == "LONG" else price - risk * 2 if decision == "SHORT" else None
    return {"decision": decision, "score": round(score, 1), "long_percent": long_percent,
            "short_percent": short_percent, "signal_confidence": max(long_percent, short_percent),
            "aligned": aligned, "blockers": blockers,
            "entry_price": price if decision != "WAIT" else None,
            "stop_price": stop, "take_profit_price": target,
            "risk_reward": "1:2（参考値）" if decision != "WAIT" else None}
