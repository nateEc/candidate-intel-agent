---
name: openclaw-org-intel
description: Internal API bridge subskill for org-intel. Use only when the parent org-intel skill explicitly needs to submit, poll, or manage BOSS candidate/talent intelligence through the Intel Agent HTTP API. Do not use as the top-level user-facing org intelligence skill.
version: 2.0.0
author: User-provided
license: Proprietary
metadata:
  hermes:
    tags: [openclaw, hipilot, org-intel-subskill, api-bridge, boss, talent, candidates, digest, subscription]
---

# OpenClaw / Hipilot Skill: Internal Candidate Intel API Bridge

## Routing Priority

This is **not** the top-level user-facing org intelligence skill.

If both `org-intel` and `openclaw-org-intel` are installed:

- User-facing requests like "我要理想汽车的组织情报", "帮我看一下小鹏汽车", "每周给我发竞对组织情报" must route to the parent `org-intel` skill first.
- The parent `org-intel` skill may then call this subskill to submit BOSS candidate tasks, poll task status, create subscriptions, or fetch candidate digest results.
- This subskill should not perform public WebSearch/WebFetch synthesis, produce the first full CEO-facing org report, or decide the final narrative by itself.
- Directly use this subskill only for explicit operator/API requests such as "调用 Intel API 提交候选人任务", "轮询这个 orgjob", "创建候选人情报订阅", or "检查 digest_run 状态".

## Purpose

Use this skill as a narrow HTTP bridge to the Intel Agent API for company-level candidate intelligence, competitor talent monitoring, talent movement, candidate activity, and candidate digest subscriptions.

Examples:

- Parent skill asks: "submit candidate intel request for 月之暗面 with refresh=candidates"
- Parent skill asks: "poll orgjob_20260509081740_5a036cd4"
- Parent skill asks: "create weekly candidate digest subscription for owner_id=..."
- Operator asks: "用 Intel API 检查这个 digest_run 的状态"

OpenClaw / Hipilot must not scrape BOSS directly. It only calls the Intel Agent HTTP API. This skill is **candidate-side only**: it must request candidate/talent-library refreshes and must not request job-posting refreshes or job-side capture. The Intel Agent backend owns BOSS login, CDP sessions, data refresh, report generation, subscription storage, and digest run state.

## Execution Model

This skill is designed primarily for **cloud Hipilot / OpenClaw agents**.

Cloud agents should:

- Use a reachable remote `ORG_INTEL_BASE_URL`, for example `https://intel-agent.example.com`.
- Include `Authorization: Bearer <ORG_INTEL_API_TOKEN>` on every `/v1/org-intel/*` request when a token is configured.
- Store `subscription_id` and latest `digest_job_id` in agent memory or durable state.
- Trigger weekly/monthly digest runs via agent scheduler or external cron.
- Poll request/digest status and deliver final Markdown back into the conversation.

Cloud agents should not:

- Start local services with `npm`, `uvicorn`, shell scripts, or `localhost`.
- Open Chrome, connect to CDP, or ask the CEO to log into BOSS.
- Run crawler scripts directly.
- Request jobs-side refreshes with `refresh: "jobs"` / `refresh: "all"` or subscription `freshness_policy: "jobs"` / `"all"`.
- Attempt to bypass BOSS login, slider captcha, SMS, or app safety checks.

Those operations happen only on the fixed Intel worker machine operated by us.

## Service

Production base URL comes from secret/config.

Current deployment example:

```text
ORG_INTEL_BASE_URL=http://115.190.10.83/org-intel
ORG_INTEL_API_TOKEN=<provided-by-operator>
```

Generic production form:

```text
ORG_INTEL_BASE_URL=https://<intel-agent-domain>
ORG_INTEL_API_TOKEN=***
```

Local developer default, for testing only:

```text
http://127.0.0.1:8787
```

When `ORG_INTEL_API_TOKEN` is configured on the Intel Agent service, every production request must include:

```http
Authorization: Bearer ***
```

