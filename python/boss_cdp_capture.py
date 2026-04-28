from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websocket import create_connection

from boss_parse import create_candidate_fingerprint, infer_last_seen_at, parse_candidate_card_text, parse_resume_text


DEFAULT_CONFIG = {
    "start_url": "https://www.zhipin.com/web/chat/search",
    "cdp_url": "http://127.0.0.1:9222",
    "output_dir": "data-python",
    "keyword": "",
    "city": "",
    "position": "",
    "filters": [],
    "limit": 20,
    "include_details": True,
    "detail_wait_ms": 900,
    "detail_max_pages": 3,
    "detail_scroll_delta": 650,
    "detail_scroll_wait_ms": 700,
    "ocr_languages": ["zh-Hans", "en-US"],
    "load_all": False,
    "load_more_wait_ms": 1400,
    "load_more_scroll_delta": 900,
    "max_scroll_rounds": 80,
    "no_growth_rounds": 2,
    "hard_max_candidates": 1000,
    "manual_ready": True,
}


APPLY_CONFIG_JS = r"""
async (config) => {
  const scope = getSearchScope();
  const doc = scope.document;

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function nativeSetValue(input, value) {
    const setter = Object.getOwnPropertyDescriptor(scope.window.HTMLInputElement.prototype, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function clickText(label) {
    if (!label) return false;
    const elements = [...doc.querySelectorAll("button, a, span, div, li")];
    const exact = elements.find((el) => visible(el) && el.textContent.trim() === label);
    if (exact) {
      exact.click();
      return true;
    }
    const contains = elements.find((el) => visible(el) && el.textContent.trim().includes(label) && el.textContent.trim().length <= label.length + 8);
    if (contains) {
      contains.click();
      return true;
    }
    return false;
  }

  if (config.keyword) {
    const inputs = [...doc.querySelectorAll("input")].filter(visible);
    const input = inputs.sort((a, b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width)[0];
    if (input) {
      nativeSetValue(input, config.keyword);
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
      input.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true }));
    }
  }

  for (const label of [config.city, config.position, ...(config.filters || [])]) {
    if (label) clickText(label);
    await new Promise((resolve) => setTimeout(resolve, 220));
  }

  if (config.keyword) {
    const clickable = [...doc.querySelectorAll("button, a, div, span")].find((el) => {
      const rect = el.getBoundingClientRect();
      return visible(el) && rect.width >= 40 && rect.height >= 30 && (el.textContent.trim() === "搜索" || /search|sou/i.test(el.className));
    });
    if (clickable) clickable.click();
  }

  return { ok: true, url: scope.window.location.href };

  function getSearchScope() {
    const frames = [...document.querySelectorAll("iframe")];
    const frame = frames.find((item) => item.src.includes("/web/frame/search")) || frames[0];
    if (frame && frame.contentWindow && frame.contentDocument) {
      return { window: frame.contentWindow, document: frame.contentDocument };
    }
    return { window, document };
  }
}
"""


COLLECT_CARDS_JS = r"""
(maxItems) => {
  const scope = getSearchScope();
  const doc = scope.document;
  const ageRe = /\d{2}岁/;

  function normalize(text) {
    return String(text || "")
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");
  }

  const elements = [...doc.querySelectorAll('a[href="javascript:;"]')];
  const cards = [];
  const seen = new Set();

  for (const element of elements) {
    const text = normalize(element.innerText || element.getAttribute("aria-label") || element.getAttribute("title"));
    if (!ageRe.test(text) || !/职位|院校|期望/.test(text)) continue;
    if (/学历要求|院校要求|经验要求|年龄要求|其他筛选/.test(text)) continue;
    if (!text || seen.has(text)) continue;
    seen.add(text);
    cards.push({
      index: cards.length,
      card_key: cardKey(element, text),
      text
    });
    if (cards.length >= maxItems) break;
  }

  return cards;

  function getSearchScope() {
    const frames = [...document.querySelectorAll("iframe")];
    const frame = frames.find((item) => item.src.includes("/web/frame/search")) || frames[0];
    if (frame && frame.contentWindow && frame.contentDocument) {
      return { window: frame.contentWindow, document: frame.contentDocument };
    }
    return { window, document };
  }

  function cardKey(element, text) {
    return [
      element.getAttribute("data-jid"),
      element.getAttribute("data-expect"),
      element.getAttribute("data-lid"),
      element.getAttribute("data-itemid")
    ].filter(Boolean).join("|") || text.slice(0, 160);
  }
}
"""


