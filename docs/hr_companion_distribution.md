# BOSS HR Local Companion Distribution

This document describes the lightweight install path for users who only want the HR browser agent, not the full organization-intelligence repo.

## Goal

A user should be able to install the OpenClaw/Hermes skill and say:

```text
帮我登录 BOSS 招聘者账号
```

If the local service is not running, the skill should install and start the companion automatically through shell execution.

## Installed Layout

Default install location:

```text
~/Library/Application Support/BossHrAgent/
  service/
    bin/boss-hr-agent
    python/
    scripts/
    requirements-hr-agent.txt
    .venv/
  chrome-profile/
  logs/service.log
  run/service.pid
```

## Bootstrap Command

The skill should run this when `GET http://127.0.0.1:8790/health` fails and the local CLI is not installed:

```bash
curl -fsSL https://raw.githubusercontent.com/nateEc/candidate-intel-agent/main/scripts/bootstrap_boss_hr_agent.sh | bash
```

The bootstrap script first tries the latest lightweight release artifact. If no release artifact exists yet, it falls back to the GitHub source archive and copies only the lightweight service files into the installed layout.

To force a specific artifact URL, set:

```bash
BOSS_HR_AGENT_ARCHIVE_URL=https://github.com/nateEc/candidate-intel-agent/releases/latest/download/boss-hr-agent-macos-latest.tar.gz
```

## Local CLI

After install:

```bash
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" start
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" status
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" stop
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" doctor
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" logs
```

## Release Package

Build a lightweight tarball from the repo:

```bash
npm run hr:package
```

Output:

```text
dist/boss-hr-agent-macos-<version>.tar.gz
dist/boss-hr-agent-macos-latest.tar.gz
```

The package includes only:

- `bin/boss-hr-agent`
- `requirements-hr-agent.txt`
- `python/boss_hr_browser_agent.py`
- `python/boss_login_flow.py`
- `python/boss_hr_relay_connector.py`
- `python/boss_cdp_capture.py`
- `python/boss_parse.py`
- `scripts/start_boss_hr_agent.sh`
- `scripts/start_boss_hr_agent_daemon.sh`

## Runtime Boundary

The companion can:

- Start a visible Chrome with a dedicated BOSS profile.
- Select recruiter login.
- Fill phone number.
- Click send SMS.
- Fill SMS code.
- Click login/register.
- Handle seeker-to-recruiter switching.
- Detect slider captcha and ask the user to solve it manually.
- Detect app safety confirmation and ask the user to confirm in the BOSS app.
- Navigate to supported BOSS pages after login.

The companion must not:

- Bypass captcha, slider puzzles, or BOSS app safety confirmation.
- Store phone numbers or SMS codes.
- Scrape hidden BOSS APIs.
- Run as a cloud service controlling a remote user's browser without a local companion.
