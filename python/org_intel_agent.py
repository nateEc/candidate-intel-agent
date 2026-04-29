from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from org_intel import contains_alias, normalize_aliases


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = "data-python/boss_talent.sqlite"
DEFAULT_OUTPUT_DIR = "org-intel"


def main() -> None:
    args = parse_args()
    aliases = normalize_cli_aliases(args)
    db_path = Path(args.db).resolve()
    refresh_jobs = should_refresh_source(args.refresh, "jobs", db_path, aliases, args.freshness_hours)
    refresh_candidates = should_refresh_source(args.refresh, "candidates", db_path, aliases, args.freshness_hours)

    if refresh_jobs:
        run_file = capture_jobs(args)
        import_run_file(run_file, db_path)
    else:
        print("职位侧：已有新鲜数据，跳过采集。")

    if refresh_candidates:
        run_file = capture_candidates(args)
        import_run_file(run_file, db_path)
    else:
        print("人才侧：已有新鲜数据或未请求，跳过采集。")

    if args.report:
        run_report(args, aliases, db_path)


def normalize_cli_aliases(args: argparse.Namespace) -> list[str]:
    values = []
    values.extend(args.alias or [])
    values.extend(args.aliases or [])
    return normalize_aliases(args.company, values)


def should_refresh_source(
    refresh: str,
    source: str,
    db_path: Path,
    aliases: list[str],
    freshness_hours: int,
) -> bool:
    if refresh == "none":
        return False
    if refresh == "all":
        return True
    if refresh == source:
        return True
    if refresh != "auto":
        return False
    if not db_path.exists():
        return True
    if source == "jobs":
        return count_recent_jobs(db_path, aliases, freshness_hours) == 0
    if source == "candidates":
        return count_recent_candidate_observations(db_path, aliases, freshness_hours) == 0
    return False


def count_recent_jobs(db_path: Path, aliases: list[str], freshness_hours: int) -> int:
    if not table_exists(db_path, "boss_job_postings"):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
    count = 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT company_name, search_keyword, description, collected_at
            FROM boss_job_postings
            ORDER BY collected_at DESC
            """
        ).fetchall()
    for row in rows:
        if not is_after_cutoff(row["collected_at"], cutoff):
            continue
        evidence = "\n".join(str(row[key] or "") for key in ("company_name", "search_keyword", "description"))
        if contains_alias(evidence, aliases):
            count += 1
    return count


def count_recent_candidate_observations(db_path: Path, aliases: list[str], freshness_hours: int) -> int:
    if not table_exists(db_path, "candidate_observations"):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
    count = 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT search_keyword, observed_at
            FROM candidate_observations
            ORDER BY observed_at DESC
            """
        ).fetchall()
    for row in rows:
        if not is_after_cutoff(row["observed_at"], cutoff):
            continue
        if contains_alias(row["search_keyword"], aliases):
            count += 1
    return count


def is_after_cutoff(value: str | None, cutoff: datetime) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= cutoff


def table_exists(db_path: Path, table: str) -> bool:
    if not db_path.exists():
        return False
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def capture_jobs(args: argparse.Namespace) -> Path:
    command = [
        sys.executable,
        "python/boss_jobs_cdp_capture.py",
        "--company",
        args.company,
        "--city",
        args.city,
        "--limit",
        str(args.jobs_limit),
        "--no-manual-ready",
    ]
    if args.jobs_no_details:
        command.append("--no-details")
    return run_capture_command(command)


def capture_candidates(args: argparse.Namespace) -> Path:
    command = [
        sys.executable,
        "python/boss_cdp_capture.py",
        "--keyword",
        args.company,
        "--position",
        args.candidate_position,
        "--limit",
        str(args.candidates_limit),
        "--detail-max-pages",
        str(args.candidate_detail_max_pages),
        "--clear-filters",
        "--no-manual-ready",
    ]
    if args.candidate_city:
        command.extend(["--city", args.candidate_city])
    if args.candidates_no_details:
        command.append("--no-details")
    return run_capture_command(command)


def run_capture_command(command: list[str]) -> Path:
    print("$ " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    run_file = extract_run_file(result.stdout)
    if not run_file:
        raise SystemExit("采集命令完成，但没有找到 run 文件路径。")
    return run_file


def extract_run_file(output: str) -> Path | None:
    match = re.search(r"单次运行结果：(.+)", output)
    if not match:
        return None
    return Path(match.group(1).strip()).resolve()


def import_run_file(run_file: Path, db_path: Path) -> None:
    command = [
        sys.executable,
        "python/import_run_sqlite.py",
        str(run_file),
        "--db",
        str(db_path),
    ]
    run_command(command)


def run_report(args: argparse.Namespace, aliases: list[str], db_path: Path) -> None:
    command = [
        sys.executable,
        "python/org_report.py",
        "--company",
        args.company,
        "--db",
        str(db_path),
        "--output-dir",
        args.output_dir,
        "--since-days",
        str(args.since_days),
    ]
    for alias in aliases:
        if alias != args.company:
            command.extend(["--alias", alias])
    run_command(command)


def run_command(command: list[str]) -> None:
    print("$ " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="组织情报本地 agent：编排 BOSS 采集、入库和报告生成。")
    parser.add_argument("--company", required=True, help="目标公司，例如 月之暗面")
    parser.add_argument("--alias", action="append", help="公司别名，可重复传入")
    parser.add_argument("--aliases", nargs="*", help="公司别名列表，例如 --aliases Moonshot Kimi")
    parser.add_argument("--refresh", choices=("auto", "none", "jobs", "candidates", "all"), default="auto")
    parser.add_argument("--report", action="store_true", help="刷新后生成组织情报报告")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="报告输出目录")
    parser.add_argument("--since-days", type=int, default=90, help="报告观察窗口天数")
    parser.add_argument("--freshness-hours", type=int, default=24, help="auto 模式下多少小时内数据算新鲜")
    parser.add_argument("--city", default="100010000", help="职位侧城市，默认全国 100010000")
    parser.add_argument("--jobs-limit", type=int, default=90, help="职位侧最多采集多少条")
    parser.add_argument("--jobs-no-details", action="store_true", help="职位侧不点击右侧详情")
    parser.add_argument("--candidate-city", default=None, help="人才库城市；为空时不改动人才库城市")
    parser.add_argument("--candidate-position", default="不限职位", help="人才库职位筛选")
    parser.add_argument("--candidates-limit", type=int, default=90, help="人才库最多采集多少条")
    parser.add_argument("--candidate-detail-max-pages", type=int, default=2, help="每份在线简历 OCR 页数")
    parser.add_argument("--candidates-no-details", action="store_true", help="人才侧不点击在线简历")
    return parser.parse_args()


if __name__ == "__main__":
    main()
