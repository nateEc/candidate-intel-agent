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
```

## Create Or Reuse Intelligence Request

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

## Recommended OpenClaw Skill Logic

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

## Data Boundary

The Intel Agent currently uses BOSS-only domestic data:

- BOSS job postings
- BOSS talent database cards
- BOSS online resume OCR snapshots visible to the logged-in account

OpenClaw-facing responses should describe this as "BOSS-only organization intelligence", not as confirmed complete org structure.
