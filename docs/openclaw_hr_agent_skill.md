# OpenClaw Skill: BOSS HR Browser Agent

## Purpose

Use this skill when the user wants the HR agent to operate BOSS Zhipin in their local browser.

Examples:

- "帮我登录 BOSS 招聘者账号"
- "打开 BOSS，帮我进入招聘者身份"
- "帮我发一个 JD"
- "发布一个后端工程师岗位"
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

If the HR agent runs in the cloud, do not call `127.0.0.1` under any circumstance. In a cloud runtime, `127.0.0.1` is the cloud sandbox, not the user's Mac. Use relay mode whenever `BOSS_HR_RELAY_BASE_URL` is configured.

Cloud relay environment variables:

```text
BOSS_HR_RELAY_BASE_URL=https://relay.example.com
BOSS_HR_RELAY_SESSION_ID=<user-session-id>
BOSS_HR_RELAY_TOKEN=<relay-token>
```

Current Metabot test defaults:

```text
BOSS_HR_RELAY_BASE_URL=http://115.190.10.83/boss-hr-relay
BOSS_HR_RELAY_SESSION_ID=nate-metabot-test
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

For first-time users, give this one-time install-and-connect command. Replace `<relay-token>` with the configured relay token:

```bash
curl -fsSL https://raw.githubusercontent.com/nateEc/candidate-intel-agent/main/scripts/bootstrap_boss_hr_agent.sh | bash -s -- connect-daemon \
  --relay-url http://115.190.10.83/boss-hr-relay \
  --session-id nate-metabot-test \
  --token <relay-token>
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
我还没有看到你本机的 BOSS 连接器在线。请在你的电脑终端运行下面这条连接命令；连接后回复“已连接”，我会继续接管 BOSS 登录流程。
```

Then include the one-time install-and-connect command from the Local Service section.

In local-agent mode only, if unavailable and terminal/shell execution is available, do not ask the user to start it manually.

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
| "发布 JD" / "发布职位" | W01 job publish endpoints below |
| "更新职位" / "修改 JD" | W02 job update endpoints below |
| "关闭职位" / "下架职位" | `POST /v1/boss/job/close` |
| "巡检投递" / "评估投递人" | `POST /v1/boss/applications/scan` |
| "给这个候选人打招呼" | `POST /v1/boss/greetings/prepare`, then `POST /v1/boss/greetings/send` after confirmation |
| "搜索候选人" | `POST /v1/boss/action/search-candidates` |
| "打开候选人简历" | `POST /v1/boss/action/open-candidate` |
| "保存这个候选人" | `POST /v1/boss/action/save-visible-candidate` |

For applicant inbox processing and recruiter-safe greetings, follow:

```text
docs/boss_recruiting_pipeline_skill.md
```

High-impact rule for W08-W11:

- Scanning and evaluation may run without confirmation.
- Sending any BOSS chat message requires explicit recruiter confirmation of the exact input text.
- Do not click `不合适` in P0.

## W01 Job Publish

Use this workflow when the user wants to create a new BOSS job post.

High-impact rule:

- Filling the form is allowed after the user provides the job details.
- Do not submit/publish the job until the user explicitly confirms the filled draft.
- If the user gives vague details, ask for missing fields before filling the draft.

Required fields:

```json
{
  "job_title": "后端工程师",
  "job_description": "岗位职责和任职要求...",
  "recruitment_type": "社招全职",
  "overseas_status": "境内岗位",
  "job_type": "其他后端开发",
  "experience": "3-5年",
  "education": "本科",
  "salary_min_k": 25,
  "salary_max_k": 50,
  "salary_months": 16
}
```

Optional:

```json
{
  "keywords": ["Python", "Go", "后端"]
}
```

Allowed common values:

- `recruitment_type`: `社招全职`, `应届校园招聘`, `实习生招聘`, `兼职招聘`
- `overseas_status`: `境内岗位`, `长期驻境外`, `短期境外出差`
- `experience`: `不限`, `1年以内`, `1-3年`, `3-5年`, `5-10年`, `10年以上`
- `education`: `不限`, `初中及以下`, `中专/中技`, `高中`, `大专`, `本科`, `硕士`, `博士`

Step 1, open the job publish page:

```http
POST /v1/boss/job/publish/start
```

Expected response:

```json
{
  "status": "job_publish_form_ready"
}
```

Step 2, fill draft:

```http
POST /v1/boss/job/publish/draft
```

Payload:

```json
{
  "recruitment_type": "社招全职",
  "job_title": "后端工程师",
  "job_description": "负责后端服务设计、开发和稳定性建设...",
  "overseas_status": "境内岗位",
  "job_type": "其他后端开发",
  "experience": "3-5年",
  "education": "本科",
  "salary_min_k": 25,
  "salary_max_k": 50,
  "salary_months": 16
}
```

If response is:

```json
{
  "status": "job_publish_draft_filled",
  "requires_confirmation": true
}
```

Summarize the draft and ask:

```text
我已经把岗位草稿填好了。请你在浏览器里快速确认一下职位名称、描述、类型、经验、学历和薪资。如果确认发布，请回复“确认发布这个职位”。
```

If response is `needs_manual`, ask the user to inspect the browser and do not publish.

Step 3, submit only after explicit confirmation:

```http
POST /v1/boss/job/publish/submit
```

Payload:

```json
{
  "confirm": true
}
```

If the user has not explicitly confirmed, do not call submit.

Treat `job_publish_submitted` as successful only when the service returns it after the page leaves the edit form or shows a success state. If submit returns `needs_manual`, tell the user the service clicked the real bottom `发布` button but BOSS still requires page-side validation or confirmation; do not claim the job was published.

## W02 Job Update

Use this workflow when the user wants to edit an existing BOSS job.

High-impact rule:

- Ask which job title to edit before opening the edit form.
- Only update editable fields. BOSS locks fields such as recruitment type, job title, job type, company, and work city after creation.
- Do not click `保存并发布` until the user explicitly confirms the edited draft.

Step 1, open the existing job edit form:

```http
POST /v1/boss/job/update/start
```

Payload:

```json
{
  "job_title": "AI工程师"
}
```

Expected response:

```json
{
  "status": "job_update_form_ready"
}
```

Step 2, fill only the fields that should change:

```http
POST /v1/boss/job/update/draft
```

Payload example:

```json
{
  "job_description": "更新后的岗位职责和任职要求...",
  "experience": "3-5年",
  "education": "本科",
  "salary_min_k": 25,
  "salary_max_k": 35,
  "salary_months": 12
}
```

If response is:

```json
{
  "status": "job_update_draft_filled",
  "requires_confirmation": true
}
```

Summarize what changed and ask:

```text
我已经把岗位更新草稿填好了。请你在浏览器里确认一下变更项。如果确认保存并发布，请回复“确认保存并发布这个职位更新”。
```

Step 3, submit only after explicit confirmation:

```http
POST /v1/boss/job/update/submit
```

Payload:

```json
{
  "confirm": true
}
```

Treat `job_update_submitted` as successful only when the service returns it. If the response is `needs_manual`, tell the user BOSS still requires page-side validation or confirmation; do not claim the update was saved.

## W01 Close Job

Use this workflow when the user wants to close or take down an active BOSS job.

High-impact rule:

- Closing a job is destructive for the active recruiting workflow.
- Ask which job to close if there is ambiguity.
- Only call the endpoint with `confirm: true` after the user explicitly confirms the exact job title.

Close by title:

```http
POST /v1/boss/job/close
```

Payload:

```json
{
  "job_title": "AI工程师",
  "confirm": true
}
```

If the user says to close the currently visible open job and there is no ambiguity, `job_title` may be omitted:

```json
{
  "confirm": true
}
```

Expected success:

```json
{
  "status": "job_closed",
  "job_title": "AI工程师"
}
```

If response is `confirmation_required`, ask the user to confirm. If response is `needs_manual`, do not claim the job was closed; tell the user BOSS still needs page-side inspection.

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
