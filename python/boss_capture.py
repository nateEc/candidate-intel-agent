from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from boss_parse import create_candidate_fingerprint, infer_last_seen_at, parse_candidate_card_text, parse_detail_text

try:
    from playwright.sync_api import Frame, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
except ModuleNotFoundError:
    print("缺少 Python Playwright。请先运行：python3 -m pip install -r requirements.txt", file=sys.stderr)
    raise


DEFAULT_CONFIG = {
    "start_url": "https://www.zhipin.com/web/chat/search",
    "profile_dir": ".boss-profile",
    "output_dir": "data-python",
    "keyword": "",
    "city": "",
    "position": "",
    "filters": [],
    "limit": 20,
    "include_details": True,
    "detail_wait_ms": 900,
    "manual_ready": True,
}


CARD_COLLECTOR_JS = r"""
(maxItems) => {
  const salaryRe = /\b\d{1,3}(?:-\d{1,3})?K(?:·\d{1,2}薪)?\b|面议/i;
  const ageRe = /\d{2}岁/;

  function isVisible(element) {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.visibility !== "hidden" &&
      style.display !== "none" &&
      rect.width >= 380 &&
      rect.height >= 60 &&
      rect.bottom > 0 &&
      rect.top < window.innerHeight &&
      rect.right > 0 &&
      rect.left < window.innerWidth
    );
  }

  function normalize(text) {
    return String(text || "")
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");
  }

  function looksLikeCard(element) {
    const text = normalize(element.innerText || element.getAttribute("aria-label") || element.getAttribute("title"));
    if (!ageRe.test(text)) return false;
    if (!/职位|院校|期望/.test(text)) return false;
    if (/学历要求|院校要求|经验要求|年龄要求|其他筛选/.test(text)) return false;
    const childMatches = [...element.children].filter((child) => {
      const childText = normalize(child.innerText || child.getAttribute("aria-label") || child.getAttribute("title"));
      return isVisible(child) && ageRe.test(childText) && /职位|院校|期望/.test(childText);
    });
    return childMatches.length === 0 || salaryRe.test(text);
  }

  const elements = [...document.querySelectorAll('a[href="javascript:;"], a, li, article, section, div')];
  const cards = [];
  const handles = [];
  const seen = new Set();

  for (const element of elements) {
    if (!isVisible(element) || !looksLikeCard(element)) continue;
    const text = normalize(element.innerText || element.getAttribute("aria-label") || element.getAttribute("title"));
    if (!text || seen.has(text)) continue;
    seen.add(text);
    handles.push(element);
    const rect = element.getBoundingClientRect();
    cards.push({
      index: cards.length,
      text,
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) }
    });
    if (cards.length >= maxItems) break;
  }

  window.__bossIndexerCards = handles;
  return cards;
}
"""


