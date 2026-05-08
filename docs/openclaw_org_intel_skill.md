# OpenClaw Skill: Org Intelligence

## Purpose

Use this skill when a user asks for company-level organization intelligence, competitor organization monitoring, hiring signals, talent movement, or BOSS-only org intel.

Examples:

- "我要看字节的组织情报"
- "帮我看一下月之暗面最近在招什么人"
- "腾讯最近有没有高阶人才流动信号"
- "更新一下 Kimi 的组织情报"

The skill talks to the local Intel Agent FastAPI service. OpenClaw should not scrape BOSS directly.
The Intel Agent backend is expected to own two logged-in BOSS Chrome/CDP sessions: recruiter talent-library on `9222` and geek job-search on `9223`.

## Service

Default base URL:

```text
http://127.0.0.1:8787
```

Recommended production config should use an environment variable:

```text
ORG_INTEL_BASE_URL=http://<intel-machine-ip>:8787
ORG_INTEL_API_TOKEN=<shared-secret>
```

When `ORG_INTEL_API_TOKEN` is configured on the Intel Agent service, every production request must include:

```http
Authorization: Bearer <shared-secret>
```

The `/health` endpoint is intentionally public for deployment checks.

## Single-company Intelligence Request

Use this path when the user asks for one company immediately, such as "我要看字节的组织情报".

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
  "refresh": "auto",
  "client_request_id": "openclaw-user-or-thread-id"
}
```

Fields:

| Field | Required | Notes |
| --- | --- | --- |
| `company` | yes | Canonical company name from the user request. |
| `aliases` | no | Known aliases, products, English names, business units. |
| `mode` | no | `quick`, `standard`, or `full`. Default `standard`. |
| `refresh` | no | `auto`, `none`, `jobs`, `candidates`, or `all`. Default `auto`. |
| `client_request_id` | no | OpenClaw conversation/request ID for traceability. |

Mode selection:

- `quick`: first-look answer, lighter capture, expected 5-10 min when fresh data is absent.
- `standard`: default org intel, expected 20-35 min when fresh data is absent.
- `full`: deeper capture, expected 60-120 min and more likely to hit platform verification.

## Response Handling

### Ready

If the intel database already has a fresh report, the service returns:

```json
{
  "status": "ready",
  "company": "月之暗面",
  "report_id": 4,
  "report_markdown": "...",
  "findings": [
    {
      "finding_type": "capability_build",
      "title": "算法/AI 是当前招聘建设重心",
      "severity": "medium",
      "confidence": 0.928,
      "summary": "..."
    }
  ],
  "message": "已有新鲜组织情报报告，直接返回。"
}
```

OpenClaw should summarize `report_markdown` directly to the user. If the user asks for evidence, use the `findings` and the report's folded raw-data section.

### Queued Or Running

If the report is not ready:

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

OpenClaw should reply:

```text
字节的组织情报需要重新采集，预计 35 分钟完成。我会稍后回来取报告。
```

Then poll:

```http
GET /v1/org-intel/requests/{job_id}
```

Recommended polling:

- First poll at `eta_at`.
- If still running, poll every 3-5 minutes.
- Stop after 3 failed/blocked attempts and tell the user.

### Blocked

If BOSS triggers verification:

```json
{
  "status": "blocked_needs_human",
  "message": "BOSS 触发登录/验证，需要人工处理后重新提交或等待 worker 重试。"
}
```

OpenClaw should not say the report is being generated normally. Say:

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

OpenClaw should expose the high-level failure and ask the operator to check the intel agent logs.

## Alias Extraction Guidance

When the user gives only a company name, OpenClaw should enrich aliases if known.

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

Use this path when the user asks for recurring CEO monitoring, such as:

- "每周给我看字节、腾讯、月之暗面的组织情报"
- "每月 1 号给我一份我关注公司的组织情报"
- "以后加上阿里"
- "现在生成一次周报"

Hipilot or an external scheduler owns cron and final message delivery. The Intel Agent owns subscription storage, data refresh, digest generation, and polling state.

### Create Subscription

```http
POST /v1/org-intel/subscriptions
```

```json
{
  "owner_id": "ceo-or-hipilot-user-id",
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
  "freshness_policy": "auto",
  "status": "active"
}
```

Response includes `id`; Hipilot should store this `subscription_id` in its user memory.

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

### Trigger Digest Run

```http
POST /v1/org-intel/subscriptions/{subscription_id}/digest-runs
```

```json
{
  "cadence": "weekly",
  "client_request_id": "hipilot-scheduled-run-id"
}
```

`cadence` can be `weekly` or `monthly`. The backend uses:

- weekly: `weekly_since_days`, default 14 days
- monthly: `monthly_since_days`, default 45 days
- refresh: subscription `freshness_policy`, default `auto`

If an active digest run already exists for the same subscription and cadence, the service returns that run instead of creating duplicates.

### Poll Digest Run

```http
GET /v1/org-intel/digest-runs?owner_id=<owner_id>&subscription_id=<subscription_id>&cadence=monthly&limit=1
GET /v1/org-intel/digest-runs/{digest_job_id}
```

The list form is useful for "查看上一次月报" when Hipilot did not keep the latest `digest_job_id`.

Possible statuses:

| Status | Hipilot behavior |
| --- | --- |
| `queued` / `running` | Poll again at `eta_at`, then every 3-5 minutes. |
| `ready` | Send `digest_markdown` to the CEO. |
| `partial_ready` | Send `digest_markdown`, and explicitly call out blocked/failed companies. |
| `blocked_needs_human` | Tell the CEO that BOSS account verification needs ops handling. |
| `failed` | Tell the CEO the digest failed and ask ops to inspect Intel Agent logs. |

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

Hipilot or the external scheduler should trigger:

- Weekly: Monday 07:30 Asia/Shanghai
- Monthly: day 1 at 07:30 Asia/Shanghai

If the digest is not `ready` by 09:00, send a short status note first, keep polling, then send the final or partial digest when available.

## Recommended OpenClaw Skill Logic

### On-demand single-company request

Pseudo-code:

```python
def handle_org_intel_request(user_text, thread_id):
    company = extract_company(user_text)
    aliases = lookup_aliases(company)
    payload = {
        "company": company,
        "aliases": aliases,
        "mode": "standard",
        "refresh": "auto",
        "client_request_id": thread_id,
    }
    result = post("/v1/org-intel/requests", payload)

    if result["status"] == "ready":
        return result["report_markdown"]

    if result["status"] in ["queued", "running_jobs", "running_candidates", "importing", "generating_report"]:
        schedule_poll(result["job_id"], result["eta_at"])
        return f"{company} 的组织情报正在采集中，预计 {minutes(result['eta_seconds'])} 分钟后可取。"

    if result["status"] == "blocked_needs_human":
        return "BOSS 触发了安全验证，需要情报机器上的人工账号处理一下。"

    return "组织情报任务失败，需要检查 intel agent 服务日志。"
```

### Recurring CEO digest request

Pseudo-code:

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
        "freshness_policy": "auto",
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

## Data Boundary

The Intel Agent currently uses BOSS-only domestic data:

- BOSS job postings
- BOSS talent database cards
- BOSS online resume OCR snapshots visible to the logged-in account

OpenClaw-facing responses should describe this as "BOSS-only organization intelligence", not as confirmed complete org structure.
