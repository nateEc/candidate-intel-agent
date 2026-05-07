# BOSS Job Management Skill

This module covers A-岗位管理 workflows.

## W01 岗位发布

Purpose: help the HR user create a BOSS job post by filling the publish form in the visible browser.

Execution location: BOSS site, through the local HR Browser Agent or cloud relay.

Human confirmation: required before final publish.

### Input Contract

Required:

- `job_title`
- `job_description`
- `recruitment_type`
- `overseas_status`
- `job_type`
- `experience`
- `education`
- `salary_min_k`
- `salary_max_k`
- `salary_months`

Optional:

- `keywords`

### Service Endpoints

Local mode:

```http
POST /v1/boss/job/publish/start
POST /v1/boss/job/publish/draft
GET  /v1/boss/job/publish/status
POST /v1/boss/job/publish/submit
```

Cloud relay mode:

```http
POST /v1/sessions/<session-id>/boss/job/publish/start
POST /v1/sessions/<session-id>/boss/job/publish/draft
GET  /v1/sessions/<session-id>/boss/job/publish/status
POST /v1/sessions/<session-id>/boss/job/publish/submit
```

### Workflow

1. Ensure BOSS recruiter login is ready.
2. Call `publish/start` to open `https://www.zhipin.com/web/chat/job/list` and click `发布职位`.
3. Call `publish/draft` with the structured job fields.
4. If the response is `job_publish_draft_filled`, summarize the draft and ask the user to confirm.
5. Only after explicit confirmation, call `publish/submit` with `{ "confirm": true }`.
6. Treat `job_publish_submitted` as successful only when returned by the service. If submit returns `needs_manual`, explain that BOSS still requires page-side validation or confirmation and ask the user to inspect the browser.

### Safety

Do not publish if:

- the draft response is `needs_manual`
- the user has not explicitly confirmed
- required fields are missing
- the user asks for a prohibited or discriminatory job description

The agent may help rewrite the description before filling the form, but must not include contact details, discriminatory language, or platform-prohibited content.

## W01/W02 关闭职位

Purpose: close an active BOSS job from the job management list.

Execution location: BOSS site, through the local HR Browser Agent or cloud relay.

Human confirmation: required before closing.

### Input Contract

Required:

- `confirm: true`

Recommended:

- `job_title`: close the matching active job. If omitted, the service closes the first visible active job.

### Service Endpoints

Local mode:

```http
POST /v1/boss/job/close
```

Cloud relay mode:

```http
POST /v1/sessions/<session-id>/boss/job/close
```

Payload:

```json
{
  "job_title": "AI工程师",
  "confirm": true
}
```

### Workflow

1. Confirm the exact job title with the user.
2. Call `job/close` with `{ "job_title": "...", "confirm": true }`.
3. Treat `job_closed` as success.
4. If the service returns `needs_manual`, tell the user to inspect the BOSS page and do not claim success.

### Safety

Do not close if:

- the user has not explicitly confirmed
- the job title is ambiguous and multiple open jobs may match
- the service response is not `job_closed`
