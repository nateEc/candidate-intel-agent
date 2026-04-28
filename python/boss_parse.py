from __future__ import annotations

import hashlib
import calendar
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


EDUCATION_LEVELS = ("博士", "硕士", "本科", "大专", "高中", "中专")
STATUS_HINTS = ("考虑机会", "月内到岗", "随时到岗", "暂不考虑", "在校", "在职", "离职", "离校")
ACTIVE_STATUS_RE = re.compile(r"刚刚活跃|今日活跃|昨日活跃|本周活跃|本月活跃|\d+日内活跃|\d+周内活跃|\d+月内活跃")
PHONE_RE = re.compile(r"(?:\+?86[- ]?)?1[3-9]\d{9}")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
WECHAT_RE = re.compile(r"(?:微信|wechat|wx|VX|v信)[:：\s]*[A-Za-z][-_A-Za-z0-9]{5,19}")


@dataclass(frozen=True)
class ParsePolicy:
    max_summary_chars: int = 220
    max_detail_summary_chars: int = 360


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    lines = []
    for line in str(text).replace("\r", "").split("\n"):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def redact_sensitive_text(value: str | None) -> str:
    text = "" if value is None else str(value)
    text = PHONE_RE.sub("[redacted-phone]", text)
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = WECHAT_RE.sub("[redacted-wechat]", text)
    return text


def truncate_text(value: str | None, max_length: int) -> str:
    text = redact_sensitive_text(re.sub(r"\s+", " ", value or "").strip())
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 1)] + "…"


def parse_candidate_card_text(raw_text: str, policy: ParsePolicy | None = None) -> dict[str, Any]:
    policy = policy or ParsePolicy()
    text = normalize_text(raw_text)
    lines = text.split("\n") if text else []
    joined = " | ".join(lines)
    first_line = lines[0] if lines else ""

    salary = _match_first(joined, r"\b\d{1,3}(?:-\d{1,3})?K(?:·\d{1,2}薪)?\b|面议")
    age_text = _match_first(joined, r"\d{2}岁")
    age = int(age_text.replace("岁", "")) if age_text else None
    years_experience = _match_first(joined, r"\d{2}年应届生|\d{2}年毕业|\d+年(?:以上)?|经验不限|应届")
    education_level = next((level for level in EDUCATION_LEVELS if level in joined), None)
    job_status = next((hint for hint in STATUS_HINTS if hint in joined), None)
    active_status = _parse_active_status(joined) or "2月以上未活跃"
    masked_name = _parse_masked_name(first_line)
    expectation = _parse_expectation(lines, salary, text)
    school = _parse_school(lines, text)
    short_summary = _parse_summary(lines, policy.max_summary_chars, salary, education_level, job_status)
    tags = _parse_tags(lines)

    confidence_keys = (masked_name, age, years_experience, education_level, salary, short_summary)
    confidence = round(sum(1 for item in confidence_keys if item) / len(confidence_keys), 3)

    return {
        "masked_name": masked_name,
        "age": age,
        "years_experience": years_experience,
        "education_level": education_level,
        "expected_city": expectation["city"],
        "expected_position": expectation["position"],
        "expected_salary": salary,
        "job_status": job_status,
        "active_status": active_status,
        "school": school,
        "short_summary": short_summary,
        "tags_json": tags,
        "parsed_confidence": confidence,
    }


def parse_detail_text(raw_text: str, policy: ParsePolicy | None = None) -> dict[str, Any]:
    policy = policy or ParsePolicy()
    text = normalize_text(raw_text)
    lines = text.split("\n") if text else []
    return {
        "detail_summary": _pick_detail_summary(lines, policy.max_detail_summary_chars),
        "detail_tags_json": _parse_tags(lines, limit=16),
        "detail_schools_json": _compact(
            [truncate_text(line.replace("院校 ", ""), 100) for line in lines if re.search(r"大学|学院|学校", line)],
            limit=5,
        ),
        "detail_companies_json": _compact(
            [
                truncate_text(line, 120)
                for line in lines
                if re.search(r"公司|集团|科技|网络|传媒|咨询|股份|有限公司|Minimax|MiniMax", line)
            ],
            limit=8,
        ),
        "detail_positions_json": _compact(
            [
                truncate_text(line, 100)
                for line in lines
                if re.search(r"工程师|开发|产品|运营|设计|销售|市场|经理|顾问|算法|测试|数据", line)
            ],
            limit=8,
        ),
    }


def parse_resume_text(raw_text: str, policy: ParsePolicy | None = None) -> dict[str, Any]:
    text = normalize_resume_text(raw_text)
    detail = parse_detail_text(text, policy)
    return {
        **detail,
        "resume_text": text,
        "resume_text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
        "resume_sections_json": _extract_resume_sections(text.split("\n") if text else []),
    }


