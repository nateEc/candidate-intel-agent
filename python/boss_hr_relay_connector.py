from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from websocket import WebSocketConnectionClosedException, create_connection


DEFAULT_LOCAL_BASE_URL = os.environ.get("BOSS_HR_AGENT_BASE_URL", "http://127.0.0.1:8790")
DEFAULT_RECONNECT_SECONDS = float(os.environ.get("BOSS_HR_RELAY_RECONNECT_SECONDS", "3"))


def main() -> int:
    args = parse_args()
    token = args.token or os.environ.get("BOSS_HR_RELAY_TOKEN") or ""
    if not token:
        print("Missing relay token. Set BOSS_HR_RELAY_TOKEN or pass --token.", file=sys.stderr)
        return 2

    session_id = args.session_id or os.environ.get("BOSS_HR_RELAY_SESSION_ID") or ""
    if not session_id:
        print("Missing session id. Set BOSS_HR_RELAY_SESSION_ID or pass --session-id.", file=sys.stderr)
        return 2

    if args.auto_start_local:
        ensure_local_service(args.local_base_url)

    while True:
        try:
            run_connector(args.relay_url, session_id, token, args.local_base_url)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"Relay connector disconnected: {exc}", file=sys.stderr)
            if args.once:
                return 1
            time.sleep(args.reconnect_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Connect local BOSS HR Browser Agent to a cloud relay.")
    parser.add_argument("--relay-url", default=os.environ.get("BOSS_HR_RELAY_URL", "http://127.0.0.1:8791"))
    parser.add_argument("--session-id", default=os.environ.get("BOSS_HR_RELAY_SESSION_ID", ""))
    parser.add_argument("--token", default=os.environ.get("BOSS_HR_RELAY_TOKEN", ""))
    parser.add_argument("--local-base-url", default=DEFAULT_LOCAL_BASE_URL)
    parser.add_argument("--reconnect-seconds", type=float, default=DEFAULT_RECONNECT_SECONDS)
    parser.add_argument("--no-auto-start-local", dest="auto_start_local", action="store_false")
    parser.add_argument("--once", action="store_true")
    parser.set_defaults(auto_start_local=True)
    return parser.parse_args()


def run_connector(relay_url: str, session_id: str, token: str, local_base_url: str) -> None:
    ws_url = build_ws_url(relay_url, session_id, token)
    print(f"Connecting BOSS HR relay session {session_id} -> {relay_url}")
    ws = create_connection(ws_url, timeout=30)
    try:
        while True:
            raw_message = ws.recv()
            message = json.loads(raw_message)
            response = handle_message(message, local_base_url)
            ws.send(json.dumps(response, ensure_ascii=False))
    finally:
        ws.close()


def build_ws_url(relay_url: str, session_id: str, token: str) -> str:
    parsed = urllib.parse.urlparse(relay_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc or parsed.path
    base_path = parsed.path if parsed.netloc else ""
    connect_path = f"{base_path.rstrip('/')}/v1/connect/{urllib.parse.quote(session_id, safe='')}"
    query = urllib.parse.urlencode({"token": token})
    return urllib.parse.urlunparse((scheme, netloc, connect_path, "", query, ""))


def handle_message(message: dict[str, Any], local_base_url: str) -> dict[str, Any]:
    request_id = str(message.get("id") or "")
    if not request_id:
        return {"error": "missing request id"}

    try:
        local_response = perform_local_request(
            local_base_url=local_base_url,
            method=str(message.get("method") or "GET"),
            path=str(message.get("path") or "/health"),
            json_body=message.get("json_body"),
        )
        return {"id": request_id, "response": local_response}
    except Exception as exc:
        return {"id": request_id, "error": str(exc)}


def perform_local_request(
    local_base_url: str,
    method: str,
    path: str,
    json_body: Any | None = None,
) -> dict[str, Any]:
    normalized_method = method.upper()
    if normalized_method not in {"GET", "POST"}:
        raise ValueError(f"unsupported local method: {method}")

    local_url = f"{local_base_url.rstrip('/')}/{path.lstrip('/')}"
    data = None
    headers = {"accept": "application/json"}
    if normalized_method == "POST":
        data = json.dumps(json_body or {}, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"

    request = urllib.request.Request(local_url, data=data, headers=headers, method=normalized_method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status_code = int(response.status)
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")

    body: Any
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = None

    return {
        "status_code": status_code,
        "body": body,
        "text": "" if body is not None else raw,
    }


def ensure_local_service(local_base_url: str) -> None:
    if local_health_ok(local_base_url):
        return

    cli_path = Path(__file__).resolve().parent.parent / "bin" / "boss-hr-agent"
    if not cli_path.exists():
        raise RuntimeError(f"local service is unavailable and CLI is missing: {cli_path}")

    subprocess.run([str(cli_path), "start"], check=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        if local_health_ok(local_base_url):
            return
        time.sleep(1)
    raise RuntimeError(f"local service did not become healthy: {local_base_url}")


def local_health_ok(local_base_url: str) -> bool:
    try:
        response = perform_local_request(local_base_url, "GET", "/health")
        return int(response.get("status_code") or 500) < 400
    except (OSError, urllib.error.URLError, WebSocketConnectionClosedException):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
