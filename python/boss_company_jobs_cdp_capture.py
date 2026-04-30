from __future__ import annotations

import argparse
import math
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from boss_cdp_capture import CdpClient, append_jsonl, request_json, write_run
from boss_jobs_parse import create_job_fingerprint, parse_job_card_text


COLLECT_COMPANY_JOB_CARDS_JS = r"""
() => {
  return [...document.querySelectorAll("li.job-card-box")].map((element, index) => {
    const anchor = element.querySelector("a.job-name[href], a[href]");
    const rect = element.getBoundingClientRect();
    return {
      index,
      href: anchor ? anchor.href : "",
      job_title: text(element.querySelector(".job-name")),
      salary_text: text(element.querySelector(".job-salary")),
      tags_json: [...element.querySelectorAll(".tag-list li, .tag-list span")]
        .map((node) => text(node))
        .filter(Boolean),
      recruiter_text: text(element.querySelector(".job-card-footer, .job-boss-info, .job-boss")),
      text: text(element),
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
    };
  }).filter((item) => item.href && item.text);

  function text(node) {
    return String(node && (node.innerText || node.textContent) || "")
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");
  }
}
"""


CLICK_COMPANY_JOB_CARD_JS = r"""
(href) => {
  const cards = [...document.querySelectorAll("li.job-card-box")];
  const item = cards.find((element) => {
    const anchor = element.querySelector("a.job-name[href], a[href]");
    return anchor && anchor.href === href;
  });
  if (!item) return { ok: false, count: cards.length };
  item.scrollIntoView({ block: "center", inline: "nearest" });
  const rect = item.getBoundingClientRect();
  item.click();
  return {
    ok: true,
    count: cards.length,
    point: { x: rect.x + Math.min(120, Math.max(60, rect.width * 0.25)), y: rect.y + Math.min(55, Math.max(35, rect.height * 0.35)) },
    text: String(item.innerText || "").replace(/\s+/g, " ").trim().slice(0, 300)
  };
}
"""


READ_COMPANY_JOB_DETAIL_JS = r"""
() => {
  const candidates = [
    document.querySelector(".job-detail-box"),
    document.querySelector(".position-job-content"),
    document.querySelector(".job-sec-text"),
    ...document.querySelectorAll("div")
  ].filter(Boolean);
  let best = null;
  for (const element of candidates) {
    const rect = element.getBoundingClientRect();
    const text = normalize(element.innerText || element.textContent || "");
    if (!text || rect.width < 300 || rect.height < 120) continue;
    if (!best || text.length > best.text.length) {
      best = { element, rect, text };
    }
  }
  if (!best) return { ok: false, detail_text: "" };
  return {
    ok: true,
    detail_text: best.text,
    detail_rect: {
      x: best.rect.x,
      y: best.rect.y,
      width: best.rect.width,
      height: best.rect.height
    }
  };

  function normalize(text) {
    return String(text || "")
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");
  }
}
"""


SCROLL_COMPANY_JOB_LIST_JS = r"""
() => {
  const cards = [...document.querySelectorAll("li.job-card-box")];
  const before = window.scrollY;
  const last = cards[cards.length - 1];
  if (last) {
    last.scrollIntoView({ block: "start", inline: "nearest" });
    window.scrollBy(0, Math.max(900, window.innerHeight * 0.75));
  } else {
    window.scrollBy(0, Math.max(900, window.innerHeight * 0.75));
  }
  window.dispatchEvent(new Event("scroll"));
  return { before, after: window.scrollY, card_count: cards.length };
}
"""