DETAIL_TEXT_JS = r"""
() => {
  function isVisible(element) {
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      rect.width >= 500 &&
      rect.height >= 260 &&
      rect.bottom > 0 &&
      rect.top < window.innerHeight &&
      rect.right > 0 &&
      rect.left < window.innerWidth
    );
  }

  function normalize(text) {
    return String(text || "")
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");
  }

  return [...document.querySelectorAll('[role="dialog"], .dialog, .modal, .resume, div')]
    .filter(isVisible)
    .map((element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      const text = normalize(element.innerText);
      const fixedLike = style.position === "fixed" || style.position === "absolute";
      return { text, score: text.length + (fixedLike ? 5000 : 0) - Math.abs(rect.width - 920) };
    })
    .filter((item) => item.text.length >= 120)
    .sort((a, b) => b.score - a.score)[0] || null;
}
"""


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.limit is not None:
        config["limit"] = args.limit
    if args.no_details:
        config["include_details"] = False
    if args.cdp_endpoint:
        config["cdp_endpoint"] = args.cdp_endpoint

    output_dir = Path(config["output_dir"]).resolve()
    profile_dir = Path(config["profile_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")

    with sync_playwright() as p:
        page, cleanup = open_browser_page(p, config, profile_dir)

        if config.get("manual_ready", True):
            input("请在打开的 Chrome 中登录 BOSS，并停在人才库搜索页。准备好后按回车继续...")

        frame = wait_for_search_frame(page)
        apply_search_config(frame, config)
        pause_if_risk_page(page, frame)

        cards = collect_cards(frame, int(config["limit"]))
        if not cards:
            print("没有识别到候选人卡片。请确认筛选后列表可见。")
            context.close()
            return

        candidates: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        collected_at = datetime.now(timezone.utc)
        observed_at = collected_at.isoformat()

        for card in cards[: int(config["limit"])]:
            card_index = parse_candidate_card_text(card["text"])
            detail_index: dict[str, Any] = {}
            if config.get("include_details", True):
                detail_index = capture_detail(frame, page, int(card["index"]), int(config.get("detail_wait_ms", 900)))

            candidate = {
                "source_platform": "boss_zhipin",
                **card_index,
                **detail_index,
                "source_url": page.url,
                "last_seen_at": infer_last_seen_at(card_index.get("active_status"), collected_at),
            }
            candidate["source_fingerprint"] = create_candidate_fingerprint(candidate)
            candidates.append(candidate)
            observations.append(
                {
                    "source_platform": "boss_zhipin",
                    "source_fingerprint": candidate["source_fingerprint"],
                    "observed_at": observed_at,
                    "source_url": page.url,
                    "search_keyword": config.get("keyword") or None,
                    "search_city": config.get("city") or None,
                    "search_filters_json": config.get("filters", []),
                    "visible_card_json": {
                        "masked_name": candidate.get("masked_name"),
                        "age": candidate.get("age"),
                        "years_experience": candidate.get("years_experience"),
                        "education_level": candidate.get("education_level"),
                        "expected_city": candidate.get("expected_city"),
                        "expected_position": candidate.get("expected_position"),
                        "expected_salary": candidate.get("expected_salary"),
                        "job_status": candidate.get("job_status"),
                        "active_status": candidate.get("active_status"),
                        "short_summary": candidate.get("short_summary"),
                        "school": candidate.get("school"),
                        "tags_json": candidate.get("tags_json", []),
                    },
                    "parsed_confidence": candidate.get("parsed_confidence"),
                }
            )
            print(f"已读取 {len(candidates)}/{len(cards)}: {candidate.get('masked_name') or '未知'} {candidate.get('expected_position') or ''} {candidate.get('expected_salary') or ''}")

        append_jsonl(output_dir / "candidates.ndjson", candidates)
        append_jsonl(output_dir / "observations.ndjson", observations)
        run_file = write_run(output_dir, run_id, {"runId": run_id, "mode": "python_playwright", "count": len(candidates), "candidates": candidates, "observations": observations})

        print(f"完成：{len(candidates)} 条候选人索引。")
        print(f"单次运行结果：{run_file}")
        cleanup()


def open_browser_page(playwright: Any, config: dict[str, Any], profile_dir: Path) -> tuple[Page, Any]:
    cdp_endpoint = str(config.get("cdp_endpoint") or "").strip()
    start_url = str(config["start_url"])

    if cdp_endpoint:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError("CDP Chrome 没有可用 browser context，请确认 Chrome 用 --remote-debugging-port 启动。")
        context = contexts[0]
        page = next((item for item in context.pages if "zhipin.com" in item.url), None)
        if page is None:
            page = context.new_page()
            page.goto(start_url, wait_until="domcontentloaded")
        else:
            page.bring_to_front()
            if "/web/chat/search" not in page.url:
                page.goto(start_url, wait_until="domcontentloaded")

        # Do not close an attached Chrome instance; ending the Python process drops the CDP connection.
        return page, lambda: None

    context = playwright.chromium.launch_persistent_context(
        str(profile_dir),
        channel="chrome",
        headless=False,
        no_viewport=True,
        locale="zh-CN",
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(start_url, wait_until="domcontentloaded")
    return page, context.close


def wait_for_search_frame(page: Page) -> Frame:
    deadline = time.time() + 30
    while time.time() < deadline:
        for frame in page.frames:
            if "/web/frame/search" in frame.url:
                return frame
        page.wait_for_timeout(500)
    raise RuntimeError("没有找到 BOSS 搜索 iframe。请确认已登录并进入人才库搜索页。")


def apply_search_config(frame: Frame, config: dict[str, Any]) -> None:
    keyword = str(config.get("keyword") or "").strip()
    if keyword:
        fill_keyword(frame, keyword)

    for label in [config.get("city"), config.get("position"), *config.get("filters", [])]:
        label_text = str(label or "").strip()
        if not label_text:
            continue
        click_visible_text(frame, label_text)

    if keyword:
        frame.keyboard.press("Enter")
        frame.page.wait_for_timeout(1200)


def fill_keyword(frame: Frame, keyword: str) -> None:
    inputs = frame.locator("input")
    best_index = None
    best_width = 0
    for index in range(inputs.count()):
        item = inputs.nth(index)
        try:
            box = item.bounding_box(timeout=1000)
            if not box or not item.is_visible():
                continue
            if box["width"] > best_width:
                best_width = box["width"]
                best_index = index
        except PlaywrightTimeoutError:
            continue

    if best_index is None:
        print("没有找到关键词输入框，请手动确认关键词。")
        return

    inputs.nth(best_index).fill(keyword)


def click_visible_text(frame: Frame, label: str) -> bool:
    locator = frame.get_by_text(label, exact=True)
    count = locator.count()
    for index in range(count):
        item = locator.nth(index)
        try:
            if item.is_visible():
                item.click(timeout=1200)
                frame.page.wait_for_timeout(250)
                return True
        except PlaywrightTimeoutError:
            continue
    return False


def pause_if_risk_page(page: Page, frame: Frame) -> None:
    text = ""
    try:
        text = page.locator("body").inner_text(timeout=1500) + "\n" + frame.locator("body").inner_text(timeout=1500)
    except PlaywrightTimeoutError:
        return
    if any(word in text for word in ("验证码", "安全验证", "登录", "账号异常")):
        input("页面出现登录/验证/账号提示。请人工处理完成后按回车继续...")


def collect_cards(frame: Frame, limit: int) -> list[dict[str, Any]]:
    frame.wait_for_load_state("domcontentloaded")
    frame.page.wait_for_timeout(800)
    return frame.evaluate(CARD_COLLECTOR_JS, limit)


def capture_detail(frame: Frame, page: Page, index: int, wait_ms: int) -> dict[str, Any]:
    try:
        frame.evaluate(
            """(index) => {
              const el = window.__bossIndexerCards && window.__bossIndexerCards[index];
              if (!el) return false;
              el.scrollIntoView({ block: "center", inline: "nearest" });
              el.click();
              return true;
            }""",
            index,
        )
        page.wait_for_timeout(wait_ms)
        detail = extract_detail_text(page, frame)
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        return parse_detail_text(detail) if detail else {}
    except Exception as error:
        print(f"详情读取失败，跳过 index={index}: {error}")
        return {}


def extract_detail_text(page: Page, frame: Frame) -> str:
    for scope in (frame, page):
        try:
            detail = scope.evaluate(DETAIL_TEXT_JS)
            if detail and detail.get("text"):
                return detail["text"]
        except Exception:
            continue
    return ""


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_run(output_dir: Path, run_id: str, payload: dict[str, Any]) -> Path:
    run_dir = output_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"run-{run_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: str) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config_path = Path(path)
    if config_path.exists():
        config.update(json.loads(config_path.read_text(encoding="utf-8")))
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BOSS 人才库 Python Playwright 采集助手")
    parser.add_argument("--config", default="boss_filters.example.json", help="筛选配置 JSON")
    parser.add_argument("--limit", type=int, default=None, help="覆盖配置里的采集数量")
    parser.add_argument("--cdp-endpoint", default="", help="连接已启动 Chrome 的 CDP 地址，例如 http://127.0.0.1:9222")
    parser.add_argument("--no-details", action="store_true", help="只采列表，不点详情")
    return parser.parse_args()


if __name__ == "__main__":
    main()