GET_CARD_CLICK_POINT_JS = r"""
(request) => {
  const target = typeof request === "number" ? { index: request } : (request || {});
  const scope = getSearchScope();
  const doc = scope.document;
  const cards = findCandidateCards(doc);
  const item = findTarget(cards, target);
  if (!item) return { ok: false, count: cards.length };
  const card = item.element;
  card.scrollIntoView({ block: "center", inline: "nearest" });
  const rect = card.getBoundingClientRect();
  const frameRect = scope.frame ? scope.frame.getBoundingClientRect() : { x: 0, y: 0 };
  return {
    ok: true,
    count: cards.length,
    x: frameRect.x + rect.x + Math.min(90, Math.max(40, rect.width * 0.18)),
    y: frameRect.y + rect.y + Math.min(50, Math.max(32, rect.height * 0.28)),
    text: normalize(card.innerText).slice(0, 500)
  };

  function findCandidateCards(currentDoc) {
    const ageRe = /\d{2}岁/;
    return [...currentDoc.querySelectorAll('a[href="javascript:;"]')].map((element, index) => ({
      element,
      index,
      text: normalize(element.innerText || element.getAttribute("aria-label") || element.getAttribute("title")),
      cardKey: cardKey(element)
    })).filter((item) => {
      const text = item.text;
      if (!ageRe.test(text) || !/职位|院校|期望/.test(text)) return false;
      return !/学历要求|院校要求|经验要求|年龄要求|其他筛选/.test(text);
    });
  }

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

  function normalize(text) {
    return String(text || "")
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");
  }

  function getSearchScope() {
    const frames = [...document.querySelectorAll("iframe")];
    const frame = frames.find((item) => item.src.includes("/web/frame/search")) || frames[0];
    if (frame && frame.contentWindow && frame.contentDocument) {
      return { window: frame.contentWindow, document: frame.contentDocument, frame };
    }
    return { window, document, frame: null };
  }

  function cardKey(element) {
    return [
      element.getAttribute("data-jid"),
      element.getAttribute("data-expect"),
      element.getAttribute("data-lid"),
      element.getAttribute("data-itemid")
    ].filter(Boolean).join("|");
  }
}
"""


GET_RESUME_FRAME_STATE_JS = r"""
() => {
  const frame = [...document.querySelectorAll("iframe")].find((item) => item.src.includes("/web/frame/c-resume"));
  if (!frame) return { ok: false };
  const rect = frame.getBoundingClientRect();
  let canvasStyle = "";
  try {
    const canvas = frame.contentDocument && frame.contentDocument.querySelector("canvas");
    canvasStyle = canvas ? canvas.getAttribute("style") || "" : "";
  } catch (error) {
    canvasStyle = String(error);
  }
  return {
    ok: true,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    bottom: rect.bottom,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    canvasStyle,
    key: `${Math.round(rect.y)}|${Math.round(rect.bottom)}|${canvasStyle}`
  };
}
"""