def normalize_resume_text(raw_text: str | None) -> str:
    text = redact_sensitive_text(normalize_text(raw_text))
    lines: list[str] = []
    previous = ""
    for line in text.split("\n") if text else []:
        cleaned = _clean_ocr_line(line)
        if not cleaned:
            continue
        if _is_resume_footer(cleaned):
            break
        if cleaned == previous:
            continue
        if _is_resume_ocr_noise(cleaned):
            continue
        lines.append(cleaned)
        previous = cleaned
    return "\n".join(lines)


def create_candidate_fingerprint(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("source_platform") or "boss_zhipin",
        candidate.get("masked_name"),
        candidate.get("age"),
        candidate.get("years_experience"),
        candidate.get("education_level"),
        candidate.get("school"),
        candidate.get("expected_city"),
        candidate.get("expected_position"),
        candidate.get("expected_salary"),
        candidate.get("short_summary"),
    ]
    normalized = [str(part).strip().lower() for part in parts if part not in (None, "")]
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:24]


def infer_last_seen_at(
    active_status: str | None,
    collected_at: datetime | None = None,
    local_timezone: str = "Asia/Shanghai",
) -> str:
    collected_at = collected_at or datetime.now(timezone.utc)
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)

    local_tz = ZoneInfo(local_timezone)
    local_now = collected_at.astimezone(local_tz)
    status = active_status or ""

    if status == "刚刚活跃":
        inferred = local_now
    elif status == "今日活跃":
        inferred = _start_of_local_day(local_now)
    elif status == "昨日活跃":
        inferred = _start_of_local_day(local_now - timedelta(days=1))
    elif status == "本周活跃":
        inferred = datetime.combine(
            (local_now - timedelta(days=local_now.weekday())).date(),
            time.min,
            local_tz,
        )
    elif status == "本月活跃":
        inferred = datetime(local_now.year, local_now.month, 1, tzinfo=local_tz)
    elif match := re.fullmatch(r"(\d+)日内活跃", status):
        inferred = local_now - timedelta(days=int(match.group(1)))
    elif match := re.fullmatch(r"(\d+)周内活跃", status):
        inferred = local_now - timedelta(weeks=int(match.group(1)))
    elif match := re.fullmatch(r"(\d+)月内活跃", status):
        inferred = _subtract_months(local_now, int(match.group(1)))
    elif status == "2月以上未活跃":
        inferred = _subtract_months(local_now, 2)
    else:
        inferred = _subtract_months(local_now, 2)

    return inferred.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_masked_name(first_line: str) -> str | None:
    match = re.search(r"[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z*＊]{1,12}", first_line)
    return match.group(0).replace("＊", "*") if match else None


def _parse_active_status(text: str) -> str | None:
    match = ACTIVE_STATUS_RE.search(text)
    return match.group(0) if match else None


def _parse_expectation(lines: list[str], salary: str | None, full_text: str) -> dict[str, str | None]:
    inline = re.search(r"期望(?:城市)?\s+([^\s]+)(?:\s+(.+?))?\s+职位\s", full_text)
    if inline:
        return {"city": inline.group(1), "position": (inline.group(2) or "").strip() or None}

    explicit = next((line for line in lines if line.startswith("期望 ")), None)
    if explicit:
        value = explicit.replace("期望", "", 1).strip()
        parts = [item.strip() for item in re.split(r"[·\-]", value) if item.strip()]
        return {"city": parts[0] if parts else None, "position": "/".join(parts[1:]) or None}

    line = next((item for item in lines if salary and salary in item), "")
    chunks = [item.strip() for item in re.split(r"[|｜]", line) if item.strip()]
    salary_index = next((idx for idx, item in enumerate(chunks) if salary and salary in item), -1)
    status_index = next((idx for idx, item in enumerate(chunks) if any(hint in item for hint in STATUS_HINTS)), -1)
    city = None
    position = None

    if status_index >= 0 and status_index + 1 < len(chunks):
        next_chunk = chunks[status_index + 1]
        if not salary or salary not in next_chunk:
            city = re.split(r"[·\-]", next_chunk)[0].strip() or None

    if salary_index > 0:
        before_salary = chunks[salary_index - 1]
        if not any(hint in before_salary for hint in STATUS_HINTS):
            parts = [item.strip() for item in re.split(r"[·\-]", before_salary) if item.strip()]
            city = city or (parts[0] if parts else None)
            position = "/".join(parts[1:]) or None

    return {"city": city, "position": position}


def _parse_school(lines: list[str], full_text: str) -> str | None:
    for index, line in enumerate(lines):
        if line.strip() in ("院校", "学校"):
            parts: list[str] = []
            for next_line in lines[index + 1 : index + 4]:
                if next_line.strip() in ("期望", "期望城市", "职位", "院校", "学校"):
                    break
                if "近14天" in next_line or "首次看到" in next_line or "该牛人" in next_line:
                    break
                parts.append(next_line.strip())
            if parts:
                return truncate_text(" ".join(parts), 100)

    marker = "院校 "
    index = full_text.rfind(marker)
    if index >= 0:
        return truncate_text(full_text[index + len(marker) :], 100)

    school_line = next((line for line in lines if re.search(r"大学|学院|学校", line)), None)
    if not school_line:
        return None
    cleaned = re.sub(r"^(院校|学校)\s*", "", school_line).strip()
    return truncate_text(cleaned.split("|")[-1], 80)


