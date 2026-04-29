# Intel Agent Fixed Machine Setup

This document describes how to run the org-intel service on one fixed macOS machine.

## What Must Be Running

The Intel machine needs three things:

1. A Chrome instance with remote debugging enabled.
2. A logged-in BOSS account in that Chrome profile.
3. The Intel Agent FastAPI service.

OpenClaw only talks to the FastAPI service. It does not control Chrome directly.

## One-Time Setup

From the repo root:

```bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Start Chrome with CDP:

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --remote-allow-origins=http://127.0.0.1:9222 \
  --user-data-dir=/tmp/boss-rpa-chrome \
  --no-first-run \
  https://www.zhipin.com/web/chat/search
```

Then log into BOSS manually in that Chrome window.

Verify CDP:

```bash
curl http://127.0.0.1:9222/json/list
```

## Start The Intel Service

Default local-only service:

```bash
npm run org:service
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

Expected:

```json
{"ok": true, "service": "org-intel-agent"}
```

## If OpenClaw Runs On Another Machine

Bind the service to the LAN address instead of localhost:

```bash
.venv/bin/uvicorn python.org_intel_service:app --host 0.0.0.0 --port 8787
```

Then configure OpenClaw:

```text
ORG_INTEL_BASE_URL=http://<intel-machine-lan-ip>:8787
```

Recommended network posture:

- Keep this service on a private network/VPN.
- Do not expose it publicly.
- Add an API token before public or cross-team deployment.

## Recommended Daily Operation

1. Keep the Chrome CDP window open.
2. Keep the BOSS account logged in.
3. Start the FastAPI service.
4. Let OpenClaw create and poll jobs.
5. If the API returns `blocked_needs_human`, open the Chrome window and finish BOSS verification manually.

## Start Everything With One Script

Use:

```bash
./scripts/start_org_intel_stack.sh
```

This starts Chrome CDP and the FastAPI service.

Environment variables:

```bash
ORG_INTEL_HOST=0.0.0.0
ORG_INTEL_PORT=8787
ORG_INTEL_DB=data-python/boss_talent.sqlite
ORG_INTEL_OUTPUT_DIR=org-intel
```

Example:

```bash
ORG_INTEL_HOST=0.0.0.0 ORG_INTEL_PORT=8787 ./scripts/start_org_intel_stack.sh
```

## API Smoke Test

Submit a request:

```bash
curl -X POST http://127.0.0.1:8787/v1/org-intel/requests \
  -H 'content-type: application/json' \
  -d '{
    "company": "月之暗面",
    "aliases": ["Moonshot", "Kimi", "moonshot.ai"],
    "mode": "standard",
    "refresh": "auto",
    "client_request_id": "manual-smoke"
  }'
```

If the database has a fresh report, this returns `ready`. Otherwise it returns a `job_id` and ETA.

Poll:

```bash
curl http://127.0.0.1:8787/v1/org-intel/requests/<job_id>
```

## Persistent Launch Option

For a fixed macOS machine, use one of these:

- Simple: run `./scripts/start_org_intel_stack.sh` inside a terminal/tmux session.
- Better: create a `launchd` plist that starts the uvicorn command at login.
- Operationally safest: use a small process supervisor and keep Chrome visible for manual verification.

Do not run Chrome headless for the first version. BOSS verification needs a visible browser.

## Troubleshooting

### Service returns `blocked_needs_human`

BOSS triggered a login or verification page. Open Chrome on the intel machine, finish the verification, then submit the request again.

### Service returns `queued` forever

Check whether the uvicorn process is still running. The worker thread lives inside the FastAPI process.

### Captures return 0 rows

Open the Chrome CDP window and confirm:

- Logged into BOSS.
- Not on a verification page.
- `curl http://127.0.0.1:9222/json/list` shows the BOSS page.

### OpenClaw cannot reach the service

If OpenClaw is remote, make sure uvicorn binds to `0.0.0.0`, the machine firewall allows port `8787`, and OpenClaw uses the LAN/VPN IP.
