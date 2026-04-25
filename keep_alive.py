"""
keep_alive.py — Tiny Flask web server that runs alongside the bot.
Gives Render and UptimeRobot an HTTP endpoint to ping so the bot
never spins down on the free tier.
"""

from threading import Thread
from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/")
def home():
    return "Axiom is alive! 💣", 200


@app.route("/health")
def health():
    return jsonify(status="ok", bot="Axiom"), 200


@app.route("/healthz")
@app.route("/ping")
def ping():
    # Keep legacy and platform-specific health URLs stable.
    return health()


import os

def keep_alive():
    """Start the Flask server in a background thread."""
    port = int(os.environ.get("PORT", 10000))
    thread = Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True)
    thread.start()
