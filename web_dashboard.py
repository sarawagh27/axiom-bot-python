"""
web_dashboard.py - Flask routes for Axiom's operational dashboard.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

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