The `/health` endpoint is intentionally public for deployment checks.

## Cloud HTTP Helper

When the cloud agent has generic code execution, use a small HTTP helper like this. Do not shell out to local repo scripts.

```python
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ["ORG_INTEL_BASE_URL"].rstrip("/")
API_TOKEN = os.environ.get("ORG_INTEL_API_TOKEN")


def org_intel_request(method, path, payload=None, query=None):
    url = BASE_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Org Intel API {error.code}: {body}") from error
```

## Single-company Intelligence Request

Use this path when the parent `org-intel` skill or an operator explicitly asks this bridge to submit one company's candidate/talent intelligence request.

Endpoint:

```http
POST /v1/org-intel/requests
```

Request body:

```json
{
  "company": "字节",
  "aliases": ["字节跳动", "ByteDance", "抖音", "TikTok", "飞书"],
  "mode": "standard",
  "refresh": "candidates",
  "client_request_id": "openclaw-user-or-thread-id"
}
```

Fields:

| Field | Required | Notes |
| --- | --- | --- |
| `company` | yes | Canonical company name from the user request. |
| `aliases` | no | Known aliases, products, English names, business units. |
| `mode` | no | `quick`, `standard`, or `full`. Default `standard`. |
| `refresh` | no | For this skill, use only `candidates` or `none`. Default to `candidates`. Do not use `auto`, `jobs`, or `all` here. |
| `client_request_id` | no | OpenClaw conversation/request ID for traceability. |

Mode selection:

- `quick`: first-look answer, lighter capture, expected 5–10 min when fresh data is absent.
- `standard`: default org intel, expected 20–35 min when fresh data is absent.
- `full`: deeper capture, expected 60–120 min and more likely to hit platform verification.

Default to `standard` unless the user explicitly asks for faster or deeper analysis.

Candidate-only request rule:

- Default every on-demand request to `"refresh": "candidates"`.
- Use `"refresh": "none"` only for cache/demo/test mode.
- Never send `"refresh": "jobs"` or `"refresh": "all"` from this skill.
- Avoid `"refresh": "auto"` for now because it may decide to refresh job-side data when the job table is stale.
- If a returned report contains historical job-posting sections, omit those sections in the user-facing answer and summarize only candidate/talent activity, online resume, seniority, role-family, school/company-background, salary-expectation, and mobility signals.

## Response Handling

### Ready

If the intel database already has a fresh report, the service may return:

```json
{
  "status": "ready",
  "company": "月之暗面",
  "report_id": 4,
  "report_markdown": "...",
  "findings": [
    {
      "finding_type": "talent_activity",
      "title": "算法/AI 相关人才活跃度较高",
      "severity": "medium",
      "confidence": 0.928,
      "summary": "..."
    }
  ],
  "message": "已有新鲜组织情报报告，直接返回。"
}
```

Action:

- Summarize `report_markdown` directly to the user.
- If the user asks for evidence, use `findings` and the report's folded raw-data section.
- Frame the output as talent/candidate intelligence. Do not add comparative disclaimers about job postings, open roles, public recruiting, or job-side data unless the user explicitly asks what data is excluded.

### Queued or Running

If the report is not ready, the service may return:

```json
{
  "status": "queued",
  "job_id": "orgjob_20260429145349_93adb427",
  "company": "字节",
  "eta_seconds": 2100,
  "eta_at": "2026-04-29T16:35:00+08:00",
  "message": "字节组织情报正在采集中，预计 35 分钟后可取。"
}
```

Important first-turn rule:

- If the initial `POST /v1/org-intel/requests` response contains a `job_id`, treat it as an async job even if the worker might finish quickly.
- Do **not** keep polling synchronously inside the same user turn.
- Immediately tell the user that no fresh candidate report was available and that collection has started, include `eta_seconds` / `eta_at`, then create a scheduled poll.
- Only return a report immediately when the initial `POST` returns `status: "ready"` **without** a `job_id`; that means the database already had a fresh cached report before this request.

