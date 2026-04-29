from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from org_intel import (
    contains_alias,
    count_top,
    has_senior_hint,
    is_recent,
    normalize_aliases,
    parse_json_list,
    role_family,
    salary_range_k,
)
from org_findings import generate_org_findings


def main() -> None:
    args = parse_args()
    target = load_target(args)
    db_path = Path(args.db).resolve()
    output_dir = Path(args.output_dir).resolve()
    generated_at = datetime.now(timezone.utc)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        candidate_signals = load_candidate_signals(conn, target["aliases"], args.since_days, generated_at)
        job_postings = load_job_postings(conn, target["aliases"], args.since_days, generated_at)
        findings = generate_org_findings(target["company"], candidate_signals, job_postings, generated_at)
        markdown = render_report(target, candidate_signals, job_postings, findings, args.since_days, generated_at)
        report_path = write_report(output_dir, target["company"], markdown, generated_at)
        save_report_record(conn, target, markdown, report_path, candidate_signals, job_postings, findings, generated_at)

    print(f"组织情报报告：{report_path}")
    print(f"候选人信号：{len(candidate_signals)}")
    print(f"职位信号：{len(job_postings)}")
    print(f"组织判断：{len(findings)}")


def load_target(args: argparse.Namespace) -> dict[str, Any]:
    if args.target_config:
        config = json.loads(Path(args.target_config).read_text(encoding="utf-8"))
        companies = config.get("companies", [])
        matched = next((item for item in companies if item.get("name") == args.company), None)
        if not matched:
            raise SystemExit(f"target config 里没有找到公司：{args.company}")
        aliases = normalize_aliases(matched["name"], matched.get("aliases", []))
        return {"company": matched["name"], "aliases": aliases}

    if not args.company:
        raise SystemExit("请传入 --company，或同时传入 --target-config 和 --company。")
    aliases = normalize_aliases(args.company, args.aliases or [])
    return {"company": args.company, "aliases": aliases}


