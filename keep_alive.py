"""
keep_alive.py — Tiny Flask web server that runs alongside the bot.
Gives Render and UptimeRobot an HTTP endpoint to ping so the bot
never spins down on the free tier.
"""

from threading import Thread
from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "Axiom is alive! 💣", 200


@app.route("/health")
def health():
    return {"status": "ok", "bot": "Axiom"}, 200


def keep_alive():
    """Start the Flask server in a background thread."""
    thread = Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True)
    thread.start()
