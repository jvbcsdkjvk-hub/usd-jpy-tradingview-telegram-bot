import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_signal


class TelegramSignalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state.json"
        self.config = {"cooldown_minutes": 30}

    def tearDown(self):
        self.temp.cleanup()

    def test_wait_never_notifies(self):
        self.assertFalse(telegram_signal.should_notify({"decision": "WAIT"}, self.config, 1000))

    def test_same_direction_obeys_cooldown(self):
        self.state.write_text('{"direction":"LONG","notified_at":1000}', encoding="utf-8")
        with patch.object(telegram_signal, "STATE_PATH", self.state):
            self.assertFalse(telegram_signal.should_notify({"decision": "LONG"}, self.config, 2000))
            self.assertTrue(telegram_signal.should_notify({"decision": "LONG"}, self.config, 3000))

    def test_direction_change_notifies_immediately(self):
        self.state.write_text('{"direction":"LONG","notified_at":1000}', encoding="utf-8")
        with patch.object(telegram_signal, "STATE_PATH", self.state):
            self.assertTrue(telegram_signal.should_notify({"decision": "SHORT"}, self.config, 1100))


if __name__ == "__main__":
    unittest.main()