Recommended user reply:

```text
我这边还没有字节的新鲜候选人情报，已经开始采集 BOSS 人才库可见信号。预计 35 分钟后完成；到时间我会自动回来取报告并发给你。
```

Then poll:

```http
GET /v1/org-intel/requests/{job_id}
```

Recommended polling:

- First poll at `eta_at`.
- If still running, poll every 3–5 minutes.
- Stop after 3 failed or blocked attempts and tell the user.
- If the first scheduled poll already finds `ready`, send the final report then; do not hide the initial ETA step from the user.

Treat these statuses as in progress:

- `queued`
- `running_jobs`
- `running_candidates`
- `importing`
- `generating_report`

### Selective Refresh Verification

In real runs, `refresh` behaves as a scoped refresh request and the final status payload can be used to verify what actually ran.

Example practical pattern:

- This skill should always use `"refresh": "candidates"` for production candidate intelligence. The final `progress.runs` may show:
  - `jobs: skipped`
  - `candidates: ready`
  - `import: ready`
  - `report: ready`
- This means the agent refreshed only candidate-side data, reused/skipped jobs-side refresh, then completed import + report generation normally.

Agent rule:

- Always pass `"refresh": "candidates"` unless the user explicitly asks for cache-only/test mode, in which case pass `"refresh": "none"`.
- After polling `GET /v1/org-intel/requests/{job_id}`, verify `progress.runs` before summarizing success.
- In the user-facing status/result, explicitly state that candidate-side refresh completed. If `jobs` appears in `progress.runs`, it should be `skipped`; do not present job-side data as part of this skill.
- If a run unexpectedly shows `jobs: ready`, treat it as stale/back-end behavior leakage: do not summarize job-side findings, and tell the operator this skill should be run with candidate-only refresh.

### Blocked

If BOSS triggers verification, the service may return:

```json
{
  "status": "blocked_needs_human",
  "message": "BOSS 触发登录/验证，需要人工处理后重新提交或等待 worker 重试。"
}
```

Do not say the report is being generated normally. Say:

```text
BOSS 触发了安全验证，需要情报机器上的人工账号处理一下。处理后我会继续刷新这份组织情报。
```

### Failed

If failed:

```json
{
  "status": "failed",
  "message": "..."
}
```

Expose the high-level failure and ask the operator to check the Intel Agent logs.

## Alias Extraction Guidance

When the parent `org-intel` skill passes only a company name, enrich aliases if known.

Examples:

| User company | Suggested aliases |
| --- | --- |
| 字节 | 字节跳动, ByteDance, 抖音, TikTok, 飞书 |
| 月之暗面 | Moonshot, moonshot.ai, Kimi |
| 腾讯 | Tencent, 腾讯科技, 腾讯云, 微信, WXG, PCG, CSIG, IEG, TEG |
| 阿里 | 阿里巴巴, Alibaba, 淘天, 阿里云, 钉钉 |
| 美团 | Meituan, 美团点评, 大众点评 |

Do not invent aliases if uncertain. Passing only `company` is acceptable.

## CEO Subscription Digest

Use this path when the parent `org-intel` skill or an operator explicitly asks this bridge to manage recurring CEO candidate/talent monitoring.

Parent/operator examples:

- "create weekly candidate digest subscription for 字节、腾讯、月之暗面"
- "patch this subscription and add 阿里"
- "start one weekly digest run now"
- "poll this digest_job_id"

The agent or an external scheduler owns cron and final message delivery. The Intel Agent owns subscription storage, candidate-side data refresh, digest generation, and polling state.

### Create Subscription

```http
POST /v1/org-intel/subscriptions
```