SCROLL_SEARCH_RESULTS_JS = r"""
() => {
  const scope = getSearchScope();
  const doc = scope.document;
  const win = scope.window;
  const frameRect = scope.frame ? scope.frame.getBoundingClientRect() : {
    x: 0,
    y: 0,
    width: win.innerWidth || window.innerWidth,
    height: win.innerHeight || window.innerHeight
  };

  const targets = unique([
    doc.querySelector(".geek-list-wrap"),
    doc.querySelector(".left-container"),
    doc.querySelector(".geek-content"),
    doc.querySelector("#is-gray-batch-chat"),
    doc.querySelector("#container"),
    doc.scrollingElement,
    doc.documentElement,
    doc.body
  ]).filter((target) => target && target.scrollHeight > target.clientHeight + 20);

  const before = targets.map((target) => target.scrollTop);
  for (const target of targets) {
    target.scrollTop = target.scrollHeight;
    target.dispatchEvent(new Event("scroll", { bubbles: true }));
  }
  win.scrollTo(0, Math.max(doc.documentElement.scrollHeight || 0, doc.body.scrollHeight || 0));
  win.dispatchEvent(new Event("scroll"));
  const after = targets.map((target) => target.scrollTop);

  return {
    ok: true,
    moved: after.some((value, index) => value !== before[index]),
    point: {
      x: frameRect.x + frameRect.width * 0.5,
      y: Math.max(80, Math.min(window.innerHeight - 120, frameRect.y + frameRect.height - 90))
    },
    scrolls: targets.slice(0, 6).map((target) => ({
      className: target.className || target.tagName,
      scrollTop: target.scrollTop,
      clientHeight: target.clientHeight,
      scrollHeight: target.scrollHeight
    }))
  };

  function getSearchScope() {
    const frames = [...document.querySelectorAll("iframe")];
    const frame = frames.find((item) => item.src.includes("/web/frame/search")) || frames[0];
    if (frame && frame.contentWindow && frame.contentDocument) {
      return { window: frame.contentWindow, document: frame.contentDocument, frame };
    }
    return { window, document, frame: null };
  }

  function unique(values) {
    return values.filter((value, index) => value && values.indexOf(value) === index);
  }
}
"""


class CdpClient:
    def __init__(self, ws_url: str):
        self.ws = create_connection(ws_url, timeout=20)
        self.next_id = 1

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            payload = json.loads(self.ws.recv())
            if payload.get("id") != message_id:
                continue
            if "error" in payload:
                raise RuntimeError(f"{method}: {payload['error']}")
            return payload.get("result", {})

    def evaluate(self, expression: str, arg: Any | None = None) -> Any:
        call_expression = f"({expression})({json.dumps(arg, ensure_ascii=False)})"
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": call_expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        remote = result.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return remote.get("value")

    def click(self, x: float, y: float) -> None:
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
        self.call(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        self.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        )

    def wheel(self, x: float, y: float, delta_y: float) -> None:
        self.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta_y},
        )

    def press_escape(self) -> None:
        for event_type in ("keyDown", "keyUp"):
            self.call(
                "Input.dispatchKeyEvent",
                {
                    "type": event_type,
                    "windowsVirtualKeyCode": 27,
                    "nativeVirtualKeyCode": 27,
                    "key": "Escape",
                    "code": "Escape",
                },
            )

    def capture_screenshot(self, clip: dict[str, float]) -> bytes:
        result = self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True, "clip": clip})
        return base64.b64decode(result["data"])

    def close(self) -> None:
        self.ws.close()


