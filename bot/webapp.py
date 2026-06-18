from __future__ import annotations

from flask import Flask, jsonify, render_template


def create_app(service):
    app = Flask(__name__, template_folder="../templates")

    @app.get("/")
    def home(): return render_template("index.html", symbol=service.config["symbol"])

    @app.get("/api/status")
    def status(): return jsonify(service.snapshot())

    @app.post("/api/refresh")
    def refresh():
        import threading
        threading.Thread(target=service.refresh, daemon=True).start()
        return jsonify({"accepted": True})

    return app

