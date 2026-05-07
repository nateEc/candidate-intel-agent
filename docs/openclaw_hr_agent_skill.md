# OpenClaw Skill: BOSS HR Browser Agent

## Purpose

Use this skill when the user wants the HR agent to operate BOSS Zhipin in their local browser.

Examples:

- "帮我登录 BOSS 招聘者账号"
- "打开 BOSS，帮我进入招聘者身份"
- "帮我发一个 JD"
- "帮我去人才库搜后端工程师"
- "帮我看一下这个候选人的在线简历"

This skill talks to a local HR Browser Agent service running on the user's machine. The skill should not control BOSS directly and should not scrape hidden APIs.

## Local Service

Default base URL:

```text
http://127.0.0.1:8790
```

Environment variable:

```text
BOSS_HR_AGENT_BASE_URL=http://127.0.0.1:8790
```

If the HR agent runs in the cloud, do not call the user's `127.0.0.1`. Use relay mode.

Cloud relay environment variables:

```text
BOSS_HR_RELAY_BASE_URL=https://relay.example.com
BOSS_HR_RELAY_SESSION_ID=<user-session-id>
BOSS_HR_RELAY_TOKEN=<relay-token>
```

In relay mode, replace local endpoints with:

```text
<BOSS_HR_RELAY_BASE_URL>/v1/sessions/<BOSS_HR_RELAY_SESSION_ID>/...
```

and include:

```http
x-boss-relay-token: <BOSS_HR_RELAY_TOKEN>
```

The user's Mac must run the local connector:

```bash
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" connect \
  --relay-url "$BOSS_HR_RELAY_BASE_URL" \
  --session-id "$BOSS_HR_RELAY_SESSION_ID" \
  --token "$BOSS_HR_RELAY_TOKEN"
```

The local service can be installed and started by the agent if the host agent has terminal/shell execution.

```bash
curl -fsSL https://raw.githubusercontent.com/nateEc/candidate-intel-agent/main/scripts/bootstrap_boss_hr_agent.sh | bash
```

Foreground shortcut for manual development:

```bash
npm run hr:start
```

Background shortcut for Hermes/OpenClaw:

```bash
npm run hr:daemon
```

Installed CLI path:

```text
~/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent
```

Expected local browser:

```text
Chrome CDP: http://127.0.0.1:9240
Chrome profile: ~/Library/Application Support/BossHrAgent/chrome-profile
BOSS URL: https://www.zhipin.com/web/user/?ka=header-login
```

## Safety Rules

- Treat phone number and SMS code as sensitive.
- Do not store phone number or SMS code in memory longer than needed.
- Do not write phone number or SMS code into notes, logs, reports, or long-term memory.
- Never ask the local service to bypass BOSS safety verification.
- If BOSS asks for mobile app confirmation, tell the user to confirm in the BOSS app.
- If the service returns `needs_manual`, ask the user to look at the visible browser.
- Never say login succeeded until the service returns `logged_in` or `already_logged_in`.

## Login Flow

### 1. Health Check

Before starting in local-agent mode, call:

```http
GET /health
```

Before starting in cloud-agent relay mode, call:

```http
GET /v1/sessions/<session-id>/status
```

If the relay returns `404 session not connected`, the user has not connected their local companion yet. Say:

```text
我还没有看到你本机的 BOSS 连接器在线。请先打开本机 companion 并连接这次会话，连接后我会继续登录流程。
```

In local-agent mode, if unavailable and terminal/shell execution is available, do not ask the user to start it manually.

First, try the installed CLI:

```bash
"$HOME/Library/Application Support/BossHrAgent/service/bin/boss-hr-agent" start
```

If the CLI is missing, install and start the local companion service:

```bash
curl -fsSL https://raw.githubusercontent.com/nateEc/candidate-intel-agent/main/scripts/bootstrap_boss_hr_agent.sh | bash
```

Then poll `GET /health` every second for up to 30 seconds. Continue to the login flow once health is available.

Only ask the user to run a command if terminal/shell execution is unavailable or auto-start fails. In that case say:

```text
本机 BOSS HR Browser Agent 还没有启动，而且我这边无法自动启动。请先运行启动命令，我会继续接管登录流程。
```

### 2. Start Browser

Call:

```http
POST /v1/browser/start
```

Payload:

```json
{
  "start_url": "https://www.zhipin.com/web/user/?ka=header-login",
  "profile_dir": "/tmp/boss-hr-agent-recruiter",
  "cdp_port": 9240
}
```

Then call:

```http
POST /v1/boss/login/start
```

Expected response:

```json
{
  "status": "waiting_phone",
  "needs_input": "phone",
  "message": "请输入用于登录 BOSS 招聘者账号的手机号。"
}
```

If response is:

```json
{
  "status": "already_logged_in",
  "role": "recruiter"
}
```

Reply:

```text
你这台电脑上的 BOSS 招聘者账号已经登录好了，我可以继续帮你操作。
```

### 3. Ask For Phone

Only ask for phone when status is `waiting_phone`.

User-facing message:

```text
请发我用于登录 BOSS 招聘者账号的手机号。我只会把它传给你本机的浏览器服务，不会保存。
```

Then call:

```http
POST /v1/boss/login/send-code
```

Payload:

```json
{
  "phone": "<user_phone>"
}
```

Expected response:

```json
{
  "status": "waiting_sms_code",
  "needs_input": "sms_code"
}
```

Reply:

```text
验证码已经发送，请把短信验证码发给我。
```

If the service returns:

```json
{
  "status": "waiting_slider_captcha",
  "needs_input": "manual_slider"
}
```

