from __future__ import annotations

import re
from typing import Any


DEFAULT_VERSION = "rules_v1"


def evaluate_candidate(
    candidate: dict[str, Any],
    job_profile: dict[str, Any] | None = None,
    resume_text: str | None = None,
) -> dict[str, Any]:
    job_profile = job_profile or {}
    resume_text = resume_text or ""
    haystack = searchable_text(candidate, resume_text)
    keywords = normalize_keywords(job_profile)

    score = 20
    reasons: list[str] = []
    risks: list[str] = []

    keyword_score, matched_keywords = score_keywords(haystack, keywords)
    score += keyword_score
    if matched_keywords:
        reasons.append("匹配关键词：" + "、".join(matched_keywords[:8]))
    elif keywords:
        risks.append("未命中岗位核心关键词")

    experience_score, experience_reason, experience_risk = score_experience(candidate, job_profile)
    score += experience_score
    if experience_reason:
        reasons.append(experience_reason)
    if experience_risk:
        risks.append(experience_risk)

    education_score, education_reason, education_risk = score_education(candidate, job_profile)
    score += education_score
    if education_reason:
        reasons.append(education_reason)
    if education_risk:
        risks.append(education_risk)

    if resume_text:
        score += 10
        reasons.append("已读取在线简历，评估信息较完整")
    else:
        risks.append("缺少在线简历文本，评估置信度较低")

    if "刚刚活跃" in str(candidate.get("active_status") or "") or "在线" in str(candidate.get("active_status") or ""):
        score += 5
        reasons.append("候选人近期活跃")

    score = max(0, min(100, score))
    grade = grade_for_score(score)
    action = "greet" if grade == "A" else "review" if grade == "B" else "archive"

    return {
        "score": score,
        "grade": grade,
        "reasons": reasons or ["信息不足，建议人工复核"],
        "risks": risks,
        "recommended_action": action,
        "evaluator_version": DEFAULT_VERSION,
    }


def searchable_text(candidate: dict[str, Any], resume_text: str) -> str:
    parts = [
        candidate.get("masked_name"),
        candidate.get("current_title"),
        candidate.get("current_company"),
        candidate.get("expected_position"),
        candidate.get("short_summary"),
        candidate.get("detail_summary"),
        resume_text,
    ]
    for key in ("tags_json", "detail_tags_json", "detail_companies_json", "detail_positions_json"):
        value = candidate.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(str(part or "") for part in parts).lower()


def normalize_keywords(job_profile: dict[str, Any]) -> list[str]:
    explicit = job_profile.get("required_keywords") or job_profile.get("keywords") or []
    if isinstance(explicit, str):
        explicit = re.split(r"[,，/、\s]+", explicit)
    keywords = [str(item).strip().lower() for item in explicit if str(item).strip()]

    job_title = str(job_profile.get("job_title") or job_profile.get("title") or "").strip()
    if job_title:
        keywords.extend(item.lower() for item in re.split(r"[,，/、\s_\\-]+", job_title) if len(item) >= 2)

    return unique(keywords)


def score_keywords(haystack: str, keywords: list[str]) -> tuple[int, list[str]]:
    if not keywords:
        return 15, []
    matched = [keyword for keyword in keywords if keyword and keyword in haystack]
    ratio = len(matched) / max(1, len(keywords))
    return int(min(35, round(35 * ratio))), matched


def score_experience(candidate: dict[str, Any], job_profile: dict[str, Any]) -> tuple[int, str | None, str | None]:
    minimum = parse_int(job_profile.get("min_years") or job_profile.get("minimum_years"))
    years = parse_years(candidate.get("years_experience"))
    if minimum is None:
        return 10, None, None
    if years is None:
        return 4, None, "工作年限无法确认"
    if years >= minimum:
        return 15, f"工作年限 {years} 年，达到岗位要求", None
    return 3, None, f"工作年限 {years} 年，低于岗位要求 {minimum} 年"


def score_education(candidate: dict[str, Any], job_profile: dict[str, Any]) -> tuple[int, str | None, str | None]:
    required = str(job_profile.get("education") or job_profile.get("minimum_education") or "").strip()
    current = str(candidate.get("education_level") or "").strip()
    if not required:
        return 8, None, None
    if not current:
        return 3, None, "学历信息缺失"
    if education_rank(current) >= education_rank(required):
        return 10, f"学历 {current} 满足要求", None
    return 2, None, f"学历 {current} 低于要求 {required}"


def grade_for_score(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def parse_years(value: Any) -> int | None:
    text = str(value or "")
    if "10年以上" in text:
        return 10
    match = re.search(r"(\d+)年", text)
    return int(match.group(1)) if match else None


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def education_rank(value: str) -> int:
    ranks = {"中专": 1, "高中": 1, "大专": 2, "本科": 3, "硕士": 4, "博士": 5}
    return max((rank for key, rank in ranks.items() if key in value), default=0)


def unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
