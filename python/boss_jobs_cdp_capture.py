from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from boss_cdp_capture import CdpClient, append_jsonl, request_json, write_run
from boss_jobs_parse import create_job_fingerprint, parse_job_card_text


DEFAULT_CONFIG = {
    "start_url": "https://www.zhipin.com/web/geek/jobs",
    "cdp_url": "http://127.0.0.1:9222",
    "output_dir": "data-python",
    "company": "",
    "keyword": "",
    "city": "100010000",
    "city_group": "",
    "limit": 30,
    "load_all": False,
    "load_more_wait_ms": 1200,
    "load_more_scroll_delta": 900,
    "max_scroll_rounds": 60,
    "no_growth_rounds": 2,
    "hard_max_jobs": 500,
    "include_details": True,
    "detail_wait_ms": 700,
    "manual_ready": True,
}


CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "南京": "101190100",
    "苏州": "101190400",
    "西安": "101110100",
}


CITY_GROUPS = {
    "hot": ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州", "西安"],
    "热门": ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州", "西安"],
}


COLLECT_JOB_CARDS_JS = r"""
(maxItems) => {
  const cards = findJobCards();
  return cards.slice(0, maxItems).map((item, index) => {
    const element = item.element;
    return {
      index,
      card_key: item.cardKey,
      href: pickHref(element),
      job_title: pickText(element, [".job-name", ".job-title", ".job-card-title", ".name"]),
      salary_text: pickText(element, [".salary", ".job-salary", ".red"]),
      job_city: pickText(element, [".job-area", ".area", ".job-location"]),
      company_name: pickText(element, [".company-name", ".company-text .name", ".company-info .name"]),
      recruiter_name: pickText(element, [".boss-name", ".recruiter-name"]),
      recruiter_title: pickText(element, [".boss-title", ".recruiter-title"]),
      tags_json: pickTags(element),
      text: item.text
    };
  });

  function findJobCards() {
    const salaryRe = /[\d\uE031-\uE03A]{1,5}(?:-[\d\uE031-\uE03A]{1,5})?(?:K(?:·[\d\uE031-\uE03A]{1,2}薪)?|元\/天)|面议/;
    const roots = [
      ...document.querySelectorAll(".job-card-wrapper, .job-card, .job-card-body, .job-primary, .job-list-box li, .job-list-container li")
    ];
    const cards = [];
    const seen = new Set();

    for (const element of roots) {
      if (!visible(element) || !isLeftListCard(element)) continue;
      const text = normalize(element.innerText || element.getAttribute("aria-label") || "");
      if (!text || !salaryRe.test(text)) continue;
      if (!/本科|大专|硕士|博士|学历不限|经验不限|在校\/应届|\d+(?:-\d+)?年|元\/天/.test(text)) continue;
      const cardKey = pickHref(element) || text.slice(0, 180);
      if (seen.has(cardKey)) continue;
      seen.add(cardKey);
      cards.push({ element, cardKey, text });
    }
    return cards;
  }

  function isLeftListCard(element) {
    const rect = element.getBoundingClientRect();
    return rect.x < window.innerWidth * 0.48 && rect.width >= 260 && rect.width <= 620;
  }

  function pickText(root, selectors) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const text = normalize(node && node.textContent);
      if (text) return text;
    }
    return "";
  }

  function pickTags(root) {
    const nodes = [...root.querySelectorAll(".tag-list span, .job-tags span, .info-desc span, .job-card-footer span")];
    const tags = [];
    for (const node of nodes) {
      const text = normalize(node.textContent);
      if (text && text.length <= 24 && !tags.includes(text)) tags.push(text);
      if (tags.length >= 16) break;
    }
    return tags;
  }

  function pickHref(root) {
    const anchor = root.matches("a") ? root : root.querySelector("a[href]");
    return anchor ? anchor.href : "";
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 80 && rect.height > 40;
  }

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


GET_JOB_CARD_CLICK_POINT_JS = r"""
(request) => {
  const target = request || {};
  const cards = findJobCards();
  const item = findTarget(cards, target);
  if (!item) return { ok: false, count: cards.length };
  const card = item.element;
  card.scrollIntoView({ block: "center", inline: "nearest" });
  const rect = card.getBoundingClientRect();
  return {
    ok: true,
    count: cards.length,
    x: rect.x + Math.min(120, Math.max(60, rect.width * 0.25)),
    y: rect.y + Math.min(55, Math.max(35, rect.height * 0.35)),
    text: item.text.slice(0, 500)
  };

  function findTarget(items, target) {
    if (target.card_key) {
      const byKey = items.find((item) => item.cardKey === target.card_key);
      if (byKey) return byKey;
    }
    if (target.text) {
      const normalized = normalize(target.text);
      const byExactText = items.find((item) => item.text === normalized);
      if (byExactText) return byExactText;
      const prefix = normalized.slice(0, 120);
      const byPrefix = items.find((item) => prefix && item.text.startsWith(prefix));
      if (byPrefix) return byPrefix;
    }
    if (Number.isInteger(target.index)) {
      return items[target.index] || null;
    }
    return null;
  }

  function findJobCards() {
    const salaryRe = /[\d\uE031-\uE03A]{1,5}(?:-[\d\uE031-\uE03A]{1,5})?(?:K(?:·[\d\uE031-\uE03A]{1,2}薪)?|元\/天)|面议/;
    const roots = [
      ...document.querySelectorAll(".job-card-wrapper, .job-card, .job-card-body, .job-primary, .job-list-box li, .job-list-container li")
    ];
    const cards = [];
    const seen = new Set();

    for (const element of roots) {
      if (!visible(element) || !isLeftListCard(element)) continue;
      const text = normalize(element.innerText || element.getAttribute("aria-label") || "");
      if (!text || !salaryRe.test(text)) continue;
      if (!/本科|大专|硕士|博士|学历不限|经验不限|在校\/应届|\d+(?:-\d+)?年|元\/天/.test(text)) continue;
      const cardKey = pickHref(element) || text.slice(0, 180);
      if (seen.has(cardKey)) continue;
      seen.add(cardKey);
      cards.push({ element, cardKey, text });
    }
    return cards;
  }

  function isLeftListCard(element) {
    const rect = element.getBoundingClientRect();
    return rect.x < window.innerWidth * 0.48 && rect.width >= 260 && rect.width <= 620;
  }

  function pickHref(root) {
    const anchor = root.matches("a") ? root : root.querySelector("a[href]");
    return anchor ? anchor.href : "";
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 80 && rect.height > 40;
  }

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


READ_JOB_DETAIL_JS = r"""
() => {
  const candidates = [
    ...document.querySelectorAll(".job-detail, .job-detail-container, .job-detail-box, .job-detail-content, .detail-content, .job-sec, .job-detail-card, .job-card-detail, .job-detail-wrap, main, section, article, div")
  ];
  const scored = [];
  for (const element of candidates) {
    if (!visible(element) || !isRightPanel(element)) continue;
    const text = normalize(element.innerText || element.textContent || "");
    if (!text || text.length < 80) continue;
    const score = markerScore(text) + Math.min(3000, text.length) / 1000;
    if (score <= 1) continue;
    const rect = element.getBoundingClientRect();
    scored.push({
      score,
      text,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
    });
  }
  scored.sort((a, b) => b.score - a.score);
  const best = scored[0] || null;
  return {
    ok: Boolean(best),
    detail_text: best ? best.text : "",
    detail_rect: best ? best.rect : null
  };

  function markerScore(text) {
    let score = 0;
    for (const marker of ["职位描述", "任职要求", "工作职责", "岗位职责", "薪资面议", "立即沟通", "关于这个岗位"]) {
      if (text.includes(marker)) score += 2;
    }
    if (/[\d\uE031-\uE03A]{1,5}(?:-[\d\uE031-\uE03A]{1,5})?(?:K(?:·[\d\uE031-\uE03A]{1,2}薪)?|元\/天)|面议/.test(text)) score += 2;
    return score;
  }

  function isRightPanel(element) {
    const rect = element.getBoundingClientRect();
    if (location.href.includes("/job_detail/")) {
      return rect.width > 420 && rect.height > 180;
    }
    return rect.x > window.innerWidth * 0.34 && rect.width > 360 && rect.height > 180;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

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


SCROLL_JOB_RESULTS_JS = r"""
() => {
  const card = findFirstJobCard();
  const targets = unique([
    ...(card ? scrollableAncestors(card) : []),
    document.querySelector(".job-list"),
    document.querySelector(".job-list-box"),
    document.querySelector(".job-list-wrapper"),
    document.querySelector(".search-job-result"),
    document.querySelector(".job-list-container"),
    document.scrollingElement,
    document.documentElement,
    document.body
  ]).filter((target) => target && target.scrollHeight > target.clientHeight + 20);

  const before = targets.map((target) => target.scrollTop);
  for (const target of targets) {
    target.scrollTop = target.scrollHeight;
    target.dispatchEvent(new Event("scroll", { bubbles: true }));
  }
  window.scrollTo(0, Math.max(document.documentElement.scrollHeight || 0, document.body.scrollHeight || 0));
  window.dispatchEvent(new Event("scroll"));
  const after = targets.map((target) => target.scrollTop);

  return {
    ok: true,
    moved: after.some((value, index) => value !== before[index]),
    point: { x: window.innerWidth * 0.5, y: Math.max(100, window.innerHeight - 120) }
  };

  function unique(values) {
    return values.filter((value, index) => value && values.indexOf(value) === index);
  }

  function scrollableAncestors(element) {
    const ancestors = [];
    let node = element.parentElement;
    while (node && node !== document.body) {
      if (node.scrollHeight > node.clientHeight + 20) ancestors.push(node);
      node = node.parentElement;
    }
    return ancestors;
  }

  function findFirstJobCard() {
    const salaryRe = /[\d\uE031-\uE03A]{1,5}(?:-[\d\uE031-\uE03A]{1,5})?(?:K(?:·[\d\uE031-\uE03A]{1,2}薪)?|元\/天)|面议/;
    return [...document.querySelectorAll(".job-card-wrapper, .job-card, .job-card-body, .job-primary, .job-list-box li, .job-list-container li")].find((element) => {
      const rect = element.getBoundingClientRect();
      const text = element.innerText || "";
      return rect.x < window.innerWidth * 0.48 && rect.width >= 260 && salaryRe.test(text);
    }) || null;
  }
}
"""


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    apply_args(config, args)

    keyword = config.get("keyword") or config.get("company") or ""
    if not keyword:
        raise SystemExit("请传入 --company 或 --keyword。")
    config["keyword"] = keyword

    output_dir = Path(config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cities = expand_cities(config.get("city"), config.get("city_group"))

    target = get_or_create_job_target(config["cdp_url"], config["start_url"])
    print(f"连接 Chrome target: {target.get('url')}")
    client = CdpClient(target["webSocketDebuggerUrl"])
    run_id = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")

    try:
        if config.get("manual_ready", True):
            input("请确认远程调试 Chrome 已登录且可访问 BOSS。准备好后按回车继续...")

        collected_at = datetime.now(timezone.utc).isoformat()
        postings: list[dict[str, Any]] = []
        seen_fingerprints: set[str] = set()
        for city in cities:
            url = build_job_search_url(config["start_url"], keyword, city)
            print(f"打开职位搜索：{city or '全国'} / {keyword}")
            navigate(client, url)
            assert_boss_page_ready(client)
            cards = load_job_cards(client, config)
            print(f"已识别职位卡片：{len(cards)}")
            for list_position, card in enumerate(cards):
                detail = {}
                if config.get("include_details", True):
                    detail = capture_job_detail(client, card, list_position, config)
                seed = {**card, **detail}
                posting = {
                    "source_platform": "boss_zhipin",
                    **parse_job_card_text(card.get("text", ""), seed),
                    "source_url": card.get("href") or url,
                    "search_keyword": keyword,
                    "search_city": city or None,
                    "collected_at": collected_at,
                }
                posting["source_fingerprint"] = create_job_fingerprint(posting)
                if posting["source_fingerprint"] in seen_fingerprints:
                    continue
                seen_fingerprints.add(posting["source_fingerprint"])
                postings.append(posting)
                print(f"已读取职位 {len(postings)}: {posting.get('job_title') or '未知'} {posting.get('salary_text') or ''}")

        append_jsonl(output_dir / "boss_job_postings.ndjson", postings)
        run_file = write_run(
            output_dir,
            run_id,
            {
                "runId": run_id,
                "mode": "boss_jobs_cdp",
                "company": config.get("company") or None,
                "keyword": keyword,
                "cities": cities,
                "count": len(postings),
                "job_postings": postings,
            },
        )
        print(f"完成：{len(postings)} 条职位索引。")
        print(f"单次运行结果：{run_file}")
    finally:
        client.close()


def apply_args(config: dict[str, Any], args: argparse.Namespace) -> None:
    if args.company is not None:
        config["company"] = args.company
    if args.keyword is not None:
        config["keyword"] = args.keyword
    if args.city is not None:
        config["city"] = args.city
    if args.city_group is not None:
        config["city_group"] = args.city_group
    if args.limit is not None:
        config["limit"] = args.limit
    if args.load_all:
        config["load_all"] = True
    if args.max_scroll_rounds is not None:
        config["max_scroll_rounds"] = args.max_scroll_rounds
    if args.cdp_url:
        config["cdp_url"] = args.cdp_url
    if args.no_details:
        config["include_details"] = False
    if args.detail_wait_ms is not None:
        config["detail_wait_ms"] = args.detail_wait_ms
    if args.no_manual_ready:
        config["manual_ready"] = False


def expand_cities(city: str | None, city_group: str | None) -> list[str]:
    if city_group:
        return CITY_GROUPS.get(city_group, [city_group])
    if city in CITY_GROUPS:
        return CITY_GROUPS[city]
    return [city or ""]


def build_job_search_url(start_url: str, keyword: str, city: str | None) -> str:
    query = urllib.parse.urlencode({"query": keyword})
    city_code = city if city and city.isdigit() else CITY_CODES.get(city or "")
    if city_code:
        query = f"{query}&city={city_code}"
    return f"{start_url.rstrip('?') if '?' not in start_url else start_url.split('?')[0]}?{query}"


def navigate(client: CdpClient, url: str) -> None:
    client.call("Page.enable")
    client.call("Page.navigate", {"url": url})
    time.sleep(2.0)


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


def load_job_cards(client: CdpClient, config: dict[str, Any]) -> list[dict[str, Any]]:
    load_all = bool(config.get("load_all"))
    configured_limit = int(config.get("limit") or 0)
    hard_max = int(config.get("hard_max_jobs", 500))
    target_count = None if load_all or configured_limit <= 0 else configured_limit
    collect_limit = target_count or hard_max
    max_rounds = int(config.get("max_scroll_rounds", 60))
    no_growth_rounds = int(config.get("no_growth_rounds", 2))
    wait_seconds = int(config.get("load_more_wait_ms", 1200)) / 1000
    scroll_delta = int(config.get("load_more_scroll_delta", 900))

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous_count = -1
    stable_rounds = 0

    for round_number in range(max_rounds + 1):
        current_cards = client.evaluate(COLLECT_JOB_CARDS_JS, collect_limit) or []
        for card in current_cards:
            key = card.get("card_key") or card.get("text")
            if not key or key in seen:
                continue
            seen.add(key)
            cards.append(card)

        if len(cards) != previous_count:
            previous_count = len(cards)
            stable_rounds = 0
        else:
            stable_rounds += 1

        if target_count and len(cards) >= target_count:
            return cards[:target_count]
        if len(cards) >= hard_max:
            print(f"达到 hard_max_jobs={hard_max}，停止继续加载。")
            return cards[:hard_max]
        if round_number > 0 and stable_rounds >= no_growth_rounds:
            return cards

        state = client.evaluate(SCROLL_JOB_RESULTS_JS)
        if state and state.get("point"):
            point = state["point"]
            client.wheel(float(point["x"]), float(point["y"]), scroll_delta)
        time.sleep(wait_seconds)

    return cards[:target_count] if target_count else cards


def capture_job_detail(
    client: CdpClient,
    card: dict[str, Any],
    list_position: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    point = client.evaluate(
        GET_JOB_CARD_CLICK_POINT_JS,
        {"index": int(card["index"]), "card_key": card.get("card_key"), "text": card.get("text")},
    )
    if not point or not point.get("ok"):
        return capture_job_detail_from_href(client, card, config, f"card-click-point-missing:{list_position}")

    client.click(float(point["x"]), float(point["y"]))
    time.sleep(int(config.get("detail_wait_ms", 700)) / 1000)
    detail = read_job_detail(client)
    detail_text = detail.get("detail_text") or ""
    if not detail_text:
        return capture_job_detail_from_href(client, card, config, "detail-panel-missing")
    return {
        "description": detail_text,
        "raw_detail_json": {
            "detail_rect": detail.get("detail_rect"),
            "detail_text_head": detail_text[:500],
        },
    }


def capture_job_detail_from_href(
    client: CdpClient,
    card: dict[str, Any],
    config: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    href = card.get("href")
    if not href:
        return {"detail_error": reason}
    navigate(client, href)
    time.sleep(max(1.0, int(config.get("detail_wait_ms", 700)) / 1000))
    detail = read_job_detail(client)
    detail_text = detail.get("detail_text") or ""
    if not detail_text:
        return {"detail_error": f"{reason};href-detail-missing"}
    return {
        "description": detail_text,
        "raw_detail_json": {
            "detail_rect": detail.get("detail_rect"),
            "detail_text_head": detail_text[:500],
            "detail_fallback": reason,
        },
    }


def read_job_detail(client: CdpClient) -> dict[str, Any]:
    return client.evaluate(READ_JOB_DETAIL_JS) or {}


def get_or_create_job_target(cdp_url: str, start_url: str) -> dict[str, Any]:
    targets = request_json(f"{cdp_url.rstrip('/')}/json/list")
    for target in targets:
        if target.get("type") == "page" and "zhipin.com/web/geek/job" in target.get("url", ""):
            return target
    encoded = urllib.parse.quote(start_url, safe=":/?=&")
    return request_json(f"{cdp_url.rstrip('/')}/json/new?{encoded}", method="PUT")


def load_config(path: str) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config_path = Path(path)
    if config_path.exists():
        config.update(json.loads(config_path.read_text(encoding="utf-8")))
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BOSS 职位侧 raw CDP 采集助手")
    parser.add_argument("--config", default="boss_jobs_filters.json", help="职位采集配置 JSON")
    parser.add_argument("--company", default=None, help="目标公司，例如 腾讯")
    parser.add_argument("--keyword", default=None, help="职位搜索关键词；为空时使用 company")
    parser.add_argument("--city", default=None, help="城市，例如 北京；传 热门 会展开为城市组")
    parser.add_argument("--city-group", default=None, help="城市组，例如 hot")
    parser.add_argument("--limit", type=int, default=None, help="每个城市最多读取多少条职位")
    parser.add_argument("--load-all", action="store_true", help="每个城市持续加载到没有新增职位")
    parser.add_argument("--max-scroll-rounds", type=int, default=None, help="加载更多阶段最多滚动轮数")
    parser.add_argument("--cdp-url", default=None, help="Chrome DevTools URL，例如 http://127.0.0.1:9222")
    parser.add_argument("--no-details", action="store_true", help="只采左侧职位卡片，不点击读取右侧详情")
    parser.add_argument("--detail-wait-ms", type=int, default=None, help="点击职位卡后等待右侧详情渲染的毫秒数")
    parser.add_argument("--no-manual-ready", action="store_true", help="不等待人工回车确认")
    return parser.parse_args()


if __name__ == "__main__":
    main()