def _parse_summary(
    lines: list[str],
    max_length: int,
    salary: str | None,
    education_level: str | None,
    job_status: str | None,
) -> str:
    if len(lines) == 1:
        inline = _parse_inline_summary(lines[0], salary, education_level, job_status)
        if inline:
            return truncate_text(inline, max_length)

    for line in lines:
        if len(line) < 12:
            continue
        if "近14天" in line or "首次看到" in line:
            continue
        if re.search(r"\d{2}岁|\d+年|本科|大专|硕士|博士|\d{1,3}-\d{1,3}K", line):
            continue
        if re.search(r"期望|职位|院校|学校", line):
            continue
        return truncate_text(line, max_length)
    return ""


def _parse_inline_summary(line: str, salary: str | None, education_level: str | None, job_status: str | None) -> str:
    expectation = re.search(r"期望(?:城市)?\s", line)
    if not expectation:
        return ""
    before = line[: expectation.start()].strip()
    anchors = [
        salary,
        job_status,
        education_level,
        _match_first(line, r"\d{2}年应届生|\d{2}年毕业|\d+年(?:以上)?|经验不限|应届"),
    ]
    ordered = sorted([anchor for anchor in anchors if anchor], key=lambda item: before.rfind(item), reverse=True)
    for anchor in ordered:
        index = before.rfind(anchor)
        if index >= 0:
            return re.sub(r"^[-\s]+", "", before[index + len(anchor) :]).strip()
    return ""


def _parse_tags(lines: list[str], limit: int = 20) -> list[str]:
    tags: list[str] = []
    for line in lines:
        if re.search(r"^(期望|职位|院校|学校)\s*", line):
            continue
        if re.search(r"\d{2}岁|\d+年|\d{1,3}-\d{1,3}K|在职|离职|本科|大专|硕士|博士", line):
            continue
        if "·" in line or "活跃" in line:
            continue
        chunks = [chunk.strip() for chunk in re.split(r"\s+|,|，|、|\|", line) if chunk.strip()]
        for chunk in chunks:
            if 2 <= len(chunk) <= 24 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9+#./-]+", chunk):
                tags.append(chunk)
    return _compact(tags, limit)


def _pick_detail_summary(lines: list[str], max_length: int) -> str:
    start = next(
        (idx for idx, line in enumerate(lines) if re.search(r"岁|本科|硕士|博士|大专|在职|离职|考虑机会", line)),
        0,
    )
    for line in lines[start : start + 8]:
        if len(line) >= 24 and not re.search(r"工作经历|项目经验|教育经历|期望职位", line):
            return truncate_text(line, max_length)
    return ""


def _extract_resume_sections(lines: list[str]) -> dict[str, str]:
    markers = (
        "期望职位",
        "工作经历",
        "项目经历",
        "项目经验",
        "教育经历",
        "社团经历",
        "资格证书",
        "作品集",
        "自我评价",
    )
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in lines:
        marker = next((item for item in markers if line.startswith(item)), None)
        if marker:
            current = marker
            sections.setdefault(current, [])
            rest = line.replace(marker, "", 1).strip(" ：:|")
            if rest:
                sections[current].append(rest)
            continue
        if current:
            sections[current].append(line)

    return {key: "\n".join(value).strip() for key, value in sections.items() if "\n".join(value).strip()}


def _clean_ocr_line(line: str) -> str:
    cleaned = re.sub(r"\s+", " ", line or "").strip()
    cleaned = cleaned.replace("｜", "|").replace("丨", "|")
    cleaned = re.sub(r"^[·•\s]+$", "", cleaned)
    return cleaned


def _is_resume_ocr_noise(line: str) -> bool:
    if len(line) <= 1:
        return True
    if line in {"x", "XA", "联系Ta", "联系TA"}:
        return True
    if re.fullmatch(r"[：:|·•\-\s]+", line):
        return True
    if re.fullmatch(r"[A-Za-z]{1,3}", line) and line.lower() not in {"ai", "hr", "hrbp", "qa"}:
        return True
    return False


def _is_resume_footer(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            "为妥善保护牛人",
            "未经BOSS直聘",
            "任何用户不得将牛人",
            "BOSS直聘平台在线浏览牛人简历",
        )
    )


def _compact(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _match_first(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.I)
    return match.group(0) if match else None


def _start_of_local_day(value: datetime) -> datetime:
    return datetime.combine(value.date(), time.min, value.tzinfo)


def _subtract_months(value: datetime, months: int) -> datetime:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
