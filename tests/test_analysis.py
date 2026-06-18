import math
import unittest

from bot.analysis import analyze_timeframe, combine, dow_theory, ema
from bot.models import Candle


def candles(direction=1, count=300):
    rows=[]
    for i in range(count):
        base=140 + direction*i*0.015 + math.sin(i/7)*0.02
        rows.append(Candle(1700000000+i*300,base,base+0.025,base-0.025,base+direction*0.01,100+i%13))
    return rows


class AnalysisTests(unittest.TestCase):
    def test_ema(self):
        self.assertEqual(len(ema([1,2,3], 2)), 3)
        self.assertGreater(ema([1,2,3], 2)[-1], 2)

    def test_dow_theory_structure(self):
        self.assertEqual(dow_theory([(1,100),(2,110)],[(1,90),(2,95)])[0],"BULLISH")
        self.assertEqual(dow_theory([(1,110),(2,100)],[(1,95),(2,90)])[0],"BEARISH")

    def test_trending_markets(self):
        up=analyze_timeframe(candles(1), "5m")
        down=analyze_timeframe(candles(-1), "5m")
        self.assertGreater(up.score, 0)
        self.assertLess(down.score, 0)

    def test_combination_requires_threshold(self):
        up=analyze_timeframe(candles(1), "5m")
        down=analyze_timeframe(candles(-1), "1h")
        result=combine({"5m":up,"1h":down},{"5m":.5,"1h":.5},85)
        self.assertEqual(result["decision"], "WAIT")
        self.assertIsNone(result["entry_price"])

    def test_trade_prices_at_threshold(self):
        up=analyze_timeframe(candles(1), "5m")
        up.score=70
        result=combine({"5m":up},{"5m":1},85)
        risk=up.metrics["atr"]*1.5
        self.assertEqual(result["decision"], "LONG")
        self.assertEqual(result["long_percent"], 85)
        self.assertEqual(result["short_percent"], 15)
        self.assertAlmostEqual(result["stop_price"], result["entry_price"]-risk)
        self.assertAlmostEqual(result["take_profit_price"], result["entry_price"]+risk*2)

    def test_short_percent_totals_one_hundred(self):
        down=analyze_timeframe(candles(-1), "5m")
        down.score=-70
        result=combine({"5m":down},{"5m":1},85)
        self.assertEqual(result["decision"], "SHORT")
        self.assertEqual(result["long_percent"]+result["short_percent"],100)


if __name__ == "__main__": unittest.main()
