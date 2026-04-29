from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


ROLE_FAMILIES = {
    "算法/AI": ("算法", "机器学习", "深度学习", "大模型", "NLP", "CV", "LLM", "AI"),
    "后端/工程": ("后端", "Java", "Go", "Golang", "Python", "服务端", "开发工程师", "工程师", "研发", "全栈", "Infra", "SRE", "系统", "架构"),
    "产品": ("产品", "PM", "产品经理"),
    "运营": ("运营", "增长", "用户运营", "内容运营", "策略运营"),
    "市场/品牌": ("市场", "品牌", "营销", "公关", "PR", "投放"),
    "销售/商务": ("销售", "商务", "BD", "客户成功", "解决方案"),
    "人力/组织": ("HR", "HRBP", "招聘", "人力", "组织发展", "OD"),
    "数据/分析": ("数据", "分析", "BI", "数仓"),
    "设计": ("设计", "视觉", "交互", "UI", "UX"),
    "法务/合规": ("法务", "合规", "律师"),
}

SENIOR_HINTS = ("总监", "负责人", "Head", "Lead", "Leader", "高级经理", "专家", "架构师", "Principal", "Staff")


def normalize_aliases(company: str, aliases: Iterable[str] | None = None) -> list[str]:
    values = [company, *(aliases or [])]
    normalized = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def contains_alias(text: str | None, aliases: Iterable[str]) -> bool:
    haystack = normalize_for_match(text)
    return any(normalize_for_match(alias) in haystack for alias in aliases if alias)


def normalize_for_match(text: str | None) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def parse_json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def role_family(text: str | None) -> str:
    normalized = normalize_for_match(text)
    for family, hints in ROLE_FAMILIES.items():
        if any(normalize_for_match(hint) in normalized for hint in hints):
            return family
    return "其他"


def count_top(values: Iterable[str | None], limit: int = 8) -> list[tuple[str, int]]:
    counter = Counter(value for value in values if value)
    return counter.most_common(limit)


def salary_range_k(salary_text: str | None) -> tuple[int | None, int | None]:
    if not salary_text or "面议" in salary_text:
        return (None, None)
    match = re.search(r"(\d{1,3})(?:-(\d{1,3}))?K", salary_text)
    if not match:
        return (None, None)
    low = int(match.group(1))
    high = int(match.group(2) or match.group(1))
    return (low, high)


def is_recent(iso_value: str | None, days: int, now: datetime | None = None) -> bool:
    if not iso_value:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        value = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value >= now - timedelta(days=days)


def has_senior_hint(text: str | None) -> bool:
    normalized = normalize_for_match(text)
    return any(normalize_for_match(hint) in normalized for hint in SENIOR_HINTS)