COLLECT_COMPANY_FILTER_LINKS_JS = r"""
(companyToken) => {
  return [...document.querySelectorAll("a[href*='/gongsi/job/']")]
    .map((anchor) => ({ text: String(anchor.innerText || anchor.textContent || "").replace(/\s+/g, " ").trim(), href: anchor.href }))
    .filter((item) => item.href.includes(companyToken))
    .filter((item) => !item.href.includes("/job_detail/"));
}
"""


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")

    target = request_json(f"{args.cdp_url.rstrip('/')}/json/new?{args.url}", method="PUT")
    print(f"连接 Chrome target: {target.get('url')}")
    client = CdpClient(target["webSocketDebuggerUrl"])
    postings: list[dict[str, Any]] = []
    seen_hrefs: set[str] = set()
    seen_fingerprints: set[str] = set()
    collected_at = datetime.now(timezone.utc).isoformat()

    try:
        navigate(client, args.url)
        assert_boss_page_ready(client)
        target_total = args.limit or detect_target_total(client) or 0
        print(f"目标职位数：{target_total or '未知'}")

        company_token = extract_company_token(args.url)
        filter_queue = [args.url]
        queued_filters = {normalize_company_filter_url(args.url)}
        visited_filters: set[str] = set()

        while filter_queue and len(visited_filters) < args.max_filter_pages:
            current_url = filter_queue.pop(0)
            normalized_current_url = normalize_company_filter_url(current_url)
            if normalized_current_url in visited_filters:
                continue
            visited_filters.add(normalized_current_url)

            navigate(client, current_url)
            assert_boss_page_ready(client)
            print(f"打开筛选页 {len(visited_filters)}: {current_url}")

            page_meta = read_company_page_meta(client)
            page_count = page_meta.get("page_count") or 1
            for page_number in range(2, page_count + 1):
                href = normalize_company_filter_url(company_page_url(current_url, page_number))
                if not href or href in queued_filters or href in visited_filters:
                    continue
                queued_filters.add(href)
                filter_queue.append(href)

            filter_links = client.evaluate(COLLECT_COMPANY_FILTER_LINKS_JS, company_token) or []
            for link in filter_links:
                href = normalize_company_filter_url(link.get("href") or "")
                if not href or href in queued_filters or href in visited_filters:
                    continue
                queued_filters.add(href)
                filter_queue.append(href)

            cards = client.evaluate(COLLECT_COMPANY_JOB_CARDS_JS) or []
            print(f"当前页职位卡片：{len(cards)} / 已采：{len(seen_hrefs)} / 待访问筛选页：{len(filter_queue)}")

            for card in cards:
                href = card.get("href")
                if not href or href in seen_hrefs:
                    continue
                clicked = client.evaluate(CLICK_COMPANY_JOB_CARD_JS, href) or {}
                if not clicked.get("ok"):
                    continue
                time.sleep(args.detail_wait_ms / 1000)
                assert_boss_page_ready(client)
                detail = client.evaluate(READ_COMPANY_JOB_DETAIL_JS) or {}
                detail_text = detail.get("detail_text") or ""

                seed = {
                    **card,
                    "company_name": args.company,
                    "description": detail_text,
                    "raw_detail_json": {
                        "detail_rect": detail.get("detail_rect"),
                        "detail_text_head": detail_text[:500],
                    },
                }
                posting = {
                    "source_platform": "boss_zhipin",
                    **parse_job_card_text(card.get("text", ""), seed),
                    "source_url": href,
                    "search_keyword": args.company,
                    "search_city": None,
                    "collected_at": collected_at,
                }
                posting["source_fingerprint"] = create_job_fingerprint(posting)
                seen_hrefs.add(href)
                if posting["source_fingerprint"] not in seen_fingerprints:
                    seen_fingerprints.add(posting["source_fingerprint"])
                    postings.append(posting)
                    print(
                        f"已读取职位 {len(postings)}"
                        f"{('/' + str(target_total)) if target_total else ''}: "
                        f"{posting.get('job_title') or '未知'} {posting.get('salary_text') or ''}"
                    )
                wait_between_jobs(args)
                if target_total and len(seen_hrefs) >= target_total:
                    break

            if target_total and len(seen_hrefs) >= target_total:
                break
            time.sleep(args.load_more_wait_ms / 1000)

        append_jsonl(output_dir / "boss_job_postings.ndjson", postings)
        run_file = write_run(
            output_dir,
            run_id,
            {
                "runId": run_id,
                "mode": "boss_company_jobs_cdp",
                "company": args.company,
                "keyword": args.company,
                "source_url": args.url,
                "target_count": target_total or None,
                "count": len(postings),
                "job_postings": postings,
            },
        )
        print(f"完成：{len(postings)} 条职位索引。")
        print(f"单次运行结果：{run_file}")
    finally:
        client.close()