Reply:

```text
BOSS 出现了滑动拼图验证。请在浏览器里手动完成滑块；完成后我会继续等待短信验证码状态。
```

Then poll:

```http
GET /v1/boss/login/status
```

Only ask for SMS code after the service returns `waiting_sms_code`.

### 4. Ask For SMS Code

Only ask for SMS code when status is `waiting_sms_code`.

Then call:

```http
POST /v1/boss/login/submit-code
```

Payload:

```json
{
  "sms_code": "<user_sms_code>"
}
```

Never repeat the SMS code back to the user.

### 5. Handle Identity Switch

If service returns:

```json
{
  "status": "maybe_switch_to_recruiter"
}
```

The local service should automatically click `切换` if the switch dialog is visible.

Reply only if the user needs context:

```text
BOSS 检测到当前账号是求职者身份，我正在帮你切换到招聘者身份。
```

Then poll:

```http
GET /v1/boss/login/status
```

### 6. Handle App Safety Confirmation

If service returns:

```json
{
  "status": "waiting_app_security_confirm",
  "needs_input": "app_confirm"
}
```

Reply:

```text
BOSS 需要你在手机 App 里完成安全登录确认。请打开 BOSS 直聘 App，点击确认。我会在这边等待页面完成登录。
```

Poll:

```http
GET /v1/boss/login/status
```

Recommended polling:

- Every 3 seconds for the first minute.
- Every 10 seconds for the next 4 minutes.
- After 5 minutes, ask whether the user wants to continue waiting or restart login.

### 7. Login Success

If service returns:

```json
{
  "status": "logged_in",
  "role": "recruiter"
}
```

Reply:

```text
BOSS 招聘者账号已经登录成功。现在可以继续帮你发 JD、搜人才或查看候选人。
```

## Status Handling

| Status | Meaning | Agent action |
| --- | --- | --- |
| `idle` | Service ready, login not started. | Start login. |
| `opening_login_page` | Browser opening login page. | Poll. |
| `waiting_phone` | Need phone. | Ask user for phone. |
| `sending_sms` | Sending SMS code. | Wait. |
| `waiting_slider_captcha` | Needs manual slider puzzle. | Ask user to solve slider in browser, poll. |
| `waiting_sms_code` | Need SMS code. | Ask user for SMS code. |
| `submitting_sms_code` | Submitting SMS code. | Wait. |
| `maybe_switch_to_recruiter` | May need identity switch. | Let service handle, poll. |
| `waiting_app_security_confirm` | Needs mobile app confirmation. | Ask user to confirm in app, poll. |
| `logged_in` | Recruiter login succeeded. | Continue HR actions. |
| `already_logged_in` | Existing profile is logged in. | Continue HR actions. |
| `needs_manual` | Unknown page or UI changed. | Ask user to inspect browser. |
| `failed` | Flow failed. | Explain failure and suggest restart. |

## Error Playbooks

### Service Not Running

Say:

```text
我还连不上你本机的 BOSS 浏览器服务。请先运行：

HR_AGENT_HOST=127.0.0.1 HR_AGENT_PORT=8790 ./scripts/start_boss_hr_agent.sh
```

### Browser Not Open

Call `POST /v1/browser/start`. If it still fails, say:

```text
本机 Chrome 没有成功启动。请确认已安装 Google Chrome，并且没有其他进程占用 9240 端口。
```

### SMS Code Expired Or Wrong

Say:

```text
这个验证码可能已过期或输入错误。我可以重新发送验证码。
```

Then call `POST /v1/boss/login/send-code` only after the user confirms.

### App Confirmation Timeout

Say:

```text
手机 App 确认还没有完成。你可以继续在 App 里确认，或者我帮你重新开始登录流程。
```

### BOSS Page Changed

If status is `needs_manual`, say:

```text
BOSS 当前页面和我认识的登录流程不完全一样。请看一下浏览器里是否有额外弹窗或验证提示；处理完后我会继续检测。
```

## Next HR Actions After Login

After login, route user intents to structured local actions:

| User intent | Local endpoint |
| --- | --- |
| "进入人才库" | `POST /v1/boss/navigate {"target":"talent_search"}` |
| "发布 JD" | `POST /v1/boss/action/post-job` |
| "搜索候选人" | `POST /v1/boss/action/search-candidates` |
| "打开候选人简历" | `POST /v1/boss/action/open-candidate` |
| "保存这个候选人" | `POST /v1/boss/action/save-visible-candidate` |

For the first MVP, only login and navigation are required. Job posting and candidate workflows can be added after login is stable.

## Conversation Example

User:

```text
帮我登录 BOSS 招聘者账号
```

Agent:

```text
我先打开你本机的 BOSS 登录页，并切到招聘者登录。
```

Service returns `waiting_phone`.

Agent:

```text
请发我用于登录 BOSS 招聘者账号的手机号。我只会把它传给你本机的浏览器服务，不会保存。
```

User:

```text
13800138000
```

Agent calls send code. Service returns `waiting_sms_code`.

Agent:

```text
验证码已经发送，请把短信验证码发给我。
```

User:

```text
123456
```

Agent calls submit code. Service returns `waiting_app_security_confirm`.

Agent:

```text
BOSS 需要你在手机 App 里完成安全登录确认。请打开 BOSS 直聘 App，点击确认。我会在这边等待页面完成登录。
```

Service returns `logged_in`.

Agent:

```text
BOSS 招聘者账号已经登录成功。现在可以继续帮你发 JD、搜人才或查看候选人。
```
