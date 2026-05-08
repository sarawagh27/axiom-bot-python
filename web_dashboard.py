"""
web_dashboard.py - Flask routes for Axiom's operational dashboard.
"""

from __future__ import annotations

import json
import time

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

from services.dashboard_data import DEFAULT_WINDOW_SECONDS, dashboard_data_service

dashboard_bp = Blueprint("dashboard", __name__)


def _int_arg(name: str, default: int, minimum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None:
        return max(minimum, value)
    return value


def _guild_arg() -> int | None:
    raw = request.args.get("guild_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dashboard_bp.route("/dashboard")
def dashboard_home():
    window_seconds = _int_arg("window", DEFAULT_WINDOW_SECONDS, minimum=300)
    guild_id = _guild_arg()
    data = dashboard_data_service.overview(guild_id, window_seconds)
    return render_template("dashboard.html", dashboard=data)


@dashboard_bp.route("/dashboard/health")
def dashboard_health():
    window_seconds = _int_arg("window", DEFAULT_WINDOW_SECONDS, minimum=300)
    guild_id = dashboard_data_service.resolve_guild_id(_guild_arg())
    if guild_id is None:
        return jsonify(dashboard_data_service.overview(None, window_seconds)["health"])
    return jsonify(dashboard_data_service.health(guild_id, window_seconds))


@dashboard_bp.route("/dashboard/anomalies")
def dashboard_anomalies():
    window_seconds = _int_arg("window", DEFAULT_WINDOW_SECONDS, minimum=300)
    guild_id = dashboard_data_service.resolve_guild_id(_guild_arg())
    if guild_id is None:
        return jsonify(dashboard_data_service.overview(None, window_seconds)["anomalies"])
    return jsonify(dashboard_data_service.anomalies(guild_id, window_seconds))


@dashboard_bp.route("/dashboard/events")
def dashboard_events():
    limit = _int_arg("limit", 40, minimum=1)
    guild_id = dashboard_data_service.resolve_guild_id(_guild_arg())
    if guild_id is None:
        return jsonify([])
    return jsonify(dashboard_data_service.events(guild_id, limit))


@dashboard_bp.route("/dashboard/data")
def dashboard_data():
    window_seconds = _int_arg("window", DEFAULT_WINDOW_SECONDS, minimum=300)
    limit = _int_arg("limit", 40, minimum=1)
    guild_id = _guild_arg()
    return jsonify(dashboard_data_service.overview(guild_id, window_seconds, limit))


@dashboard_bp.route("/dashboard/timeline")
def dashboard_timeline():
    window_seconds = _int_arg("window", DEFAULT_WINDOW_SECONDS, minimum=300)
    limit = _int_arg("limit", 30, minimum=1)
    guild_id = dashboard_data_service.resolve_guild_id(_guild_arg())
    if guild_id is None:
        return jsonify([])
    return jsonify(dashboard_data_service.timeline(guild_id, window_seconds, limit))


@dashboard_bp.route("/dashboard/stream")
def dashboard_stream():
    window_seconds = _int_arg("window", DEFAULT_WINDOW_SECONDS, minimum=300)
    limit = _int_arg("limit", 40, minimum=1)
    interval = _int_arg("interval", 3, minimum=1)
    after_id = _int_arg("after_id", 0, minimum=0)
    once = request.args.get("once") == "1"
    guild_id = _guild_arg()

    def event_stream():
        cursor = after_id
        while True:
            payload = dashboard_data_service.live_snapshot(
                guild_id=guild_id,
                window_seconds=window_seconds,
                event_limit=limit,
                after_id=cursor,
            )
            cursor = payload.get("latest_event_id", cursor)
            yield f"event: dashboard\ndata: {json.dumps(payload, default=str)}\n\n"
            if once:
                break
            time.sleep(interval)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
