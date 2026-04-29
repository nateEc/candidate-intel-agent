from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from org_intel import count_top, has_senior_hint, is_recent


def generate_org_findings(
    company: str,
    candidate_signals: list[dict[str, Any]],
    job_postings: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    generated_at = generated_at or datetime.now(timezone.utc)
    findings = [
        build_hiring_focus_finding(company, job_postings, generated_at),
        build_talent_movement_finding(company, candidate_signals, generated_at),
        build_senior_signal_finding(company, candidate_signals, job_postings, generated_at),
        build_salary_pressure_finding(company, job_postings, generated_at),
        build_geo_focus_finding(company, job_postings, generated_at),
    ]
    return [finding for finding in findings if finding]


def build_hiring_focus_finding(
    company: str,
    job_postings: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if not job_postings:
        return None
    top = count_top([item.get("role_family") for item in job_postings], 3)
    if not top:
        return None
    top_family, top_count = top[0]
    total = len(job_postings)
    ratio = top_count / total
    severity = "high" if top_count >= 20 and ratio >= 0.45 else "medium" if top_count >= 5 else "low"
    confidence = clamp(0.45 + min(total, 120) / 240 + ratio * 0.25)
    samples = sample_job_titles(job_postings, top_family)
    return finding(
        company,
        "capability_build",
        f"{top_family} 是当前招聘建设重心",
        severity,
        confidence,
        f"职位侧 {total} 条样本中，{top_family} 方向有 {top_count} 条，占比 {ratio:.0%}，说明该能力方向正在被集中补强。",
        {
            "job_count": total,
            "top_families": [{"role_family": family, "count": count} for family, count in top],
            "sample_job_titles": samples,
        },
        generated_at,
    )


def build_talent_movement_finding(
    company: str,
    candidate_signals: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if not candidate_signals:
        return None
    recent_14 = [item for item in candidate_signals if is_recent(item.get("last_seen_at"), 14, generated_at)]
    recent_30 = [item for item in candidate_signals if is_recent(item.get("last_seen_at"), 30, generated_at)]
    if not recent_30:
        return None
    top = count_top([item.get("role_family") for item in recent_30], 3)
    severity = "high" if len(recent_14) >= 10 or len(recent_30) >= 20 else "medium" if len(recent_14) >= 3 else "low"
    confidence = clamp(0.4 + min(len(recent_30), 60) / 120 + (0.15 if recent_14 else 0))
    return finding(
        company,
        "talent_movement",
        "近期人才活跃信号需要进入挖猎观察池",
        severity,
        confidence,
        f"人才侧近14天活跃 {len(recent_14)} 人，近30天活跃 {len(recent_30)} 人，集中方向为 {format_counts(top)}。",
        {
            "recent_14_count": len(recent_14),
            "recent_30_count": len(recent_30),
            "top_families": [{"role_family": family, "count": count} for family, count in top],
            "sample_candidate_ids": [str(item.get("source_fingerprint", ""))[:8] for item in recent_30[:12]],
        },
        generated_at,
    )


def build_senior_signal_finding(
    company: str,
    candidate_signals: list[dict[str, Any]],
    job_postings: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    senior_jobs = [item for item in job_postings if item.get("senior_signal") or has_senior_hint(item.get("job_title"))]
    senior_candidates = [item for item in candidate_signals if item.get("senior_signal")]
    total = len(senior_jobs) + len(senior_candidates)
    if total == 0:
        return None
    severity = "high" if len(senior_jobs) >= 8 or len(senior_candidates) >= 5 else "medium"
    confidence = clamp(0.45 + min(total, 40) / 80)
    return finding(
        company,
        "senior_role_signal",
        "高阶岗位/负责人相关信号值得人工复核",
        severity,
        confidence,
        f"职位侧高阶信号 {len(senior_jobs)} 条，人才侧高阶活跃信号 {len(senior_candidates)} 条，建议复核是否对应新团队搭建、替补招聘或关键人窗口。",
        {
            "senior_job_count": len(senior_jobs),
            "senior_candidate_count": len(senior_candidates),
            "sample_job_titles": sample_job_titles(senior_jobs, None),
            "sample_candidate_ids": [str(item.get("source_fingerprint", ""))[:8] for item in senior_candidates[:12]],
        },
        generated_at,
    )


def build_salary_pressure_finding(
    company: str,
    job_postings: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    high_salary = [item for item in job_postings if (item.get("salary_high_k") or 0) >= 60]
    if not high_salary:
        return None
    top = sorted(high_salary, key=lambda item: item.get("salary_high_k") or 0, reverse=True)[:8]
    severity = "high" if len(high_salary) >= 10 else "medium"
    confidence = clamp(0.5 + min(len(high_salary), 30) / 60)
    return finding(
        company,
        "salary_pressure",
        "高薪岗位显示关键能力竞争强度较高",
        severity,
        confidence,
        f"职位侧发现 {len(high_salary)} 条薪资上沿 >=60K 的岗位，主要集中在 {format_counts(count_top([item.get('role_family') for item in high_salary], 3))}。",
        {
            "high_salary_count": len(high_salary),
            "samples": [
                {
                    "job_title": item.get("job_title"),
                    "salary_text": item.get("salary_text"),
                    "role_family": item.get("role_family"),
                }
                for item in top
            ],
        },
        generated_at,
    )


def build_geo_focus_finding(
    company: str,
    job_postings: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    city_counts = count_top([item.get("job_city") or item.get("search_city") for item in job_postings], 3)
    if not city_counts:
        return None
    top_city, top_count = city_counts[0]
    total = len(job_postings)
    ratio = top_count / total
    if total < 10 or ratio < 0.45:
        return None
    severity = "medium" if ratio < 0.7 else "high"
    confidence = clamp(0.45 + ratio * 0.35 + min(total, 80) / 200)
    return finding(
        company,
        "geo_focus",
        f"招聘地理重心集中在 {top_city}",
        severity,
        confidence,
        f"职位侧 {total} 条样本中，{top_city} 相关岗位 {top_count} 条，占比 {ratio:.0%}，可作为团队布局和挖猎地域优先级参考。",
        {
            "top_cities": [{"city": city, "count": count} for city, count in city_counts],
            "job_count": total,
        },
        generated_at,
    )


def finding(
    company: str,
    finding_type: str,
    title: str,
    severity: str,
    confidence: float,
    summary: str,
    evidence: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "company_name": company,
        "finding_type": finding_type,
        "title": title,
        "severity": severity,
        "confidence": round(confidence, 3),
        "summary": summary,
        "evidence_json": evidence,
        "generated_at": generated_at.isoformat(),
    }


def sample_job_titles(job_postings: list[dict[str, Any]], role_family: str | None, limit: int = 8) -> list[str]:
    values = []
    for item in job_postings:
        if role_family and item.get("role_family") != role_family:
            continue
        title = item.get("job_title")
        if title and title not in values:
            values.append(title)
        if len(values) >= limit:
            break
    return values


def format_counts(items: list[tuple[str, int]]) -> str:
    return "、".join(f"{name} {count}" for name, count in items) if items else "暂无"


def clamp(value: float, low: float = 0.0, high: float = 0.95) -> float:
    return max(low, min(high, value))