def capture_resume_snapshot(
    client: CdpClient,
    card: dict[str, Any],
    list_position: int,
    config: dict[str, Any],
    output_dir: Path,
    run_id: str,
) -> dict[str, Any] | None:
    point = client.evaluate(
        GET_CARD_CLICK_POINT_JS,
        {"index": int(card["index"]), "card_key": card.get("card_key"), "text": card.get("text")},
    )
    if not point or not point.get("ok"):
        return None

    client.click(float(point["x"]), float(point["y"]))
    time.sleep(int(config.get("detail_wait_ms", 900)) / 1000)

    screenshot_dir = output_dir / "resume-screenshots" / run_id
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    max_pages = int(config.get("detail_max_pages", 3))
    scroll_delta = int(config.get("detail_scroll_delta", 650))
    scroll_wait = int(config.get("detail_scroll_wait_ms", 700)) / 1000

    try:
        for page_number in range(1, max_pages + 1):
            state = wait_for_resume_frame(client)
            if not state or not state.get("ok"):
                break

            key = str(state.get("key") or "")
            if key in seen_keys:
                break
            seen_keys.add(key)

            clip = screenshot_clip_for_resume(state)
            if not clip:
                break

            image_path = screenshot_dir / f"candidate-{list_position + 1:03d}-page-{page_number:02d}.png"
            image_path.write_bytes(client.capture_screenshot(clip))
            ocr_result = ocr_image(image_path, config.get("ocr_languages", ["zh-Hans", "en-US"]))
            pages.append(
                {
                    "page": page_number,
                    "screenshot_path": str(image_path),
                    "text": ocr_result.get("text", ""),
                    "ocr_engine": ocr_result.get("engine"),
                    "ocr_error": ocr_result.get("error"),
                }
            )

            if page_number >= max_pages:
                break

            wheel_x = float(state["x"] + state["width"] / 2)
            wheel_y = float(min(max(state["y"] + state["height"] * 0.75, 80), state["viewportHeight"] - 100))
            client.wheel(wheel_x, wheel_y, scroll_delta)
            time.sleep(scroll_wait)

        text = merge_ocr_pages([page["text"] for page in pages])
        parsed = parse_resume_text(text)
        return {
            **parsed,
            "ocr_engine": next((page.get("ocr_engine") for page in pages if page.get("ocr_engine")), None),
            "ocr_pages_json": [
                {
                    "page": page["page"],
                    "screenshot_path": page["screenshot_path"],
                    "ocr_error": page.get("ocr_error"),
                }
                for page in pages
            ],
        }
    finally:
        client.press_escape()
        time.sleep(0.2)


def wait_for_resume_frame(client: CdpClient, timeout_seconds: float = 4.0) -> dict[str, Any] | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = client.evaluate(GET_RESUME_FRAME_STATE_JS)
        if state and state.get("ok"):
            return state
        time.sleep(0.2)
    return None


def screenshot_clip_for_resume(state: dict[str, Any]) -> dict[str, float] | None:
    margin_x = 10
    margin_y = 8
    left = max(0, float(state["x"]) + margin_x)
    top = max(0, float(state["y"]) + margin_y)
    right = min(float(state["viewportWidth"]), float(state["x"]) + float(state["width"]) - margin_x)
    bottom = min(float(state["viewportHeight"]) - 70, float(state["y"]) + float(state["height"]) - margin_y)
    if right - left < 300 or bottom - top < 160:
        return None
    return {"x": left, "y": top, "width": right - left, "height": bottom - top, "scale": 1}


def ocr_image(path: Path, languages: list[str]) -> dict[str, Any]:
    try:
        import Foundation  # type: ignore
        import Vision  # type: ignore
    except Exception as exc:
        return {"engine": None, "text": "", "error": f"OCR unavailable: {exc}"}

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    if languages:
        request.setRecognitionLanguages_(languages)

    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(Foundation.NSURL.fileURLWithPath_(str(path)), {})
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        return {"engine": "macos_vision", "text": "", "error": str(error)}

    items: list[dict[str, Any]] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        text = str(candidates[0].string()).strip()
        if not text:
            continue
        try:
            box = observation.boundingBox()
            x_value = float(box.origin.x)
            y_value = float(box.origin.y)
        except Exception:
            x_value = 0.0
            y_value = 0.0
        items.append({"x": x_value, "y": y_value, "text": text})

    items.sort(key=lambda item: (-round(float(item["y"]), 3), round(float(item["x"]), 3)))
    return {"engine": "macos_vision", "text": "\n".join(item["text"] for item in items), "error": None}