```json
{
  "owner_id": "ceo-or-agent-user-id",
  "display_name": "CEO 重点公司监控",
  "cadence": "weekly_and_monthly",
  "companies": [
    {"company": "字节", "aliases": ["字节跳动", "ByteDance", "抖音", "TikTok", "飞书"], "mode": "standard"},
    {"company": "腾讯", "aliases": ["Tencent", "腾讯科技", "腾讯云", "微信"], "mode": "standard"},
    {"company": "月之暗面", "aliases": ["Moonshot", "Kimi", "moonshot.ai"], "mode": "standard"}
  ],
  "timezone": "Asia/Shanghai",
  "weekly_since_days": 14,
  "monthly_since_days": 45,
  "freshness_policy": "candidates",
  "status": "active"
}
```

Response includes `id`; the agent should store this `subscription_id` in durable state.

Suggested keys:

```text
org_intel_subscription_id:<owner_id>
org_intel_subscription_companies:<owner_id>
org_intel_latest_weekly_digest_id:<owner_id>
org_intel_latest_monthly_digest_id:<owner_id>
```

### List / Read / Update Subscription

```http
GET /v1/org-intel/subscriptions?owner_id=<owner_id>
GET /v1/org-intel/subscriptions/{subscription_id}
PATCH /v1/org-intel/subscriptions/{subscription_id}
```

To add or remove companies, send the full desired company list in `companies`:

```json
{
  "companies": [
    {"company": "字节", "aliases": ["字节跳动", "ByteDance"], "mode": "standard"},
    {"company": "腾讯", "aliases": ["Tencent"], "mode": "standard"},
    {"company": "阿里", "aliases": ["阿里巴巴", "Alibaba", "阿里云"], "mode": "standard"}
  ]
}
```

If `status` is `paused`, digest generation returns `409`.

Candidate-only subscription rule:

- Set `freshness_policy` to `"candidates"` for normal weekly/monthly runs.
- Set `freshness_policy` to `"none"` only for test mode or cache-only previews.
- Do not set `freshness_policy` to `"auto"`, `"jobs"`, or `"all"` from this skill.
- If the backend-generated `digest_markdown` includes job-posting language, the agent should filter or summarize around candidate/talent sections only.

### Test mode: reuse existing reports only

For test runs where the user explicitly says not to refresh data and only use existing reports, set:

```json
{
  "freshness_policy": "none"
}
```

Practical rule:

- Use `freshness_policy: none` on the subscription when the goal is to validate digest generation without triggering candidate refresh.
- In user-facing wording, say clearly that the weekly/monthly digest is in **test mode** and will reuse existing reports only.
- This is especially useful for first-time cron setup, delivery testing, or previewing the digest format before enabling real refreshes.

### Trigger Digest Run

```http
POST /v1/org-intel/subscriptions/{subscription_id}/digest-runs
```

```json
{
  "cadence": "weekly",
  "client_request_id": "agent-scheduled-run-id"
}
```

`cadence` can be `weekly` or `monthly`. The backend uses:

- weekly: `weekly_since_days`, default 14 days
- monthly: `monthly_since_days`, default 45 days
- refresh: subscription `freshness_policy`; this skill should use `candidates` for production and `none` for cache-only tests.

If an active digest run already exists for the same subscription and cadence, the service returns that run instead of creating duplicates.

The agent should immediately do one of two things:

- If status is `ready` or `partial_ready`, deliver `digest_markdown`.
- If status is `queued` or `running`, tell the user the ETA and schedule/poll by `digest_job_id`.

### Poll Digest Run

```http
GET /v1/org-intel/digest-runs?owner_id=<owner_id>&subscription_id=<subscription_id>&cadence=monthly&limit=1
GET /v1/org-intel/digest-runs/{digest_job_id}
```

The list form is useful when the parent `org-intel` skill asks for the latest monthly digest and the agent did not keep the latest `digest_job_id`.

Possible statuses:

| Status | Agent behavior |
| --- | --- |
| `queued` / `running` | Poll again at `eta_at`, then every 3–5 minutes. |
| `ready` | Send `digest_markdown` to the user. |
| `partial_ready` | Send `digest_markdown`, and explicitly call out blocked/failed companies. |
| `blocked_needs_human` | Tell the user that BOSS account verification needs ops handling. |
| `failed` | Tell the user the digest failed and ask ops to inspect Intel Agent logs. |

