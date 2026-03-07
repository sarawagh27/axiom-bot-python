"""
services/audit_service.py — Immutable structured audit trail.
Appends JSON records to logs/audit.log on every session state event.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.session_model import Session

_AUDIT_LOG_PATH = "logs/audit.log"


class AuditService:
    def __init__(self) -> None:
        os.makedirs("logs", exist_ok=True)
        self._logger = self._build_logger()

    def _build_logger(self) -> logging.Logger:
        logger = logging.getLogger("axiom.audit")
        logger.setLevel(logging.INFO)
        logger.propagate = False  # Don't bubble up to root logger

        handler = logging.handlers.RotatingFileHandler(
            filename=_AUDIT_LOG_PATH,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_event(
        self,
        event: str,
        session: "Session",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append a JSON audit record for the given session event."""
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            **session.to_dict(),
        }
        if extra:
            record.update(extra)

        try:
            self._logger.info(json.dumps(record, default=str))
        except Exception as exc:  # noqa: BLE001
            # Audit logging must never crash the bot
            logging.getLogger("axiom.audit_service").error(
                "Failed to write audit record: %s", exc
            )

    def log_admin_action(
        self,
        action: str,
        admin_id: int,
        guild_id: int,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Audit log an admin action (not tied to a specific session)."""
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": f"ADMIN_{action}",
            "admin_id": admin_id,
            "guild_id": guild_id,
        }
        if details:
            record.update(details)

        try:
            self._logger.info(json.dumps(record, default=str))
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("axiom.audit_service").error(
                "Failed to write admin audit record: %s", exc
            )


# Module-level singleton
audit_service = AuditService()
