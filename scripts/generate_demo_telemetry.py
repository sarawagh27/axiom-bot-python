"""Generate realistic demo telemetry for Axiom's operational intelligence.

Run this from the repository root:
    python scripts/generate_demo_telemetry.py

Use Ctrl+C to stop continuous generation.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.anomaly_detection import anomaly_detector  # noqa: E402
from core.database import db  # noqa: E402
from core.incidents import incident_service  # noqa: E402
from core.telemetry import EventName, EventSeverity  # noqa: E402


DEFAULT_GUILD_ID = 100001
USERS = (200101, 200202, 200303, 200404)
TARGETS = (300101, 300202, 300303)
COMMANDS = ("pingbomb", "ghostping", "massghost", "stats", "ops status")


class DemoTelemetryGenerator:
    """Writes operational telemetry through Axiom's real persistence layer."""

    def __init__(self, guild_id: int = DEFAULT_GUILD_ID, seed: int | None = None) -> None:
        self.guild_id = guild_id
        self._random = random.Random(seed)
        self._step = 0

    def emit_step(self) -> None:
        self._step += 1
        user_id = self._random.choice(USERS)
        target_id = self._random.choice(TARGETS)
        command = self._random.choice(COMMANDS)

        db.record_usage(
            guild_id=self.guild_id,
            user_id=user_id,
            command=command,
            target_id=target_id,
            count=self._random.randint(1, 5),
        )

        if self._step % 2 == 0:
            self._record_session_activity(user_id, target_id)
        if self._step % 3 == 0:
            self._record_cooldown_pressure(user_id)
        if self._step % 5 == 0:
            self._record_rate_limit_pressure(user_id)
        if self._step % 7 == 0:
            self._record_error_spike(user_id, command)
        if self._step % 11 == 0:
            self._record_admin_action(user_id)

        self.reconcile_incidents()

    def reconcile_incidents(self) -> None:
        report = anomaly_detector.detect(self.guild_id, window_seconds=3600)
        incident_service.reconcile_anomalies(report)

    def _record_session_activity(self, user_id: int, target_id: int) -> None:
        db.record_operational_event(
            event_type=EventName.SESSION_STARTED,
            severity=EventSeverity.INFO,
            source="demo_telemetry",
            guild_id=self.guild_id,
            user_id=user_id,
            target_id=target_id,
            command="pingbomb",
            metadata={"demo": True, "step": self._step},
        )
        for index in range(self._random.randint(2, 6)):
            db.record_operational_event(
                event_type=EventName.SESSION_PING,
                severity=EventSeverity.INFO,
                source="demo_telemetry",
                guild_id=self.guild_id,
                user_id=user_id,
                target_id=target_id,
                command="pingbomb",
                metadata={"demo": True, "sequence": index + 1, "step": self._step},
            )

    def _record_cooldown_pressure(self, user_id: int) -> None:
        for _ in range(2):
            db.record_operational_event(
                event_type=EventName.COMMAND_REJECTED,
                severity=EventSeverity.WARNING,
                source="demo_telemetry",
                guild_id=self.guild_id,
                user_id=user_id,
                command="pingbomb",
                metadata={
                    "demo": True,
                    "reason": "cooldown",
                    "remaining_seconds": self._random.randint(8, 45),
                    "step": self._step,
                },
            )

    def _record_rate_limit_pressure(self, user_id: int) -> None:
        for _ in range(3):
            db.record_operational_event(
                event_type=EventName.COMMAND_RATE_LIMITED,
                severity=EventSeverity.WARNING,
                source="demo_telemetry",
                guild_id=self.guild_id,
                user_id=user_id,
                command="pingbomb",
                metadata={
                    "demo": True,
                    "retry_after": self._random.randint(3, 20),
                    "step": self._step,
                },
            )

    def _record_error_spike(self, user_id: int, command: str) -> None:
        for index in range(3):
            db.record_operational_event(
                event_type=EventName.COMMAND_ERROR,
                severity=EventSeverity.ERROR,
                source="demo_telemetry",
                guild_id=self.guild_id,
                user_id=user_id,
                command=command,
                metadata={
                    "demo": True,
                    "error_type": "DemoRuntimeError",
                    "error": f"simulated failure {index + 1}",
                    "step": self._step,
                },
            )

    def _record_admin_action(self, user_id: int) -> None:
        db.record_operational_event(
            event_type=EventName.ADMIN_ACTION,
            severity=EventSeverity.INFO,
            source="demo_telemetry",
            guild_id=self.guild_id,
            user_id=user_id,
            command="admin_stop_all",
            metadata={"demo": True, "action": "review_demo_incidents", "step": self._step},
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate live demo telemetry for Axiom.")
    parser.add_argument("--guild-id", type=int, default=DEFAULT_GUILD_ID)
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between demo batches.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Number of batches to emit. Default 0 runs until Ctrl+C.",
    )
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db.connect()
    generator = DemoTelemetryGenerator(guild_id=args.guild_id, seed=args.seed)

    print(f"Generating demo telemetry for guild {args.guild_id}.")
    print("Press Ctrl+C to stop.")

    emitted = 0
    try:
        while args.iterations == 0 or emitted < args.iterations:
            generator.emit_step()
            emitted += 1
            print(f"emitted batch {emitted}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped demo telemetry generator.")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
