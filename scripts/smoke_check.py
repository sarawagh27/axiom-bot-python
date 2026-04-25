"""
Simple post-deploy smoke check for Render keep-alive endpoints.

Usage:
    python scripts/smoke_check.py https://your-app.onrender.com
"""

from __future__ import annotations

import json
import time
import sys
import urllib.error
import urllib.request


EXPECTED = {"status": "ok", "bot": "Axiom"}
ROUTES = ("/ping", "/health", "/healthz")
REQUEST_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 10


def check_route_once(base_url: str, route: str) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}{route}"
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        return False, f"{route}: request failed ({exc})"

    if status != 200:
        return False, f"{route}: expected 200, got {status}"

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False, f"{route}: response is not valid JSON"

    if payload != EXPECTED:
        return False, f"{route}: expected {EXPECTED}, got {payload}"

    return True, f"{route}: OK"


def check_route(base_url: str, route: str) -> tuple[bool, str]:
    last_message = f"{route}: unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ok, message = check_route_once(base_url, route)
        if ok:
            return True, f"{route}: OK (attempt {attempt}/{MAX_ATTEMPTS})"

        last_message = message
        if attempt < MAX_ATTEMPTS:
            print(
                f"{route}: attempt {attempt}/{MAX_ATTEMPTS} failed, "
                f"retrying in {RETRY_BACKOFF_SECONDS}s..."
            )
            time.sleep(RETRY_BACKOFF_SECONDS)

    return False, f"{route}: FAILED after {MAX_ATTEMPTS} attempts. Last error: {last_message}"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/smoke_check.py https://your-app.onrender.com")
        return 2

    base_url = sys.argv[1].strip()
    failures: list[str] = []

    print(f"Running keep-alive smoke check against: {base_url}")
    for route in ROUTES:
        ok, message = check_route(base_url, route)
        print(message)
        if not ok:
            failures.append(message)

    if failures:
        print("\nSmoke check FAILED.")
        return 1

    print("\nSmoke check PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
