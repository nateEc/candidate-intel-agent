# OpenClaw Skill: BOSS Recruiting Pipeline

## Purpose

Use this skill when the recruiter wants the agent to process BOSS applicants for an active job:

- W08: scan the BOSS chat inbox for applicants under one job.
- W09: evaluate applicants against a job profile.
- W10/W18: save applicants and resumes into the local talent store.
- W11: prepare a first greeting for high-fit applicants, then send only after explicit confirmation.
- W19: dedupe and merge candidates while saving.

The recruiter value is a ranked, auditable candidate worklist: who is worth replying to first, why, what resume evidence was captured, and which action is ready for HR confirmation.

## Service

Local mode:

```text
http://127.0.0.1:8790
```

Cloud relay mode:

```text
<BOSS_HR_RELAY_BASE_URL>/v1/sessions/<BOSS_HR_RELAY_SESSION_ID>
```

Relay calls must include:

```http
x-boss-relay-token: <BOSS_HR_RELAY_TOKEN>
```

Chrome/CDP defaults:

```text
HR service: 127.0.0.1:8790
Chrome CDP: 127.0.0.1:9240
BOSS page: https://www.zhipin.com/web/chat/index
Talent DB: data-python/boss_talent.sqlite
```

## Safety Rules

- Never send a greeting unless the recruiter explicitly confirms the exact visible message.
- `dry_run` should default to `true` for scans.
- Do not click `不合适` in P0.
- Do not bypass BOSS login, slider captcha, or app safety confirmation.
- Do not expose full phone numbers, SMS codes, or private contact details in summaries.
- If a page operation returns `needs_manual`, ask the recruiter to inspect the visible browser.

## W08-W10: Scan, Evaluate, Save

Use this when the recruiter says things like:

- "帮我巡检 AI工程师 的投递"
- "看一下这个岗位今天新来的候选人"
- "把这个岗位的投递人评估并入库"

Call:

```http
POST /v1/boss/applications/scan
```

Payload:

```json
{
  "job_filter": "AI工程师 _ 北京 20-30K",
  "limit": 20,
  "include_resumes": true,
  "detail_max_pages": 8,
  "candidate_wait_ms": 2600,
  "candidate_jitter_ms": 1400,
  "dry_run": true,
  "job_profile": {
    "job_title": "AI工程师",
    "required_keywords": ["Java", "SpringBoot", "AI"],
    "min_years": 3,
    "education": "本科"
  }
}
```

Behavior:

1. Open BOSS `沟通`.
2. Click `全部`, then use the `全部职位` selector to pick the requested job.
3. Scroll the left applicant list until `limit` is reached or BOSS shows `没有更多了`.
4. Open each applicant chat.
5. Read visible profile and chat summary.
6. Open the green online-resume button when available, OCR the resume modal page by page until the bottom, a repeated page, or `detail_max_pages`, then close the modal.
7. Evaluate candidate grade A/B/C/D.
8. Save candidate, application, resume snapshot, evaluation, and dedupe link.

Default pacing is intentionally conservative: wait about 1.2s after opening a candidate, and about 2.6s plus jitter between candidates. Only reduce these values for tiny local smoke tests.

Response shape:

```json
{
  "status": "ready",
  "scan_run_id": "appscan_...",
  "job_filter": "AI工程师 _ 北京 20-30K",
  "count": 20,
  "dry_run": true,
  "candidates": [
    {
      "source_fingerprint": "...",
      "candidate": {},
      "application": {},
      "evaluation": {
        "grade": "A",
        "score": 82,
        "reasons": [],
        "risks": [],
        "recommended_action": "greet"
      },
      "has_resume": true
    }
  ]
}
```

Agent reply should be recruiter-oriented:

```text
我已经巡检 AI工程师 这个岗位的 20 位投递人，入库 20 位。

优先处理：
1. 伊先生｜A｜82分｜Java/SpringBoot/10年以上/本科｜建议打招呼
2. 任校彤｜B｜63分｜Java/3年/本科｜建议人工复核

主要风险：
- 4 位没有打开在线简历，只能按聊天摘要和顶部资料评估。
- 2 位薪资期望高于当前岗位区间。
```

## Scan Status

Call:

```http
GET /v1/boss/applications/scan/{scan_run_id}
```

Use this if a cloud relay or UI needs to re-check a run record. The first P0 implementation runs synchronously, so most scans return `ready` in the initial response.

## W11: Prepare Greeting

Use this only after the recruiter has selected the visible candidate in BOSS, or after a scan result gives a specific `source_fingerprint` and the agent has navigated to that candidate.

To use the first BOSS common phrase:

```http
POST /v1/boss/greetings/prepare
```

Payload:

```json
{
  "quick_reply_index": 0,
  "source_fingerprint": "<candidate-source-fingerprint>",
  "job_title": "AI工程师"
}
```

To prepare a custom message:

```json
{
  "message_text": "你好，看到你做过 Java 和 SpringBoot，我们这个 AI 工程师岗位也需要类似经验，方便聊聊吗？",
  "source_fingerprint": "<candidate-source-fingerprint>",
  "job_title": "AI工程师"
}
```

Expected response:

```json
{
  "status": "confirmation_required",
  "required_confirmation": true,
  "input_text": "方便发一份你的简历过来吗？"
}
```

Tell the recruiter exactly what is in the input box and ask for confirmation:

```text
我已经把这句放进输入框了：
“方便发一份你的简历过来吗？”

确认发送的话，请回复“确认发送”。
```

## W11: Send Greeting

Only call this after explicit confirmation:

```http
POST /v1/boss/greetings/send
```

Payload:

```json
{
  "confirm": true,
  "expected_text": "方便发一份你的简历过来吗？",
  "source_fingerprint": "<candidate-source-fingerprint>",
  "job_title": "AI工程师"
}
```

If `expected_text` does not match the current input box, the service refuses to send and returns `confirmation_required`. Read the returned `input_text` back to the recruiter and ask again.

## Dedupe

P0 does not rely on a stable BOSS URL for chat applicants. The local store resolves candidates by:

- Resume hash when the online resume was captured.
- Otherwise a weak identity built from name, age, education, job, and chat-summary hash.

This is enough to avoid obvious duplicate rows while preserving the raw application and evaluation history for later manual correction.
