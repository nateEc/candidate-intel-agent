from __future__ import annotations

import hashlib
import re
from typing import Any


BOSS_DIGIT_MAP = str.maketrans(
    {
        "\ue031": "0",
        "\ue032": "1",
        "\ue033": "2",
        "\ue034": "3",
        "\ue035": "4",
        "\ue036": "5",
        "\ue037": "6",
        "\ue038": "7",
        "\ue039": "8",
        "\ue03a": "9",
    }
)

SALARY_RE = re.compile(r"\b\d{1,5}(?:-\d{1,5})?(?:K(?:·\d{1,2}薪)?|元/天)\b|面议")
EXPERIENCE_RE = re.compile(r"经验不限|在校/应届|\d+(?:-\d+)?年")
EDUCATION_RE = re.compile(r"学历不限|博士|硕士|本科|大专|高中|中专")
INTERNSHIP_DURATION_RE = re.compile(r"\d+天/周|\d+个月")


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = decode_boss_digits(text)
    lines = []
    for line in text.replace("\r", "").split("\n"):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def decode_boss_digits(text: str | None) -> str:
    return str(text or "").translate(BOSS_DIGIT_MAP)


def parse_job_card_text(raw_text: str, seed: dict[str, Any] | None = None) -> dict[str, Any]:
    seed = _normalize_seed(seed or {})
    text = normalize_text(raw_text)
    lines = text.split("\n") if text else []
    joined = " | ".join(lines)

    salary = seed.get("salary_text") or _match_first(joined, SALARY_RE)
    job_title = seed.get("job_title") or _pick_title(lines, salary)
    company_name = seed.get("company_name") or _pick_company(lines, job_title)
    job_city = seed.get("job_city") or _pick_city(lines)
    experience = seed.get("experience_requirement") or _match_first(joined, EXPERIENCE_RE)
    education = seed.get("education_requirement") or _match_first(joined, EDUCATION_RE)
    tags = seed.get("tags_json") or _pick_tags(lines)

    return {
        "job_title": job_title,
        "company_name": company_name,
        "job_city": job_city,
        "salary_text": salary,
        "experience_requirement": experience,
        "education_requirement": education,
        "recruiter_name": seed.get("recruiter_name"),
        "recruiter_title": seed.get("recruiter_title"),
        "tags_json": tags,
        "description": seed.get("description") or _pick_description(lines, job_title, salary, company_name),
        "raw_card_json": {**seed, "text": text},
    }


def create_job_fingerprint(posting: dict[str, Any]) -> str:
    parts = [
        posting.get("source_platform") or "boss_zhipin",
        posting.get("company_name"),
        posting.get("job_title"),
        posting.get("job_city"),
        posting.get("salary_text"),
        posting.get("experience_requirement"),
        posting.get("education_requirement"),
        posting.get("source_url"),
    ]
    normalized = [str(part).strip().lower() for part in parts if part not in (None, "")]
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:24]


def _match_first(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    return match.group(0) if match else None


def _normalize_seed(seed: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in seed.items():
        if isinstance(value, str):
            normalized[key] = decode_boss_digits(value)
        elif isinstance(value, list):
            normalized[key] = [decode_boss_digits(item) if isinstance(item, str) else item for item in value]
        else:
            normalized[key] = value
    return normalized


def _pick_title(lines: list[str], salary: str | None) -> str | None:
    for line in lines[:5]:
        if salary and salary in line:
            cleaned = line.replace(salary, "").strip(" |·-")
            if cleaned:
                return cleaned
        if not SALARY_RE.search(line) and not _looks_like_company(line):
            return line
    return lines[0] if lines else None


def _pick_company(lines: list[str], title: str | None) -> str | None:
    for line in lines:
        if title and line == title:
            continue
        if _looks_like_company(line):
            return re.split(r"\s+[|｜·]\s+", line)[0].strip()
    for line in lines:
        if title and line == title:
            continue
        if (
            SALARY_RE.search(line)
            or EXPERIENCE_RE.search(line)
            or EDUCATION_RE.search(line)
            or INTERNSHIP_DURATION_RE.search(line)
        ):
            continue
        if _pick_city([line]):
            continue
        if 2 <= len(line) <= 30:
            return re.split(r"\s+[|｜·]\s+", line)[0].strip()
    return None


def _pick_city(lines: list[str]) -> str | None:
    for line in lines:
        match = re.search(r"(北京|上海|深圳|广州|杭州|成都|武汉|南京|苏州|西安|天津|重庆)(?:[·\-\s][\u4e00-\u9fa5]{1,8})?", line)
        if match:
            return match.group(0)
    return None


def _pick_tags(lines: list[str]) -> list[str]:
    tags: list[str] = []
    for line in lines:
        if any(marker in line for marker in ("经验", "学历", "融资", "人数", "公司", "集团")):
            continue
        parts = [part.strip() for part in re.split(r"[ ,，|｜·/]+", line) if part.strip()]
        for part in parts:
            if 2 <= len(part) <= 18 and not SALARY_RE.search(part) and part not in tags:
                tags.append(part)
        if len(tags) >= 12:
            break
    return tags[:12]


def _pick_description(lines: list[str], title: str | None, salary: str | None, company: str | None) -> str | None:
    kept = []
    for line in lines:
        if line in (title, salary, company):
            continue
        if _looks_like_company(line):
            continue
        kept.append(line)
    return "\n".join(kept[:8]) or None


def _looks_like_company(line: str) -> bool:
    return bool(re.search(r"公司|集团|科技|网络|信息|咨询|传媒|股份|有限|Tencent|腾讯|字节|阿里|美团|百度", line, re.I))