Digest markdown is multi-company and intentionally aggregate-only:

```md
# CEO 组织情报周报 / 月报

## 一句话总览
## 本期最值得关注的 3-5 个信号
## 公司优先级排行
## 分公司摘要
## 风险/阻塞项
## 数据范围与置信度说明
```

### Cron Recommendation

The agent or external scheduler should trigger:

- Weekly: Monday 07:30 Asia/Shanghai
- Monthly: day 1 at 07:30 Asia/Shanghai

If the digest is not `ready` by 09:00, send a short status note first, keep polling, then send the final or partial digest when available.

### Scheduler Load-Shaping

Do not trigger every customer's weekly/monthly digest in the same minute. The Intel Agent backend queues work and reuses active single-company requests, but BOSS candidate capture still runs on a limited worker machine.

Recommended cloud scheduler behavior:

```python
def stable_jitter_minutes(subscription_id, cadence, window_minutes):
    return stable_hash(f"{subscription_id}:{cadence}") % window_minutes

# weekly
trigger_at = monday_0630_asia_shanghai + stable_jitter_minutes(subscription_id, "weekly", 120)

# monthly
trigger_at = day_1_0630_asia_shanghai + stable_jitter_minutes(subscription_id, "monthly", 150)
```

User-facing promise:

- Prefer “周一上午” / “每月1日上午” over an exact minute.
- If the user asks for an exact delivery time, trigger roughly two hours earlier with a small deterministic jitter.
- At the promised delivery time, if the digest is still `queued` or `running`, send a short status note and keep polling.

`client_request_id` should be deterministic and traceable, for example:

```text
hipilot:<owner_id>:<subscription_id>:weekly:2026-W20
hipilot:<owner_id>:<subscription_id>:monthly:2026-05
```

The backend reuses an active digest for the same `subscription_id + cadence`, so repeated scheduler calls during one active run should not create duplicate digest runs.

## Recommended OpenClaw Skill Logic

All pseudo-code below assumes `post()` and `get()` call remote `ORG_INTEL_BASE_URL`, not localhost.

### On-demand single-company request

```python
def handle_org_intel_request(user_text, thread_id):
    company = extract_company(user_text)
    aliases = lookup_aliases(company)
    payload = {
        "company": company,
        "aliases": aliases,
        "mode": "standard",
        "refresh": "candidates",
        "client_request_id": thread_id,
    }
    result = post("/v1/org-intel/requests", payload)

    if result["status"] == "ready" and not result.get("job_id"):
        return result["report_markdown"]

    if result["status"] in ["queued", "running_jobs", "running_candidates", "importing", "generating_report"]:
        schedule_poll(result["job_id"], result["eta_at"])
        return f"我这边还没有{company}的新鲜候选人情报，已经开始采集 BOSS 人才库可见信号。预计 {minutes(result['eta_seconds'])} 分钟后完成；到时间我会自动回来取报告并发给你。"

    if result["status"] == "ready" and result.get("job_id"):
        # This can happen only when polling an existing job, not as the first user-facing step.
        return result["report_markdown"]

    if result["status"] == "blocked_needs_human":
        return "BOSS 触发了安全验证，需要情报机器上的人工账号处理一下。"

    return "组织情报任务失败，需要检查 intel agent 服务日志。"
```

### Recurring CEO digest request

