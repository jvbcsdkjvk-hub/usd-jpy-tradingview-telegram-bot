import json
import math
import unittest
from datetime import datetime, timezone
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

    def test_message_contains_required_environment_sections(self):
        items=analyses((1,1,-1)); summary=summary_for(items)
        message=telegram_signal.telegram_message(summary,items,{"danger":[],"upcoming":[],"error":None})
        for text in ("現在価格","エントリー条件","利確候補","損切り","根拠","警戒",
                     "15m","5m CHOCH","FVG","ローソク足確定","反発確認待ち","注目価格"):
            self.assertIn(text,message)
        self.assertNotIn("スコア内訳",message)
        self.assertNotIn("総合評価",message)
        self.assertLess(len(message),4096)

    def test_calendar_danger_forces_no_entry_wording(self):
        items=analyses(); summary=summary_for(items)
        danger={"danger":[{"currency":"USD","title":"CPI",
                 "time":datetime(2026,6,19,1,30,tzinfo=timezone.utc)}],"upcoming":[],"error":None}
        message=telegram_signal.telegram_message(summary,items,danger)
        self.assertIn("USD CPI",message)

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