def merge_ocr_pages(page_texts: list[str]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for page_text in page_texts:
        for raw_line in page_text.split("\n"):
            line = raw_line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


def load_candidate_cards(client: CdpClient, config: dict[str, Any]) -> list[dict[str, Any]]:
    load_all = bool(config.get("load_all"))
    configured_limit = int(config.get("limit") or 0)
    hard_max = int(config.get("hard_max_candidates", 1000))
    target_count = None if load_all or configured_limit <= 0 else configured_limit
    collect_limit = target_count or hard_max
    max_rounds = int(config.get("max_scroll_rounds", 80))
    no_growth_rounds = int(config.get("no_growth_rounds", 2))
    wait_seconds = int(config.get("load_more_wait_ms", 1400)) / 1000
    scroll_delta = int(config.get("load_more_scroll_delta", 900))

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous_count = -1
    stable_rounds = 0

    for round_number in range(max_rounds + 1):
        current_cards = client.evaluate(COLLECT_CARDS_JS, collect_limit) or []
        for card in current_cards:
            key = card.get("card_key") or card.get("text")
            if not key or key in seen:
                continue
            seen.add(key)
            cards.append(card)

        if len(cards) != previous_count:
            print(f"已加载候选人卡片：{len(cards)}")
            previous_count = len(cards)
            stable_rounds = 0
        else:
            stable_rounds += 1

        if target_count and len(cards) >= target_count:
            return cards[:target_count]
        if len(cards) >= hard_max:
            print(f"达到 hard_max_candidates={hard_max}，停止继续加载。")
            return cards[:hard_max]
        if round_number > 0 and stable_rounds >= no_growth_rounds:
            return cards

        state = client.evaluate(SCROLL_SEARCH_RESULTS_JS)
        if state and state.get("point"):
            point = state["point"]
            client.wheel(float(point["x"]), float(point["y"]), scroll_delta)
        time.sleep(wait_seconds)

    return cards[:target_count] if target_count else cards


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.limit is not None:
        config["limit"] = args.limit
    if args.no_details:
        config["include_details"] = False
    if args.skip_apply:
        config["skip_apply"] = True
    if args.cdp_url:
        config["cdp_url"] = args.cdp_url
    if args.detail_max_pages is not None:
        config["detail_max_pages"] = args.detail_max_pages
    if args.load_all:
        config["load_all"] = True
    if args.max_scroll_rounds is not None:
        config["max_scroll_rounds"] = args.max_scroll_rounds

    output_dir = Path(config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    target = get_or_create_target(config["cdp_url"], config["start_url"])
    print(f"连接 Chrome target: {target.get('url')}")
    client = CdpClient(target["webSocketDebuggerUrl"])
    run_id = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")

    try:
        if config.get("manual_ready", True):
            input("请在远程调试 Chrome 中确认已登录 BOSS，并停在人才库搜索页。准备好后按回车继续...")

        if not config.get("skip_apply"):
            client.evaluate(APPLY_CONFIG_JS, config)
            time.sleep(1.2)
        cards = load_candidate_cards(client, config)
        if not cards:
            print("没有识别到候选人卡片。请确认 Chrome target 是 BOSS 人才库搜索页，且列表可见。")
            return

        candidates = []
        observations = []
        resume_snapshots = []
        collected_at = datetime.now(timezone.utc)
        observed_at = collected_at.isoformat()
        for list_position, card in enumerate(cards):
            card_index = parse_candidate_card_text(card["text"])
            detail_index = {}
            resume_snapshot = None
            if config.get("include_details", True):
                resume_snapshot = capture_resume_snapshot(
                    client,
                    card,
                    list_position,
                    config,
                    output_dir,
                    run_id,
                )
                if resume_snapshot and resume_snapshot.get("resume_text"):
                    detail_index = {
                        "detail_summary": resume_snapshot.get("detail_summary"),
                        "detail_tags_json": resume_snapshot.get("detail_tags_json", []),
                        "detail_schools_json": resume_snapshot.get("detail_schools_json", []),
                        "detail_companies_json": resume_snapshot.get("detail_companies_json", []),
                        "detail_positions_json": resume_snapshot.get("detail_positions_json", []),
                    }

            candidate = {
                "source_platform": "boss_zhipin",
                **card_index,
                **detail_index,
                "source_url": target.get("url"),
                "last_seen_at": infer_last_seen_at(card_index.get("active_status"), collected_at),
            }
            candidate["source_fingerprint"] = create_candidate_fingerprint(candidate)
            candidates.append(candidate)
            if resume_snapshot and resume_snapshot.get("resume_text"):
                resume_snapshots.append(
                    {
                        "source_platform": "boss_zhipin",
                        "source_fingerprint": candidate["source_fingerprint"],
                        "collected_at": observed_at,
                        "source_url": target.get("url"),
                        "parser_version": "resume_ocr_v1",
                        "resume_text": resume_snapshot.get("resume_text"),
                        "resume_text_hash": resume_snapshot.get("resume_text_hash"),
                        "resume_sections_json": resume_snapshot.get("resume_sections_json", {}),
                        "detail_summary": resume_snapshot.get("detail_summary"),
                        "detail_tags_json": resume_snapshot.get("detail_tags_json", []),
                        "detail_schools_json": resume_snapshot.get("detail_schools_json", []),
                        "detail_companies_json": resume_snapshot.get("detail_companies_json", []),
                        "detail_positions_json": resume_snapshot.get("detail_positions_json", []),
                        "ocr_engine": resume_snapshot.get("ocr_engine"),
                        "ocr_pages_json": resume_snapshot.get("ocr_pages_json", []),
                    }
                )
            observations.append(
                {
                    "source_platform": "boss_zhipin",
                    "source_fingerprint": candidate["source_fingerprint"],
                    "observed_at": observed_at,
                    "source_url": target.get("url"),
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
        append_jsonl(output_dir / "resume_snapshots.ndjson", resume_snapshots)
        run_file = write_run(
            output_dir,
            run_id,
            {
                "runId": run_id,
                "mode": "raw_cdp",
                "count": len(candidates),
                "resume_snapshot_count": len(resume_snapshots),
                "candidates": candidates,
                "observations": observations,
                "resume_snapshots": resume_snapshots,
            },
        )
        print(f"完成：{len(candidates)} 条候选人索引。")
        if config.get("include_details", True):
            print(f"在线简历快照：{len(resume_snapshots)} 条。")
        print(f"单次运行结果：{run_file}")
    finally:
        client.close()


def get_or_create_target(cdp_url: str, start_url: str) -> dict[str, Any]:
    targets = request_json(f"{cdp_url.rstrip('/')}/json/list")
    for target in targets:
        if target.get("type") == "page" and "zhipin.com/web/chat/search" in target.get("url", ""):
            return target
    encoded = urllib.parse.quote(start_url, safe=":/?=&")
    return request_json(f"{cdp_url.rstrip('/')}/json/new?{encoded}", method="PUT")


def request_json(url: str, method: str = "GET") -> Any:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


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
    parser = argparse.ArgumentParser(description="BOSS 人才库 raw CDP 采集助手")
    parser.add_argument("--config", default="boss_filters.example.json", help="筛选配置 JSON")
    parser.add_argument("--limit", type=int, default=None, help="覆盖配置里的采集数量")
    parser.add_argument("--cdp-url", default=None, help="Chrome DevTools URL，例如 http://127.0.0.1:9222")
    parser.add_argument("--no-details", action="store_true", help="只采列表，不点详情")
    parser.add_argument("--detail-max-pages", type=int, default=None, help="每份在线简历最多滚动 OCR 几屏")
    parser.add_argument("--load-all", action="store_true", help="持续向下加载，直到没有更多候选人")
    parser.add_argument("--max-scroll-rounds", type=int, default=None, help="加载更多阶段最多滚动轮数")
    parser.add_argument("--skip-apply", action="store_true", help="跳过自动筛选/搜索，直接读取当前页面")
    return parser.parse_args()


if __name__ == "__main__":
    main()