```python
def handle_ceo_subscription_request(user_text, owner_id):
    companies = extract_companies(user_text)
    cadence = extract_cadence(user_text)  # weekly / monthly / weekly_and_monthly
    payload = {
        "owner_id": owner_id,
        "display_name": "CEO 重点公司监控",
        "cadence": cadence,
        "companies": enrich_company_aliases(companies),
        "timezone": "Asia/Shanghai",
        "freshness_policy": "candidates",
    }
    subscription = post("/v1/org-intel/subscriptions", payload)
    remember(owner_id, "org_intel_subscription_id", subscription["id"])
    return f"已创建组织情报订阅：{', '.join(c['company'] for c in subscription['companies'])}。"


def run_scheduled_digest(subscription_id, cadence, cron_id):
    result = post(
        f"/v1/org-intel/subscriptions/{subscription_id}/digest-runs",
        {"cadence": cadence, "client_request_id": cron_id},
    )
    if result["status"] in ["queued", "running"]:
        schedule_poll(result["digest_job_id"], result["eta_at"])
        return "组织情报 digest 正在生成。"
    return deliver_digest_result(result)


def poll_digest(digest_job_id):
    result = get(f"/v1/org-intel/digest-runs/{digest_job_id}")
    if result["status"] in ["queued", "running"]:
        schedule_poll(result["digest_job_id"], result["eta_at"])
        return None
    return deliver_digest_result(result)


def deliver_digest_result(result):
    if result["status"] in ["ready", "partial_ready"]:
        return result["digest_markdown"]
    if result["status"] == "blocked_needs_human":
        return "BOSS 账号触发验证，需要运营处理后继续生成组织情报。"
    return "组织情报 digest 生成失败，需要检查 Intel Agent 服务日志。"
```

### Add / Remove Companies

When the parent `org-intel` skill asks this bridge to add or remove companies, the agent should:

1. Read the saved `subscription_id`.
2. `GET /v1/org-intel/subscriptions/{subscription_id}`.
3. Apply the company list change locally.
4. Send the full new `companies` array with `PATCH /v1/org-intel/subscriptions/{subscription_id}`.

Do not send only the delta company; the API treats `companies` as the full desired list.

### Generate Once Now

When the parent `org-intel` skill asks this bridge to generate one digest now:

1. Read saved `subscription_id`, or list by `owner_id` if memory is missing.
2. `POST /v1/org-intel/subscriptions/{subscription_id}/digest-runs`.
3. If running, remember `digest_job_id` and poll.
4. If ready/partial, deliver `digest_markdown` immediately.

### View Last Digest

When the parent `org-intel` skill asks this bridge to fetch the last digest:

```http
GET /v1/org-intel/digest-runs?owner_id=<owner_id>&cadence=monthly&limit=1
```

If the latest run is `ready` or `partial_ready`, send `digest_markdown`. If it is still running, resume polling. If there is no digest, offer to generate one now.

## Default Response Format

Unless the user explicitly asks for detail, keep the reply to roughly 8–12 lines and use this order.

### A. General candidate intelligence

1. **一句话结论** — one sentence only.
2. **关键信号** — up to 3 bullets:
   - active candidate role families
   - seniority / experience / education background
   - talent movement / activity level
3. **一句判断** — plain business interpretation.
4. **提示** — one short caveat: BOSS candidate-side only, incomplete, or classification issue.

### B. “最近有什么人才信号”

1. `最近活跃的人才主要来自：` followed by 4–8 representative role/background clusters.
2. `一句话判断：` summarize what this says about talent market or possible poaching window.
3. Optional caveat if classification is noisy.

Do not answer job-posting or open-position questions from this skill. If the user asks “最近在招什么人/有哪些岗位”, give a short boundary response such as `这版先看人才侧信号，我可以先按候选人活跃与人才流动帮你判断。` Do not mention public recruiting intelligence or job-side data.

### C. Talent movement

1. active role families
2. recent activity intensity
3. one-line interpretation of whether it is worth watching / poaching
4. one short caveat

## Classification-Anomaly Handling

Some reports may have obvious role-family misclassification, especially in fashion, retail, consumer brands, or franchise-heavy companies where candidate backgrounds like the following may be incorrectly tagged as `算法/AI` or `后端/工程`:

- 导购 / 店长 / 销售顾问
- 主播 / 穿搭博主 / 场控
- 商品企划 / 商品运营
- 服装设计师 / 图案设计师 / 工艺师
- 面料 / 辅料 / 开发跟单 / 供应链岗位

