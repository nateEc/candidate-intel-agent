# BOSS HR Cloud Relay

Use this when the HR agent runs in the cloud and cannot access the user's `127.0.0.1`.

## Architecture

```text
Cloud Hermes/OpenClaw Agent
  -> HTTPS request to cloud relay
  -> WebSocket session
  -> User's local BOSS HR companion connector
  -> User's local BOSS HR Browser Agent on 127.0.0.1:8790
  -> User's visible Chrome
```

The local connector always initiates the outbound WebSocket connection. The cloud service never opens an inbound connection to the user's laptop.

## Cloud Relay

Run on a cloud machine:

```bash
cd candidate-intel-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements-hr-agent.txt
BOSS_HR_RELAY_TOKEN="<shared-secret>" \
BOSS_HR_RELAY_REQUEST_TIMEOUT=900 \
PYTHONPATH=python .venv/bin/uvicorn boss_hr_relay_service:app --host 0.0.0.0 --port 8791
```

Health check:

```bash
curl https://relay.example.com/health
```

Current Metabot test relay is served through nginx at:

```text
http://115.190.10.83/boss-hr-relay
```

## Local Connector

On the user's Mac, after installing the lightweight companion:

```bash
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" connect \
  --relay-url https://relay.example.com \
  --session-id "<user-session-id>" \
  --token "<shared-secret>"
```

For first-time users, install and connect in the background with one command:

```bash
curl -fsSL https://raw.githubusercontent.com/nateEc/candidate-intel-agent/main/scripts/bootstrap_boss_hr_agent.sh | bash -s -- connect-daemon \
  --relay-url https://relay.example.com \
  --session-id "<user-session-id>" \
  --token "<shared-secret>"
```

The connector starts the local BOSS HR Browser Agent if needed, then connects to:

```text
wss://relay.example.com/v1/connect/<user-session-id>?token=<shared-secret>
```

## Cloud Agent API

The cloud agent should call the relay, not the user's localhost.

Required header:

```http
x-boss-relay-token: <shared-secret>
```

Status:

```http
GET /v1/sessions/<session-id>/status
```

Login flow:

```http
POST /v1/sessions/<session-id>/browser/start
POST /v1/sessions/<session-id>/boss/login/start
POST /v1/sessions/<session-id>/boss/login/send-code
POST /v1/sessions/<session-id>/boss/login/submit-code
GET  /v1/sessions/<session-id>/boss/login/status
POST /v1/sessions/<session-id>/boss/navigate
POST /v1/sessions/<session-id>/boss/job/publish/start
POST /v1/sessions/<session-id>/boss/job/publish/draft
GET  /v1/sessions/<session-id>/boss/job/publish/status
POST /v1/sessions/<session-id>/boss/job/publish/submit
POST /v1/sessions/<session-id>/boss/job/update/start
POST /v1/sessions/<session-id>/boss/job/update/draft
POST /v1/sessions/<session-id>/boss/job/update/submit
POST /v1/sessions/<session-id>/boss/job/close
```

These mirror the local companion API. The relay unwraps successful local responses and forwards local errors as HTTP errors.

Long OCR scans are allowed to run synchronously. Set both relay and connector timeouts to about 900 seconds for testing:

```bash
BOSS_HR_RELAY_REQUEST_TIMEOUT=900
BOSS_HR_CONNECTOR_LOCAL_TIMEOUT=900
```

## Security Boundary

- Use a long random `BOSS_HR_RELAY_TOKEN`.
- Use per-user unpredictable session ids.
- Prefer HTTPS/WSS in production.
- Do not put phone numbers or SMS codes in relay logs.
- The relay never solves slider captcha or BOSS app safety confirmation.
- The user still completes slider, SMS, and app confirmation locally.

## MVP Limitation

This relay uses one shared token for both connector and cloud-agent API calls. For production, replace it with per-user issued tokens and an explicit pairing flow.