def load_candidate_signals(
    conn: sqlite3.Connection,
    aliases: list[str],
    since_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    if not table_exists(conn, "candidates"):
        return []

    observations = latest_observations(conn)
    resumes = latest_resumes(conn) if table_exists(conn, "candidate_resume_snapshots") else {}
    rows = conn.execute("SELECT * FROM candidates").fetchall()
    signals = []
    for row in rows:
        candidate = dict(row)
        observation = observations.get(candidate["source_fingerprint"], {})
        resume = resumes.get(candidate["source_fingerprint"], {})
        if not is_recent(candidate.get("last_seen_at"), since_days, now) and not is_recent(
            observation.get("observed_at"), since_days, now
        ):
            continue

        evidence_text = "\n".join(
            str(value or "")
            for value in (
                candidate.get("short_summary"),
                candidate.get("expected_position"),
                candidate.get("school"),
                candidate.get("detail_summary"),
                " ".join(parse_json_list(candidate.get("detail_companies_json"))),
                " ".join(parse_json_list(candidate.get("detail_positions_json"))),
                resume.get("resume_text"),
            )
        )
        search_keyword = observation.get("search_keyword") or ""
        confidence = match_confidence(evidence_text, search_keyword, aliases)
        if confidence < 0.4:
            continue

        position_text = " ".join(
            [
                str(candidate.get("expected_position") or ""),
                " ".join(parse_json_list(candidate.get("detail_positions_json"))),
                str(candidate.get("short_summary") or ""),
            ]
        )
        signals.append(
            {
                **candidate,
                "search_keyword": search_keyword,
                "search_city": observation.get("search_city"),
                "match_confidence": confidence,
                "role_family": role_family(position_text),
                "senior_signal": has_senior_hint(position_text),
            }
        )
    signals.sort(key=lambda item: (item.get("match_confidence") or 0, item.get("last_seen_at") or ""), reverse=True)
    return signals


def latest_observations(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if not table_exists(conn, "candidate_observations"):
        return {}
    rows = conn.execute(
        """
        SELECT source_fingerprint, observed_at, search_keyword, search_city
        FROM candidate_observations
        ORDER BY observed_at
        """
    ).fetchall()
    return {row["source_fingerprint"]: dict(row) for row in rows}


def latest_resumes(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT source_fingerprint, collected_at, resume_text
        FROM candidate_resume_snapshots
        ORDER BY collected_at
        """
    ).fetchall()
    return {row["source_fingerprint"]: dict(row) for row in rows}


def match_confidence(evidence_text: str, search_keyword: str, aliases: list[str]) -> float:
    if contains_alias(evidence_text, aliases):
        return 0.9
    if contains_alias(search_keyword, aliases):
        return 0.45
    return 0.0


def load_job_postings(
    conn: sqlite3.Connection,
    aliases: list[str],
    since_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    if not table_exists(conn, "boss_job_postings"):
        return []
    rows = conn.execute("SELECT * FROM boss_job_postings ORDER BY collected_at DESC").fetchall()
    postings = []
    for row in rows:
        posting = dict(row)
        if not is_recent(posting.get("collected_at"), since_days, now):
            continue
        evidence = "\n".join(
            str(value or "")
            for value in (
                posting.get("company_name"),
                posting.get("job_title"),
                posting.get("description"),
                posting.get("search_keyword"),
            )
        )
        if not contains_alias(evidence, aliases):
            continue
        title_family = role_family(posting.get("job_title"))
        description_family = role_family(posting.get("description"))
        low, high = salary_range_k(posting.get("salary_text"))
        posting["role_family"] = title_family if title_family != "其他" else description_family
        posting["senior_signal"] = has_senior_hint(posting.get("job_title")) or has_senior_hint(posting.get("description"))
        posting["salary_low_k"] = low
        posting["salary_high_k"] = high
        postings.append(posting)
    return postings


def render_report(
    target: dict[str, Any],
    candidate_signals: list[dict[str, Any]],
    job_postings: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    since_days: int,
    generated_at: datetime,
) -> str:
    company = target["company"]
    aliases = "、".join(target["aliases"])
    recent_14 = sum(1 for item in candidate_signals if is_recent(item.get("last_seen_at"), 14, generated_at))
    recent_30 = sum(1 for item in candidate_signals if is_recent(item.get("last_seen_at"), 30, generated_at))
    senior_candidates = [item for item in candidate_signals if item.get("senior_signal")]
    senior_jobs = [item for item in job_postings if item.get("senior_signal")]

    lines = [
        f"# {company} 组织情报（BOSS-only）",
        "",
        f"- 生成时间：{generated_at.astimezone(timezone.utc).isoformat()}",
        f"- 观察窗口：近 {since_days} 天",
        f"- 匹配别名：{aliases}",
        f"- 数据范围：BOSS 职位信号 {len(job_postings)} 条，人才活跃信号 {len(candidate_signals)} 条",
        "",
        "## 一句话结论",
        "",
        summary_sentence(candidate_signals, job_postings, recent_14, recent_30),
        "",
        "## 核心组织判断",
        "",
        render_findings_section(findings),
        "",
        "## 高管动向",
        "",
        senior_summary(senior_candidates, senior_jobs),
        "",
        "## 他们在招什么人",
        "",
        render_jobs_section(job_postings, candidate_signals),
        "",
        "## 谁可能要走",
        "",
        render_candidate_section(candidate_signals, recent_14, recent_30),
        "",
        "## 组织架构全景",
        "",
        render_org_map(candidate_signals, job_postings),
        "",
        "<details>",
        "<summary>原始聚合数据（脱敏）</summary>",
        "",
        render_raw_candidate_table(candidate_signals),
        "",
        render_raw_job_table(job_postings),
        "",
        "</details>",
        "",
        "## 置信度说明",
        "",
        "- 已确认：BOSS 职位和人才活跃两侧均出现同一方向信号。",
        "- 中置信：只在职位侧或人才侧出现，但信号集中。",
        "- 待观察：样本少，或只有关键词搜索命中，没有简历/岗位文本交叉印证。",
    ]
    return "\n".join(lines).strip() + "\n"


def summary_sentence(
    candidate_signals: list[dict[str, Any]],
    job_postings: list[dict[str, Any]],
    recent_14: int,
    recent_30: int,
) -> str:
    top_jobs = count_top([item.get("role_family") for item in job_postings], 3)
    top_candidates = count_top([item.get("role_family") for item in candidate_signals], 3)
    if job_postings and candidate_signals:
        return (
            f"BOSS 信号显示，招聘侧集中在 {format_counts(top_jobs)}；"
            f"人才活跃侧集中在 {format_counts(top_candidates)}，其中近14天活跃 {recent_14} 人、近30天活跃 {recent_30} 人。"
        )
    if job_postings:
        return f"BOSS 职位侧已有样本，主要集中在 {format_counts(top_jobs)}；人才活跃侧暂未形成足够样本。"
    if candidate_signals:
        return f"BOSS 人才活跃侧已有样本，主要集中在 {format_counts(top_candidates)}；职位侧暂未导入样本。"
    return "当前数据库内还没有足够的 BOSS 信号形成判断。"


def senior_summary(candidates: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> str:
    if not candidates and not jobs:
        return "未发现足够强的 BOSS-only 高管/负责人变动信号。"
    parts = []
    if jobs:
        parts.append(f"职位侧出现 {len(jobs)} 条负责人/专家/高阶岗位相关信号，建议复核岗位 JD 和部门归属。")
    if candidates:
        parts.append(f"人才侧出现 {len(candidates)} 条负责人/专家/高阶岗位活跃信号，正文保持脱敏，建议进入人工复核池。")
    return "\n".join(f"- {part}" for part in parts)


def render_findings_section(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "当前样本不足，还没有形成可操作的组织判断。"
    rows = [["判断", "级别", "置信度", "摘要"]]
    for item in findings:
        rows.append(
            [
                item.get("title") or "",
                severity_label(item.get("severity")),
                f"{float(item.get('confidence') or 0):.2f}",
                item.get("summary") or "",
            ]
        )
    return markdown_table(rows)


def severity_label(value: str | None) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value or "", value or "")


def render_jobs_section(job_postings: list[dict[str, Any]], candidate_signals: list[dict[str, Any]]) -> str:
    if not job_postings:
        fallback = count_top([item.get("role_family") for item in candidate_signals], 6)
        if not fallback:
            return "职位侧还没有导入 BOSS 岗位数据。下一步先跑 `capture:jobs`。"
        return "职位侧还没有导入 BOSS 岗位数据；从人才期望岗位反推，关注方向为：" + format_counts(fallback)

    family_counts = count_top([item.get("role_family") for item in job_postings], 8)
    city_counts = count_top([item.get("job_city") or item.get("search_city") for item in job_postings], 8)
    salary_items = [item for item in job_postings if item.get("salary_low_k") is not None]
    high_salary = sorted(salary_items, key=lambda item: item.get("salary_high_k") or 0, reverse=True)[:5]

    lines = [
        f"- 岗位方向：{format_counts(family_counts)}",
        f"- 城市分布：{format_counts(city_counts)}",
    ]
    if high_salary:
        lines.append("- 高薪岗位样本：" + "；".join(f"{item.get('job_title')} {item.get('salary_text')}" for item in high_salary))
    return "\n".join(lines)


def render_candidate_section(candidate_signals: list[dict[str, Any]], recent_14: int, recent_30: int) -> str:
    if not candidate_signals:
        return "人才侧还没有可用信号。"
    family_counts = count_top([item.get("role_family") for item in candidate_signals], 8)
    status_counts = count_top([item.get("active_status") for item in candidate_signals], 8)
    salary_counts = count_top([item.get("expected_salary") for item in candidate_signals], 8)
    return "\n".join(
        [
            f"- 活跃强度：近14天 {recent_14} 人，近30天 {recent_30} 人。",
            f"- 方向分布：{format_counts(family_counts)}",
            f"- 活跃标签：{format_counts(status_counts)}",
            f"- 薪资期望：{format_counts(salary_counts)}",
        ]
    )


def render_org_map(candidate_signals: list[dict[str, Any]], job_postings: list[dict[str, Any]]) -> str:
    combined = [item.get("role_family") for item in candidate_signals] + [item.get("role_family") for item in job_postings]
    family_counts = count_top(combined, 10)
    if not family_counts:
        return "暂无足够数据生成组织能力地图。"
    rows = [["能力方向", "信号数", "判断"]]
    for family, count in family_counts:
        judgment = "重点关注" if count >= 5 else "待观察"
        rows.append([family, str(count), judgment])
    return markdown_table(rows)


def render_raw_candidate_table(candidate_signals: list[dict[str, Any]]) -> str:
    rows = [["ID", "方向", "期望城市", "期望薪资", "活跃", "置信度"]]
    for item in candidate_signals[:40]:
        rows.append(
            [
                str(item.get("source_fingerprint", ""))[:8],
                item.get("role_family") or "",
                item.get("expected_city") or "",
                item.get("expected_salary") or "",
                item.get("active_status") or "",
                f"{item.get('match_confidence'):.2f}",
            ]
        )
    return "### 人才活跃信号\n\n" + markdown_table(rows)


def render_raw_job_table(job_postings: list[dict[str, Any]]) -> str:
    rows = [["ID", "岗位", "公司", "城市", "薪资", "方向"]]
    for item in job_postings[:40]:
        rows.append(
            [
                str(item.get("source_fingerprint", ""))[:8],
                item.get("job_title") or "",
                item.get("company_name") or "",
                item.get("job_city") or item.get("search_city") or "",
                item.get("salary_text") or "",
                item.get("role_family") or "",
            ]
        )
    return "### 职位信号\n\n" + markdown_table(rows)


def format_counts(items: list[tuple[str, int]]) -> str:
    return "、".join(f"{name} {count}" for name, count in items) if items else "暂无"


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    divider = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    body = ["| " + " | ".join(clean_cell(cell) for cell in row) + " |" for row in rows[1:]]
    return "\n".join([header, divider, *body])


def clean_cell(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "/")


def write_report(output_dir: Path, company: str, markdown: str, generated_at: datetime) -> Path:
    report_dir = output_dir / company
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = f"report-{generated_at.strftime('%Y%m%d-%H%M%S')}.md"
    path = report_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def save_report_record(
    conn: sqlite3.Connection,
    target: dict[str, Any],
    markdown: str,
    report_path: Path,
    candidate_signals: list[dict[str, Any]],
    job_postings: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    generated_at: datetime,
) -> None:
    ensure_report_table(conn)
    cursor = conn.execute(
        """
        INSERT INTO org_intel_reports (
          company_name, aliases_json, report_type, report_markdown,
          source_counts_json, generated_at, report_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target["company"],
            json.dumps(target["aliases"], ensure_ascii=False),
            "single_company",
            markdown,
            json.dumps({"candidate_signals": len(candidate_signals), "job_postings": len(job_postings)}, ensure_ascii=False),
            generated_at.isoformat(),
            str(report_path),
        ),
    )
    save_findings(conn, findings, cursor.lastrowid)
    conn.commit()


def ensure_report_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS org_intel_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          company_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL DEFAULT '[]',
          report_type TEXT NOT NULL DEFAULT 'single_company',
          report_markdown TEXT NOT NULL,
          source_counts_json TEXT NOT NULL DEFAULT '{}',
          generated_at TEXT,
          report_path TEXT
        );

        CREATE TABLE IF NOT EXISTS org_findings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          company_name TEXT NOT NULL,
          finding_type TEXT NOT NULL,
          title TEXT NOT NULL,
          severity TEXT NOT NULL DEFAULT 'medium',
          confidence REAL,
          summary TEXT NOT NULL,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          generated_at TEXT,
          report_id INTEGER
        );
        """
    )


def save_findings(conn: sqlite3.Connection, findings: list[dict[str, Any]], report_id: int | None) -> None:
    for item in findings:
        conn.execute(
            """
            INSERT INTO org_findings (
              company_name, finding_type, title, severity, confidence, summary,
              evidence_json, generated_at, report_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("company_name"),
                item.get("finding_type"),
                item.get("title"),
                item.get("severity"),
                item.get("confidence"),
                item.get("summary"),
                json.dumps(item.get("evidence_json", {}), ensure_ascii=False),
                item.get("generated_at"),
                report_id,
            ),
        )


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于 BOSS SQLite 数据生成组织情报 Markdown。")
    parser.add_argument("--db", default="data-python/boss_talent.sqlite", help="SQLite database path")
    parser.add_argument("--company", required=True, help="目标公司，例如 腾讯")
    parser.add_argument("--alias", action="append", dest="aliases", help="公司别名，可重复传入")
    parser.add_argument("--target-config", default=None, help="组织情报目标配置 JSON")
    parser.add_argument("--since-days", type=int, default=90, help="观察窗口天数")
    parser.add_argument("--output-dir", default="org-intel", help="报告输出目录")
    return parser.parse_args()


if __name__ == "__main__":
    main()