def navigate(client: CdpClient, url: str) -> None:
    client.call("Page.enable")
    client.call("Page.navigate", {"url": url})
    time.sleep(2.0)


def detect_target_total(client: CdpClient) -> int | None:
    state = client.evaluate(
        r"""
() => {
  const text = String(document.body ? document.body.innerText : "").replace(/\s+/g, " ");
  const match = text.match(/(?:招聘职位\(|在招职位)\s*(\d+)|(\d+)\s*在招职位/);
  return match ? Number(match[1] || match[2]) : null;
}
"""
    )
    return int(state) if state else None


def read_company_page_meta(client: CdpClient) -> dict[str, int | None]:
    state = client.evaluate(
        r"""
() => {
  const data = window.__BOSSCOMPANY__ && window.__BOSSCOMPANY__.data && window.__BOSSCOMPANY__.data[0] || {};
  const cardCount = document.querySelectorAll("li.job-card-box").length;
  const pageNumbers = [...document.querySelectorAll("a[ka^='page-']")]
    .map((anchor) => Number(String(anchor.textContent || "").trim()))
    .filter((value) => Number.isFinite(value));
  return {
    total_count: Number(data.totalCount || 0) || null,
    card_count: cardCount || null,
    max_page_number: pageNumbers.length ? Math.max(...pageNumbers) : null
  };
}
"""
    ) or {}
    total_count = int(state["total_count"]) if state.get("total_count") else None
    card_count = int(state["card_count"]) if state.get("card_count") else None
    max_page_number = int(state["max_page_number"]) if state.get("max_page_number") else None
    inferred_page_count = math.ceil(total_count / 15) if total_count else None
    page_count = max([value for value in [inferred_page_count, max_page_number] if value] or [1])
    return {
        "total_count": total_count,
        "card_count": card_count,
        "page_count": page_count,
    }


def extract_company_token(url: str) -> str:
    match = re.search(r"/gongsi/job/(?:[^/?#]+/)*([^/?#]+)", url)
    if not match:
        raise SystemExit(f"无法从 URL 中识别公司 token：{url}")
    return match.group(1)


def normalize_company_filter_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    page = query.get("page")
    kept_query = urlencode({"page": page}) if page and page != "1" else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, kept_query, ""))


def company_page_url(url: str, page_number: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if page_number <= 1:
        query.pop("page", None)
    else:
        query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))




def assert_boss_page_ready(client: CdpClient) -> None:
    state = client.evaluate(
        r"""
() => ({
  url: location.href,
  text: String(document.body ? document.body.innerText : "").replace(/\s+/g, " ").trim().slice(0, 500)
})
"""
    ) or {}
    url = state.get("url") or ""
    text = state.get("text") or ""
    if "passport" in url or "verify" in url or "验证码" in text or "安全验证" in text:
        raise SystemExit(f"BOSS 进入登录/验证页，请在 Chrome 中人工处理后重试：{url}")


def wait_between_jobs(args: argparse.Namespace) -> None:
    base_ms = max(0, args.job_wait_ms)
    jitter_ms = max(0, args.job_jitter_ms)
    delay_ms = base_ms + (random.randint(0, jitter_ms) if jitter_ms else 0)
    if delay_ms:
        time.sleep(delay_ms / 1000)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BOSS 公司招聘页 CDP 采集助手")
    parser.add_argument("--url", required=True, help="BOSS /gongsi/job/...html 公司招聘页 URL")
    parser.add_argument("--company", required=True, help="公司名，例如 MO&CO招聘")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9223")
    parser.add_argument("--output-dir", default="data-python")
    parser.add_argument("--limit", type=int, default=None, help="覆盖页面检测到的职位总数")
    parser.add_argument("--max-filter-pages", type=int, default=80)
    parser.add_argument("--detail-wait-ms", type=int, default=4500)
    parser.add_argument("--job-wait-ms", type=int, default=3500)
    parser.add_argument("--job-jitter-ms", type=int, default=3000)
    parser.add_argument("--load-more-wait-ms", type=int, default=2500)
    return parser.parse_args()


if __name__ == "__main__":
    main()
