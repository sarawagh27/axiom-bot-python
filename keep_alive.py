"""
keep_alive.py — Flask web server that keeps Render alive.
Runs in a background thread alongside the bot.
"""

import logging
import os
from threading import Thread
from flask import Flask, jsonify

log = logging.getLogger("axiom.keep_alive")
app = Flask(__name__)


@app.route("/")
def home():
    return "Axiom is alive! 💣", 200


@app.route("/health")
def health():
    return jsonify({"status": "ok", "bot": "Axiom"}), 200


@app.route("/ping")
def ping():
    return "pong", 200


def keep_alive():
    """Start the Flask server in a background thread."""
    port = int(os.environ.get("PORT", 10000))

    def run():
        app.run(host="0.0.0.0", port=port, threaded=True)

    thread = Thread(target=run, daemon=True)
    thread.start()
    log.info(f"Keep-alive server started on port {port}")
