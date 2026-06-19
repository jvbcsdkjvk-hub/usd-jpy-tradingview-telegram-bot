import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import telegram_signal
from bot.analysis import analyze_timeframe, combine
from bot.economic_calendar import fetch_calendar
from bot.models import Candle


def candles(direction=1, count=300):
    rows=[]
    for i in range(count):
        base=150 + direction*i*0.012 + math.sin(i/6)*0.03
        rows.append(Candle(1700000000+i*300,base,base+.025,base-.025,base+direction*.008,100+i%11))
    return rows


def analyses(directions=(1,1,1)):
    return {tf:analyze_timeframe(candles(direction),tf)
            for tf,direction in zip(("1h","15m","5m"),directions)}


def summary_for(items):
    weights={"1h":.4,"15m":.35,"5m":.25}
    summary=combine(items,weights,50)
    summary.update(telegram_signal.score_environment(summary,items))
    return summary


class FakeResponse:
    def __init__(self,payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return json.dumps(self.payload).encode()


class TelegramSignalTests(unittest.TestCase):
    def test_all_timeframes_are_used(self):
        config={"symbol":"FOREXCOM:USDJPY","history_bars":500,
                "telegram_short_term":{"weights":{"1h":.4,"15m":.35,"5m":.25}}}
        values=analyses()
        with patch.object(telegram_signal,"fetch_candles",return_value=[object()]), \
             patch.object(telegram_signal,"analyze_timeframe",side_effect=lambda candles,tf:values[tf]):
            summary,result=telegram_signal.analyze(config)
        self.assertEqual(set(result),{"1h","15m","5m"})
        self.assertEqual(summary["decision"],"LONG")
        self.assertLessEqual(summary["total_score"],100)
        self.assertEqual(sum(x[1] for x in summary["score_breakdown"].values()),100)

    def test_five_minute_countertrend_reduces_alignment(self):
        aligned=summary_for(analyses((1,1,1)))
        counter=summary_for(analyses((1,1,-1)))
        self.assertGreater(aligned["score_breakdown"]["上位足・時間足整合性"][0],
                           counter["score_breakdown"]["上位足・時間足整合性"][0])

    def test_normal_message_is_short(self):
        items=analyses((1,1,-1)); summary=summary_for(items)
        message=telegram_signal.normal_message(summary,items)
        for text in ("価格","1h","5m","注目価格","TP","SL"):
            self.assertIn(text,message)
        for text in ("FVG","ATR","BOS","CHOCH","EMA","スコア"):
            self.assertNotIn(text,message)
        self.assertLess(len(message),500)

    def test_strong_message_has_detailed_reasons(self):
        items=analyses(); summary=summary_for(items); summary["total_score"]=78
        message=telegram_signal.strong_message(summary,items)
        for text in ("強ロング候補","78/100","15m","BOS","CHOCH","EMA","FVG",
                     "エントリー条件","飛び乗り禁止","ローソク足確定待ち"):
            self.assertIn(text,message)

    def test_notification_thresholds_and_slots(self):
        summary={"total_score":54,"decision":"LONG"}; calendar={"danger":[]}
        self.assertIsNone(telegram_signal.choose_notification(summary,calendar,0,now=1000))
        summary["total_score"]=60
        self.assertEqual(telegram_signal.choose_notification(summary,calendar,0,now=1000),"normal")
        self.assertIsNone(telegram_signal.choose_notification(summary,calendar,15,now=1000))

    def test_strong_signal_cooldown_and_direction_change(self):
        summary={"total_score":75,"decision":"LONG"}; calendar={"danger":[]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(telegram_signal,"STATE_PATH",Path(tmp)/"state.json"):
            self.assertEqual(telegram_signal.choose_notification(summary,calendar,15,now=1000),"strong")
            telegram_signal.write_state({"direction":"LONG","strong_at":1000})
            self.assertIsNone(telegram_signal.choose_notification(summary,calendar,15,now=1500))
            summary["decision"]="SHORT"
            self.assertEqual(telegram_signal.choose_notification(summary,calendar,15,now=1500),"strong")

    def test_calendar_danger_downgrades_to_normal_on_half_hour(self):
        summary={"total_score":80,"decision":"LONG"}; calendar={"danger":[{"title":"CPI"}]}
        self.assertEqual(telegram_signal.choose_notification(summary,calendar,30,now=1000),"normal")
        self.assertIsNone(telegram_signal.choose_notification(summary,calendar,15,now=1000))

    def test_high_impact_calendar_window(self):
        payload=[{"title":"CPI","country":"USD","date":"2026-06-19T01:30:00+00:00","impact":"High"},
                 {"title":"Minor","country":"JPY","date":"2026-06-19T01:20:00+00:00","impact":"Low"}]
        config={"url":"https://example.test","currencies":["USD","JPY"],"impact":"High",
                "minutes_before":60,"minutes_after":30}
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            result=fetch_calendar(config,datetime(2026,6,19,1,0,tzinfo=timezone.utc))
        self.assertEqual(len(result["danger"]),1)
        self.assertEqual(result["danger"][0]["title"],"CPI")


if __name__ == "__main__": unittest.main()
