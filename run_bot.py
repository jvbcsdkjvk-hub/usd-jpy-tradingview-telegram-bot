import threading
from pathlib import Path

from bot.service import SignalService
from bot.webapp import create_app


def main():
    root = Path(__file__).resolve().parent
    service = SignalService(root / "config.json")
    worker = threading.Thread(target=service.run, daemon=True)
    worker.start()
    port = int(service.config["port"])
    create_app(service).run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__": main()