When this happens:

1. Do not repeat the classifier label as the main conclusion.
2. Re-interpret the talent focus using raw resume/profile text, not job-posting titles.
3. Add a short explicit warning near the top, for example: `这份报告的岗位自动分类存在偏差，以下判断以原始岗位标题为准。`
4. Prefer human business labels such as:
   - 零售销售
   - 商品 / 企划 / 供应链
   - 设计
   - 电商运营
   - 品牌 / 内容 / 直播
   - 人力 / HRBP

For traditional retail, fashion, apparel, or franchise-heavy companies, treat high counts of `算法/AI` or `后端/工程` with skepticism if the underlying titles are obviously non-technical.

## Cloud Smoke Test

Use this checklist before giving the skill to a cloud user:

1. `GET {ORG_INTEL_BASE_URL}/health` returns `ok: true`.
2. `POST /v1/org-intel/subscriptions` with token creates a subscription.
3. `GET /v1/org-intel/subscriptions?owner_id=<owner_id>` returns that subscription.
4. `POST /v1/org-intel/subscriptions/{id}/digest-runs` returns `ready`, `partial_ready`, `queued`, or `running`.
5. `GET /v1/org-intel/digest-runs/{digest_job_id}` returns the same digest run.
6. The agent stores `subscription_id` and `digest_job_id`.
7. The agent never attempts to start local services or connect to BOSS Chrome/CDP.

Minimal operator/API bridge test prompts:

```text
调用 Intel API 创建一个每周候选人情报订阅，关注月之暗面和腾讯。
调用 Intel API 生成一次周报。
调用 Intel API 查看上一次周报。
调用 Intel API 给订阅增加阿里。
调用 Intel API 暂停这个订阅。
```

## Data Boundary

This skill currently uses BOSS candidate-side domestic data on our worker machine:

- BOSS talent database cards
- BOSS online resume OCR snapshots visible to the logged-in account

User-facing responses should describe this as talent/candidate intelligence. Do not volunteer exclusions like “not job-side/public recruiting intelligence”; keep that boundary internal unless the user asks directly.

## User-Facing Wording Guardrails

Do not include these phrases in normal user replies:

- `岗位侧`
- `职位侧`
- `公开招聘`
- `job-side`
- `job-posting`
- `不是岗位侧`
- `not job`

Preferred wording:

- `候选人情报`
- `人才活跃信号`
- `人才流动窗口`
- `BOSS 人才库可见信号`

## Hermes Execution Note

When using this skill inside Hermes and the service returns an in-progress status for a single-company request (`queued`, `running_jobs`, `running_candidates`, `importing`, `generating_report`):

- Immediately tell the user the report is being collected and include the ETA.
- Create a `cronjob` to poll `GET /v1/org-intel/requests/{job_id}` at `eta_at`. The cron job must include a complete callback instruction, not just a `job_id` payload.
- If still in progress, re-schedule another poll 3–5 minutes later.
- On `ready`, deliver the Chinese summary directly back to the originating conversation.
- Stop and notify the user if the service becomes `blocked_needs_human` or `failed`.
- If the user asks after the ETA why the report has not arrived, do not create a new request. Immediately `GET /v1/org-intel/requests/{job_id}` and deliver the report if it is already `ready`.

Hermes must not do a blocking `time.sleep(...)` or tight polling loop in the same user turn after creating a single-company request. The correct UX is:

1. Current turn: submit request, return ETA, schedule cron.
2. Cron turn at `eta_at`: poll once.
3. If ready: send report. If still running: say it is still running only if the promised ETA has passed, then schedule another poll.

For recurring digests:

- Trigger weekly/monthly runs through the scheduler.
- Poll `GET /v1/org-intel/digest-runs/{digest_job_id}` until `ready`, `partial_ready`, `blocked_needs_human`, or `failed`.
- Deliver final digest Markdown back to the original conversation.
