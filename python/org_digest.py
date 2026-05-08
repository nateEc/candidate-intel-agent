from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def render_ceo_digest(
    subscription: dict[str, Any],
    cadence: str,
    company_results: list[dict[str, Any]],
    since_days: int,
    generated_at: datetime | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    cadence_label = "周报" if cadence == "weekly" else "月报"
    ready = [item for item in company_results if item.get("status") == "ready"]
    blocked = [item for item in company_results if item.get("status") == "blocked_needs_human"]
    failed = [item for item in company_results if item.get("status") == "failed"]
    top_findings = top_digest_findings(ready)
    ranking = rank_companies(ready)

    lines = [
        f"# CEO 组织情报{cadence_label}（BOSS-only）",
        "",
        f"- 生成时间：{generated_at.astimezone(timezone.utc).isoformat()}",
        f"- 订阅：{subscription.get('display_name') or subscription.get('id')}",
        f"- 观察窗口：近 {since_days} 天",
        f"- 公司范围：{len(company_results)} 家，其中可用 {len(ready)} 家、阻塞 {len(blocked)} 家、失败 {len(failed)} 家",
        "",
        "## 一句话总览",
        "",
        overview_sentence(ready, blocked, failed),
        "",
        "## 本期最值得关注的 3-5 个信号",
        "",
        render_top_findings(top_findings),
        "",
        "## 公司优先级排行",
        "",
        render_ranking(ranking),
        "",
        "## 分公司摘要",
        "",
        render_company_summaries(company_results),
        "",
        "## 风险/阻塞项",
        "",
        render_risks(blocked, failed),
        "",
        "## 数据范围与置信度说明",
        "",
        "- 数据来源：BOSS 职位侧和人才库侧可见信息。",
        "- 置信度来自职位信号、人才活跃信号和规则化组织判断，不等同于完整组织结构确认。",
        "- 候选人信息保持脱敏；本 digest 不展示完整简历或联系方式。",
    ]
    return "\n".join(lines).strip() + "\n"


def overview_sentence(
    ready: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    failed: list[dict[str, Any]],
) -> str:
    if not ready:
        if blocked:
            return "本期关注公司尚未形成可交付 digest，主要原因是 BOSS 账号触发验证，需要运营侧处理后重试。"
        if failed:
            return "本期关注公司尚未形成可交付 digest，任务执行失败，需要检查 intel worker 日志。"
        return "本期关注公司还没有形成足够的组织情报信号。"

    high = sum(1 for item in ready for finding in item.get("findings", []) if finding.get("severity") == "high")
    companies = "、".join(item["company"] for item in ready[:5])
    suffix = ""
    if blocked or failed:
        suffix = f"；另有 {len(blocked) + len(failed)} 家公司存在阻塞或失败，详见风险区。"
    return f"本期 {len(ready)} 家公司形成可读信号，覆盖 {companies}，其中高优先级组织判断 {high} 条{suffix}"


def top_digest_findings(company_results: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    rows = []
    for result in company_results:
        for finding in result.get("findings", []):
            rows.append(
                {
                    "company": result["company"],
                    "title": finding.get("title") or "",
                    "severity": finding.get("severity") or "medium",
                    "confidence": float(finding.get("confidence") or 0),
                    "summary": finding.get("summary") or "",
                }
            )
    rows.sort(key=lambda item: (SEVERITY_WEIGHT.get(item["severity"], 0), item["confidence"]), reverse=True)
    return rows[:limit]


def render_top_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "本期没有足够强的跨公司高优先级信号。"
    rows = [["公司", "信号", "级别", "置信度", "摘要"]]
    for item in findings:
        rows.append(
            [
                item["company"],
                item["title"],
                severity_label(item["severity"]),
                f"{item['confidence']:.2f}",
                item["summary"],
            ]
        )
    return markdown_table(rows)


def rank_companies(company_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranking = []
    for result in company_results:
        findings = result.get("findings", [])
        score = sum(SEVERITY_WEIGHT.get(item.get("severity"), 0) * max(float(item.get("confidence") or 0), 0.1) for item in findings)
        high_count = sum(1 for item in findings if item.get("severity") == "high")
        ranking.append(
            {
                "company": result["company"],
                "score": round(score, 2),
                "high_count": high_count,
                "finding_count": len(findings),
                "top_title": findings[0].get("title") if findings else "暂无强信号",
            }
        )
    ranking.sort(key=lambda item: (item["score"], item["high_count"], item["finding_count"]), reverse=True)
    return ranking


def render_ranking(ranking: list[dict[str, Any]]) -> str:
    if not ranking:
        return "暂无可排序公司。"
    rows = [["排名", "公司", "优先级分", "高优先级信号", "组织判断数", "首要关注点"]]
    for index, item in enumerate(ranking, start=1):
        rows.append(
            [
                str(index),
                item["company"],
                f"{item['score']:.2f}",
                str(item["high_count"]),
                str(item["finding_count"]),
                item["top_title"],
            ]
        )
    return markdown_table(rows)


def render_company_summaries(company_results: list[dict[str, Any]]) -> str:
    if not company_results:
        return "暂无公司配置。"
    sections = []
    for result in company_results:
        status = result.get("status")
        company = result.get("company")
        if status != "ready":
            sections.append(f"### {company}\n\n- 状态：{status_label(status)}\n- 原因：{result.get('message') or result.get('error_message') or '暂无'}")
            continue
        findings = result.get("findings", [])
        report = result.get("report") or {}
        counts = json_loads(report.get("source_counts_json"), {})
        top = findings[:3]
        lines = [
            f"### {company}",
            "",
            f"- 样本：职位信号 {counts.get('job_postings', 0)} 条，人才活跃信号 {counts.get('candidate_signals', 0)} 条",
            f"- 首要判断：{top[0].get('title') if top else '暂无强信号'}",
        ]
        if top:
            lines.append("- 重点信号：" + "；".join(item.get("summary") or item.get("title") or "" for item in top))
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def render_risks(blocked: list[dict[str, Any]], failed: list[dict[str, Any]]) -> str:
    if not blocked and not failed:
        return "本期没有公司级阻塞或失败。"
    rows = [["公司", "状态", "说明"]]
    for item in [*blocked, *failed]:
        rows.append(
            [
                item.get("company") or "",
                status_label(item.get("status")),
                item.get("message") or item.get("error_message") or "",
            ]
        )
    return markdown_table(rows)


def severity_label(value: str | None) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value or "", value or "")


def status_label(value: str | None) -> str:
    return {
        "ready": "已完成",
        "partial_ready": "部分完成",
        "blocked_needs_human": "BOSS 验证阻塞",
        "failed": "失败",
        "queued": "排队中",
        "running": "执行中",
    }.get(value or "", value or "")


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    divider = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    body = ["| " + " | ".join(clean_cell(cell) for cell in row) + " |" for row in rows[1:]]
    return "\n".join([header, divider, *body])


def clean_cell(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "/")


def json_loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback
