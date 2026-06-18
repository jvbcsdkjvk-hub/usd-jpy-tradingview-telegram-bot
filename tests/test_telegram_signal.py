import unittest
from unittest.mock import patch

import telegram_signal
from bot.models import TimeframeAnalysis


def analysis(tf, score, price=150.0, atr=0.2):
    return TimeframeAnalysis(tf, score, "LONG" if score >= 0 else "SHORT", abs(score),
                             metrics={"price": price, "atr": atr, "ema20":149.95,
                                      "last_swing_high":150.2,"last_swing_low":149.8,
                                      "dow_label":"HH・HL（高値・安値切り上げ）"})


class TelegramSignalTests(unittest.TestCase):
    def test_five_minute_has_sixty_five_percent_weight(self):
        config={"symbol":"FOREXCOM:USDJPY","history_bars":500,
                "telegram_short_term":{"weak_threshold":60,"weights":{"5m":.65,"1h":.35}}}
        values={"5m":analysis("5m",80),"1h":analysis("1h",-20)}
        with patch.object(telegram_signal,"fetch_candles",return_value=[object()]), \
             patch.object(telegram_signal,"analyze_timeframe",side_effect=lambda candles,tf:values[tf]):
            summary,_=telegram_signal.analyze(config)
        self.assertEqual(summary["decision"],"LONG")
        self.assertEqual(summary["long_percent"],72.5)
        self.assertFalse(summary["weak"])

    def test_weak_signal_still_chooses_direction(self):
        config={"symbol":"FOREXCOM:USDJPY","history_bars":500,
                "telegram_short_term":{"weak_threshold":60,"weights":{"5m":.65,"1h":.35}}}
        values={"5m":analysis("5m",8),"1h":analysis("1h",-2)}
        with patch.object(telegram_signal,"fetch_candles",return_value=[object()]), \
             patch.object(telegram_signal,"analyze_timeframe",side_effect=lambda candles,tf:values[tf]):
            summary,_=telegram_signal.analyze(config)
        self.assertEqual(summary["decision"],"LONG")
        self.assertTrue(summary["weak"])
        self.assertIsNotNone(summary["entry_price"])

    def test_message_contains_prices_and_weak_warning(self):
        summary={"decision":"SHORT","long_percent":45.0,"short_percent":55.0,
                 "signal_confidence":55.0,"weak":True,"entry_price":150.0,
                 "take_profit_price":149.4,"stop_price":150.3}
        message=telegram_signal.telegram_message(summary,{"5m":analysis("5m",-10),"1h":analysis("1h",0)})
        self.assertIn("弱い売り。即エントリー非推奨",message)
        self.assertIn("現在価格",message)
        self.assertIn("利確",message)
        self.assertIn("損切り",message)
        self.assertIn("ダウ理論",message)
        self.assertIn("下抜け確定後",message)


if __name__ == "__main__": unittest.main()
