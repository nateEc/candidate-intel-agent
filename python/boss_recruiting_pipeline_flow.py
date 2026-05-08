from __future__ import annotations

import re
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import candidate_evaluator
import talent_store
from boss_cdp_capture import (
    CdpClient,
    merge_ocr_pages,
    ocr_image,
    screenshot_clip_for_resume,
    wait_for_resume_frame,
)
from boss_parse import create_candidate_fingerprint, parse_resume_text


CHAT_URL = "https://www.zhipin.com/web/chat/index"


NAVIGATE_CHAT_JS = r"""
(url) => {
  if (!location.href.includes("/web/chat/index")) {
    location.href = url;
    return { ok: true, navigated: true, url: location.href };
  }
  return { ok: true, navigated: false, url: location.href };
}
"""


READ_PAGE_BLOCKER_JS = r"""
() => {
  const url = location.href;
  const text = String(document.body?.innerText || "");
  if (/passport|verify|安全验证|验证/.test(url) || /安全验证|验证|请完成验证|登录/.test(text)) {
    return { blocked: true, url, text: text.slice(0, 300) };
  }
  return { blocked: false, url };
}
"""


PREPARE_CONTACTS_TAB_JS = r"""
async () => {
  const actions = [];
  await pause(300);
  clickText("全部");
  actions.push("tab:全部");
  await pause(120);
  return { ok: true, actions, selectedJob: readSelectedJob(), url: location.href };

  function findJobTrigger() {
    const nodes = [...document.querySelectorAll("button, div, span")].filter(visible);
    const byClass = nodes.find((node) => {
      const cls = String(node.className || "");
      const text = normalize(node.textContent);
      return /chat-top-job|job-select|chat-select-job/.test(cls) && /职位|工程师|开发|产品|运营|设计|K/.test(text);
    });
    if (byClass) return byClass;
    const candidates = nodes.filter((node) => {
      const rect = node.getBoundingClientRect();
      const text = normalize(node.textContent);
      if (rect.left < 180 || rect.left > window.innerWidth * 0.48) return false;
      if (rect.top < 90 || rect.top > 180 || rect.height < 18 || rect.height > 68) return false;
      if (rect.width < 160 || rect.width > 520 || text.length > 90) return false;
      if (/未读|批量|刚刚|昨天|回复|应聘|沟通/.test(text)) return false;
      return /职位|工程师|开发|产品|运营|设计|K/.test(text);
    });
    return candidates.sort((a, b) => scoreTrigger(b) - scoreTrigger(a))[0];
  }

  function scoreTrigger(node) {
    const text = normalize(node.textContent);
    let score = 0;
    if (/全部职位/.test(text)) score += 6;
    if (/职位|工程师|开发|产品|运营|设计|K/.test(text)) score += 3;
    if (node.getBoundingClientRect().width > 240) score += 1;
    return score;
  }

  function readSelectedJob() {
    const trigger = findJobTrigger();
    return trigger ? selectedJobText(trigger) : "";
  }

  function selectedJobText(trigger) {
    const label = trigger.matches && trigger.matches(".chat-select-job") ? trigger : trigger.querySelector?.(".chat-select-job");
    const input = trigger.querySelector?.("input.chat-job-search") || document.querySelector("input.chat-job-search");
    const text = normalize(label ? label.textContent : trigger.textContent);
    return text || normalize(input ? input.value : "");
  }

  function clickText(label, options = {}) {
    const nodes = [...document.querySelectorAll("button, a, span, div, li")].filter(visible);
    const exact = nodes.find((node) => normalize(node.textContent) === label);
    if (exact) return clickElement(exact);
    if (!options.allowContains) return false;
    const contains = nodes.find((node) => {
      const text = normalize(node.textContent);
      return text.includes(label) && text.length <= label.length + 20;
    });
    return clickElement(contains);
  }

  function clickElement(node) {
    if (!node) return false;
    node.scrollIntoView({ block: "center", inline: "nearest" });
    const rect = node.getBoundingClientRect();
    const x = rect.x + rect.width / 2;
    const y = rect.y + rect.height / 2;
    for (const type of ["mouseover", "mousemove", "mousedown", "mouseup", "click"]) {
      node.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0 }));
    }
    return true;
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function pause(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
"""


FIND_JOB_TRIGGER_POINT_JS = r"""
() => {
  const trigger = findJobTrigger();
  if (!trigger) return { ok: false, reason: "job-trigger-not-found", selectedJob: readSelectedJob() };
  const rect = trigger.getBoundingClientRect();
  return {
    ok: true,
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
    text: selectedJobText(trigger),
    rect: rectOf(trigger)
  };

  function findJobTrigger() {
    const nodes = [...document.querySelectorAll("button, div, span")].filter(visible);
    const byClass = nodes.find((node) => {
      const cls = String(node.className || "");
      const text = normalize(node.textContent);
      return /chat-top-job|job-select|chat-select-job/.test(cls) && /职位|工程师|开发|产品|运营|设计|K/.test(text);
    });
    if (byClass) return byClass;
    const candidates = nodes.filter((node) => {
      const rect = node.getBoundingClientRect();
      const text = normalize(node.textContent);
      if (rect.left < 180 || rect.left > window.innerWidth * 0.48) return false;
      if (rect.top < 90 || rect.top > 180 || rect.height < 18 || rect.height > 68) return false;
      if (rect.width < 160 || rect.width > 520 || text.length > 90) return false;
      if (/未读|批量|刚刚|昨天|回复|应聘|沟通/.test(text)) return false;
      return /职位|工程师|开发|产品|运营|设计|K/.test(text);
    });
    return candidates.sort((a, b) => scoreTrigger(b) - scoreTrigger(a))[0];
  }

  function scoreTrigger(node) {
    const text = normalize(node.textContent);
    let score = 0;
    if (/全部职位/.test(text)) score += 6;
    if (/职位|工程师|开发|产品|运营|设计|K/.test(text)) score += 3;
    if (node.getBoundingClientRect().width > 240) score += 1;
    return score;
  }

  function readSelectedJob() {
    const trigger = findJobTrigger();
    return trigger ? selectedJobText(trigger) : "";
  }

  function selectedJobText(trigger) {
    const label = trigger.matches && trigger.matches(".chat-select-job") ? trigger : trigger.querySelector?.(".chat-select-job");
    const input = trigger.querySelector?.("input.chat-job-search") || document.querySelector("input.chat-job-search");
    const text = normalize(label ? label.textContent : trigger.textContent);
    return text || normalize(input ? input.value : "");
  }

  function rectOf(node) {
    const rect = node.getBoundingClientRect();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }
}
"""


FIND_JOB_OPTION_POINT_JS = r"""
(label) => {
  const labelNorm = normalize(label);
  const list = document.querySelector(".ui-dropmenu-visible .ui-dropmenu-list") || document.querySelector(".ui-dropmenu-list");
  const nodes = (list ? [...list.querySelectorAll("li, span, div, a, button")] : [...document.querySelectorAll("li, span, div, a, button")]).filter(visible);
  const options = nodes.filter((node) => {
    const rect = node.getBoundingClientRect();
    const text = normalize(node.textContent);
    if (!text || text.length > 120 || /请输入职位名称|未读|批量|刚刚|昨天|回复|应聘/.test(text)) return false;
    if (!list) {
      if (rect.left < 180 || rect.left > window.innerWidth * 0.5) return false;
      if (rect.top < 110 || rect.top > 420) return false;
    }
    return text === labelNorm || text.includes(labelNorm) || labelNorm.includes(text);
  });
  const exact = options.find((node) => normalize(node.textContent) === labelNorm);
  const best = exact || options.sort((a, b) => normalize(a.textContent).length - normalize(b.textContent).length)[0];
  if (!best) return { ok: false, reason: "job-option-not-found", visibleOptions: nodes.map((node) => normalize(node.textContent)).filter(Boolean).slice(0, 20) };
  const rect = best.getBoundingClientRect();
  return { ok: true, x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, text: normalize(best.textContent), rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height } };

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }
}
"""


SET_JOB_SEARCH_JS = r"""
(label) => {
  const input = [...document.querySelectorAll("input")].find((item) => visible(item) && /职位/.test(item.placeholder || ""));
  if (!input) return { ok: false, reason: "job-search-input-not-found" };
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  input.focus();
  setter.call(input, label || "");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true, value: input.value };

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }
}
"""


SCROLL_RESUME_FRAME_JS = r"""
(delta) => {
  const frame = [...document.querySelectorAll("iframe")].find((item) => item.src.includes("/web/frame/c-resume"));
  if (!frame || !frame.contentDocument) return { ok: false, reason: "resume-frame-not-found" };
  const doc = frame.contentDocument;
  const win = frame.contentWindow;
  const targets = [
    doc.scrollingElement,
    doc.documentElement,
    doc.body,
    ...doc.querySelectorAll("main, section, article, div")
  ].filter((target, index, array) => {
    if (!target || array.indexOf(target) !== index) return false;
    return target.scrollHeight > target.clientHeight + 20;
  });
  const target = targets.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
  if (!target) {
    if (win) {
      const beforeY = win.scrollY || 0;
      win.scrollBy(0, Number(delta || 650));
      return { ok: true, moved: (win.scrollY || 0) !== beforeY, scrollTop: Math.round(win.scrollY || 0) };
    }
    return { ok: false, reason: "scroll-target-not-found" };
  }
  const before = target.scrollTop;
  target.scrollTop = Math.min(target.scrollHeight, target.scrollTop + Number(delta || 650));
  target.dispatchEvent(new Event("scroll", { bubbles: true }));
  if (win) win.dispatchEvent(new Event("scroll"));
  return {
    ok: true,
    moved: target.scrollTop !== before,
    scrollTop: Math.round(target.scrollTop),
    scrollHeight: Math.round(target.scrollHeight),
    clientHeight: Math.round(target.clientHeight),
    atBottom: target.scrollTop + target.clientHeight >= target.scrollHeight - 24
  };
}
"""


COLLECT_CONTACTS_JS = r"""
(limit) => {
  const contacts = [];
  const seen = new Set();
  for (const item of findContactItems()) {
    const text = normalize(item.innerText || item.textContent || "");
    if (!text || seen.has(text)) continue;
    seen.add(text);
    contacts.push({
      index: contacts.length,
      card_key: hash(text),
      text,
      rect: rectOf(item),
      has_unread: Boolean(item.querySelector(".unread, .badge, [class*=unread]"))
    });
    if (contacts.length >= limit) break;
  }
  return {
    contacts,
    endReached: /没有更多了/.test(document.body.innerText || ""),
    selectedJob: readSelectedJob()
  };

  function findContactItems() {
    const preferred = [...document.querySelectorAll(".geek-item-wrap, .geek-item")].filter(visible);
    const nodes = preferred.length ? preferred : [...document.querySelectorAll("li, a, div")].filter(visible);
    return nodes.filter((node) => {
      const rect = node.getBoundingClientRect();
      if (rect.left < 180 || rect.left > window.innerWidth * 0.48) return false;
      if (rect.top < 120 || rect.width < 220 || rect.height < 36 || rect.height > 140) return false;
      const text = normalize(node.innerText || node.textContent || "");
      if (!text || /全部职位|未读|批量|没有更多了/.test(text)) return false;
      return /工程师|开发|产品|运营|设计|经理|顾问|AI|Java|前端|后端/.test(text) || /\d{1,2}:\d{2}|昨天|刚刚/.test(text);
    });
  }

  function readSelectedJob() {
    const nodes = [...document.querySelectorAll("button, div, span")].filter(visible);
    const byClass = nodes.find((item) => {
      const text = normalize(item.textContent);
      return /chat-select-job|chat-top-job|job-select/.test(String(item.className || "")) && /职位|工程师|开发|产品|运营|设计|K/.test(text);
    });
    if (byClass) return selectedJobText(byClass);
    const node = nodes.find((item) => {
      const rect = item.getBoundingClientRect();
      const text = normalize(item.textContent);
      if (rect.left < 180 || rect.left > window.innerWidth * 0.48) return false;
      if (rect.top < 90 || rect.top > 180 || rect.height < 18 || rect.height > 68) return false;
      if (rect.width < 160 || rect.width > 520 || text.length > 90) return false;
      if (/未读|批量|刚刚|昨天|回复|应聘|沟通/.test(text)) return false;
      return /职位|工程师|开发|产品|运营|设计|K/.test(text);
    });
    return node ? normalize(node.textContent) : "";
  }

  function selectedJobText(trigger) {
    const label = trigger.matches && trigger.matches(".chat-select-job") ? trigger : trigger.querySelector?.(".chat-select-job");
    const input = trigger.querySelector?.("input.chat-job-search") || document.querySelector("input.chat-job-search");
    const text = normalize(label ? label.textContent : trigger.textContent);
    return text || normalize(input ? input.value : "");
  }

  function rectOf(node) {
    const rect = node.getBoundingClientRect();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\r/g, "").split("\n").map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
  }

  function hash(text) {
    let value = 0;
    for (let index = 0; index < text.length; index += 1) value = ((value << 5) - value + text.charCodeAt(index)) | 0;
    return String(value);
  }
}
"""


CLICK_CONTACT_JS = r"""
(request) => {
  const cards = findContactItems();
  let target = null;
  if (request && request.text) {
    const prefix = normalize(request.text).slice(0, 80);
    target = cards.find((item) => normalize(item.innerText || item.textContent || "").startsWith(prefix));
  }
  if (!target && Number.isInteger(request.index)) target = cards[request.index];
  if (!target) return { ok: false, count: cards.length };
  target.scrollIntoView({ block: "center", inline: "nearest" });
  const rect = target.getBoundingClientRect();
  return { ok: true, x: rect.x + Math.min(80, rect.width * 0.25), y: rect.y + Math.min(45, rect.height * 0.5), text: normalize(target.innerText || target.textContent || "") };

  function findContactItems() {
    const preferred = [...document.querySelectorAll(".geek-item-wrap, .geek-item")].filter(visible);
    const nodes = preferred.length ? preferred : [...document.querySelectorAll("li, a, div")].filter(visible);
    return nodes.filter((node) => {
      const rect = node.getBoundingClientRect();
      if (rect.left < 180 || rect.left > window.innerWidth * 0.48) return false;
      if (rect.top < 120 || rect.width < 220 || rect.height < 36 || rect.height > 140) return false;
      const text = normalize(node.innerText || node.textContent || "");
      if (!text || /全部职位|未读|批量|没有更多了/.test(text)) return false;
      return /工程师|开发|产品|运营|设计|经理|顾问|AI|Java|前端|后端/.test(text) || /\d{1,2}:\d{2}|昨天|刚刚/.test(text);
    });
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\r/g, "").split("\n").map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
  }
}
"""


SCROLL_CONTACTS_JS = r"""
() => {
  const targets = [...document.querySelectorAll("div, ul")].filter((node) => {
    const rect = node.getBoundingClientRect();
    return rect.left > 250 && rect.right < window.innerWidth * 0.52 && node.scrollHeight > node.clientHeight + 20;
  });
  const target = targets.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] || document.scrollingElement;
  const before = target.scrollTop;
  target.scrollTop = Math.min(target.scrollHeight, target.scrollTop + 900);
  target.dispatchEvent(new Event("scroll", { bubbles: true }));
  const rect = target.getBoundingClientRect();
  return { ok: true, moved: target.scrollTop !== before, x: rect.x + rect.width / 2, y: Math.min(window.innerHeight - 120, rect.y + rect.height - 80) };
}
"""


READ_PROFILE_JS = r"""
() => {
  const rightTexts = [];
  const headerTexts = [];
  for (const node of [...document.querySelectorAll("div, section, header, span")].filter(visible)) {
    const rect = node.getBoundingClientRect();
    if (rect.left < window.innerWidth * 0.48) continue;
    const text = normalize(node.innerText || node.textContent || "");
    if (!text) continue;
    if (rect.top < 300) headerTexts.push(text);
    if (rect.height > 12 && text.length > 1) rightTexts.push(text);
  }
  const bodyText = normalize(rightTexts.join("\n"));
  return {
    ok: true,
    url: location.href,
    header_text: chooseHeader(headerTexts),
    body_text: bodyText.slice(0, 5000),
    input_text: readInputText()
  };

  function chooseHeader(texts) {
    return texts.sort((a, b) => score(b) - score(a))[0] || "";
  }

  function score(text) {
    let value = 0;
    if (/\d{2}岁/.test(text)) value += 3;
    if (/本科|硕士|博士|大专/.test(text)) value += 2;
    if (/期望|沟通职位/.test(text)) value += 2;
    return value + Math.min(text.length / 80, 3);
  }

  function readInputText() {
    const nodes = [...document.querySelectorAll("textarea, [contenteditable=true], .input-area, .chat-input, .boss-chat-editor-input")].filter(visible);
    const node = nodes.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0];
    return node ? normalize(node.value || node.innerText || node.textContent || "") : "";
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\r/g, "").split("\n").map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
  }
}
"""


CLICK_RESUME_BUTTON_JS = r"""
() => {
  const candidates = [...document.querySelectorAll("button, a, div")].filter(visible).map((node) => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return { node, rect, text: normalize(node.innerText || node.textContent || ""), bg: style.backgroundColor, cls: String(node.className || "") };
  }).filter((item) => {
    if (item.rect.left < window.innerWidth * 0.72 || item.rect.top > 330 || item.rect.width < 28 || item.rect.width > 80 || item.rect.height < 28 || item.rect.height > 80) return false;
    return /resume|简历|card|geek/i.test(item.cls) || /rgb\(.*(180|190|200).*\)/.test(item.bg) || !item.text;
  }).sort((a, b) => a.rect.left - b.rect.left);
  const item = candidates[0];
  if (!item) return { ok: false };
  return { ok: true, x: item.rect.x + item.rect.width / 2, y: item.rect.y + item.rect.height / 2, text: item.text, className: item.cls };

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }
}
"""


PREPARE_QUICK_REPLY_JS = r"""
(request) => {
  const custom = request && request.message_text;
  if (custom) {
    const input = findInput();
    if (!input) return { ok: false, reason: "input-not-found" };
    setInput(input, custom);
    return { ok: true, input_text: readInputText(), source: "custom" };
  }

  if (quickReplyRows().length) {
    return { ok: true, opened: true, input_text: readInputText(), source: "quick_reply_pending" };
  }

  const common = findQuickReplyButton();
  if (!common) return { ok: false, reason: "quick-reply-button-not-found" };
  const rect = common.getBoundingClientRect();
  return {
    ok: true,
    opened: false,
    needs_click: true,
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
    input_text: readInputText(),
    source: "quick_reply_button"
  };

  function findQuickReplyButton() {
    const nodes = [...document.querySelectorAll("button, a, span, div")].filter(visible);
    return nodes.find((node) => {
      const text = normalize(node.innerText || node.textContent);
      const cls = String(node.className || "");
      const rect = node.getBoundingClientRect();
      if (rect.left < window.innerWidth * 0.45 || rect.top < window.innerHeight * 0.55) return false;
      return text === "常" || text === "常用语" || /changyongyu|quick|phrase|reply/i.test(cls);
    });
  }

  function quickReplyRows() {
    return [...document.querySelectorAll(".phrase-content li, .phrase-content [role=option]")].filter(visible).filter((node) => {
      const text = normalize(node.innerText || node.textContent);
      return text.length >= 4 && !/^设置$|^常用语$/.test(text);
    });
  }

  function findInput() {
    return [...document.querySelectorAll("textarea, [contenteditable=true], .input-area, .chat-input, .boss-chat-editor-input")].filter(visible).sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0];
  }

  function setInput(node, value) {
    if ("value" in node) {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (setter) setter.call(node, value);
      else node.value = value;
    } else {
      node.textContent = value;
    }
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function readInputText() {
    const input = findInput();
    return input ? normalize(input.value || input.innerText || input.textContent || "") : "";
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }
}
"""


SELECT_QUICK_REPLY_JS = r"""
(index) => {
  const phraseRows = [...document.querySelectorAll(".phrase-content li, .phrase-content [role=option]")].filter(visible).filter((node) => {
    const text = normalize(node.textContent);
    return text.length >= 4 && !/^发送$|^设置$|^常用语$/.test(text);
  });
  const row = phraseRows[index || 0];
  if (!row) return { ok: false, reason: "quick-reply-options-not-found", count: phraseRows.length };
  const rect = row.getBoundingClientRect();
  return {
    ok: true,
    count: phraseRows.length,
    selected_text: cleanPhraseText(row.textContent),
    x: rect.x + Math.min(rect.width - 20, Math.max(20, rect.width * 0.5)),
    y: rect.y + rect.height / 2,
    input_text: readInputText()
  };

  function readInputText() {
    const nodes = [...document.querySelectorAll("textarea, [contenteditable=true], .input-area, .chat-input, .boss-chat-editor-input")].filter(visible);
    const node = nodes.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0];
    return node ? normalize(node.value || node.innerText || node.textContent || "") : "";
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function cleanPhraseText(text) {
    return normalize(text).replace(/\s*发送$/, "").trim();
  }
}
"""


SEND_MESSAGE_JS = r"""
() => {
  const inputText = readInputText();
  const buttons = [...document.querySelectorAll("button, a, span, div")].filter(visible).filter((node) => {
    const rect = node.getBoundingClientRect();
    return rect.left > window.innerWidth * 0.74 && rect.top > window.innerHeight * 0.78 && normalize(node.textContent) === "发送";
  });
  const button = buttons.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0];
  if (!button) return { ok: false, reason: "send-button-not-found", input_text: inputText };
  button.click();
  return { ok: true, input_text: inputText };

  function readInputText() {
    const nodes = [...document.querySelectorAll("textarea, [contenteditable=true], .input-area, .chat-input, .boss-chat-editor-input")].filter(visible);
    const node = nodes.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0];
    return node ? normalize(node.value || node.innerText || node.textContent || "") : "";
  }

  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0 && !node.disabled;
  }

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }
}
"""


def scan_applications(client: CdpClient, payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
    job_filter = payload.get("job_filter") or payload.get("job_title")
    limit = int(payload.get("limit") or 20)
    include_resumes = bool(payload.get("include_resumes", True))
    detail_max_pages = int(payload.get("detail_max_pages") or 8)
    detail_wait_ms = int(payload.get("detail_wait_ms") or 1200)
    detail_scroll_delta = int(payload.get("detail_scroll_delta") or 620)
    detail_scroll_wait_ms = int(payload.get("detail_scroll_wait_ms") or 900)
    profile_wait_ms = int(payload.get("profile_wait_ms") or 1200)
    candidate_wait_ms = int(payload.get("candidate_wait_ms") or 2600)
    candidate_jitter_ms = int(payload.get("candidate_jitter_ms") or 1400)
    output_dir = Path(payload.get("output_dir") or "data-python").resolve()

    with talent_store.connect(db_path) as conn:
        scan_id = talent_store.create_scan_run(conn, job_filter, {"payload": public_scan_payload(payload)})

    try:
        client.evaluate(NAVIGATE_CHAT_JS, CHAT_URL)
        time.sleep(1.2)
        blocker = read_page_blocker(client)
        if blocker.get("blocked"):
            with talent_store.connect(db_path) as conn:
                talent_store.finish_scan_run(conn, scan_id, "blocked_needs_human", 0, 0, raw={"blocker": blocker})
            return {
                "status": "blocked_needs_human",
                "message": "BOSS 触发登录或安全验证，需要人工在浏览器里处理。",
                "scan_run_id": scan_id,
                "blocker": blocker,
                "count": 0,
                "candidates": [],
                "dry_run": bool(payload.get("dry_run", True)),
            }
        filter_result = apply_job_filter(client, job_filter)
        if job_filter and not filter_result.get("ok"):
            with talent_store.connect(db_path) as conn:
                talent_store.finish_scan_run(conn, scan_id, "needs_manual", 0, 0, raw={"filter": filter_result})
            return {
                "status": "needs_manual",
                "message": f"未能自动选择岗位：{job_filter}。请在浏览器里手动选择后重试。",
                "scan_run_id": scan_id,
                "job_filter": filter_result.get("selectedJob") or job_filter,
                "filter": filter_result,
                "count": 0,
                "candidates": [],
                "dry_run": bool(payload.get("dry_run", True)),
            }
        blocker = read_page_blocker(client)
        if blocker.get("blocked"):
            with talent_store.connect(db_path) as conn:
                talent_store.finish_scan_run(conn, scan_id, "blocked_needs_human", 0, 0, raw={"filter": filter_result, "blocker": blocker})
            return {
                "status": "blocked_needs_human",
                "message": "BOSS 触发登录或安全验证，需要人工在浏览器里处理。",
                "scan_run_id": scan_id,
                "job_filter": filter_result.get("selectedJob") or job_filter,
                "blocker": blocker,
                "count": 0,
                "candidates": [],
                "dry_run": bool(payload.get("dry_run", True)),
            }
        contacts = load_contacts(client, limit)

        results = []
        for index, contact in enumerate(contacts[:limit]):
            human_pause(candidate_wait_ms, candidate_jitter_ms, skip=index == 0)
            if not click_contact(client, contact, index):
                continue
            time.sleep(max(0, profile_wait_ms) / 1000)
            blocker = read_page_blocker(client)
            if blocker.get("blocked"):
                with talent_store.connect(db_path) as conn:
                    talent_store.finish_scan_run(conn, scan_id, "partial_ready", len(results), len(results), raw={"filter": filter_result, "blocker": blocker})
                return {
                    "status": "partial_ready" if results else "blocked_needs_human",
                    "message": "BOSS 触发登录或安全验证，需要人工在浏览器里处理。",
                    "scan_run_id": scan_id,
                    "job_filter": filter_result.get("selectedJob") or job_filter,
                    "blocker": blocker,
                    "count": len(results),
                    "candidates": results,
                    "dry_run": bool(payload.get("dry_run", True)),
                }
            profile = client.evaluate(READ_PROFILE_JS) or {}
            resume_snapshot = (
                capture_current_resume(
                    client,
                    output_dir,
                    scan_id,
                    index,
                    detail_max_pages,
                    detail_wait_ms=detail_wait_ms,
                    scroll_delta=detail_scroll_delta,
                    scroll_wait_ms=detail_scroll_wait_ms,
                )
                if include_resumes
                else None
            )
            candidate = build_candidate(contact, profile, resume_snapshot)
            application = build_application(contact, profile, scan_id, filter_result.get("selectedJob") or job_filter)
            evaluation = candidate_evaluator.evaluate_candidate(candidate, payload.get("job_profile") or {}, (resume_snapshot or {}).get("resume_text"))
            with talent_store.connect(db_path) as conn:
                fingerprint = talent_store.upsert_application_candidate(conn, candidate, application, evaluation, resume_snapshot)
            results.append(
                {
                    "source_fingerprint": fingerprint,
                    "candidate": candidate,
                    "application": application,
                    "evaluation": evaluation,
                    "has_resume": bool(resume_snapshot and resume_snapshot.get("resume_text")),
                }
            )

        with talent_store.connect(db_path) as conn:
            talent_store.finish_scan_run(
                conn,
                scan_id,
                "ready",
                candidate_count=len(results),
                application_count=len(results),
                raw={"filter": filter_result, "contact_count": len(contacts)},
            )

        return {
            "status": "ready",
            "message": f"已巡检 {len(results)} 位投递/沟通候选人。",
            "scan_run_id": scan_id,
            "job_filter": filter_result.get("selectedJob") or job_filter,
            "count": len(results),
            "candidates": results,
            "dry_run": bool(payload.get("dry_run", True)),
        }
    except Exception as exc:
        with talent_store.connect(db_path) as conn:
            talent_store.finish_scan_run(conn, scan_id, "failed", 0, 0, raw={"error": str(exc)})
        raise


def read_page_blocker(client: CdpClient) -> dict[str, Any]:
    return client.evaluate(READ_PAGE_BLOCKER_JS) or {"blocked": False}


def apply_job_filter(client: CdpClient, job_filter: str | None) -> dict[str, Any]:
    result = client.evaluate(PREPARE_CONTACTS_TAB_JS) or {}
    result.setdefault("actions", [])
    if not job_filter:
        result["ok"] = True
        return result

    trigger = client.evaluate(FIND_JOB_TRIGGER_POINT_JS) or {}
    result["trigger"] = trigger
    if not trigger.get("ok"):
        result.update({"ok": False, "reason": trigger.get("reason") or "job-trigger-not-found"})
        return result

    client.click(float(trigger["x"]), float(trigger["y"]))
    result["actions"].append("job-filter:open")
    time.sleep(0.35)

    option = client.evaluate(FIND_JOB_OPTION_POINT_JS, job_filter) or {}
    if not option.get("ok"):
        search = client.evaluate(SET_JOB_SEARCH_JS, job_filter) or {}
        result["search"] = search
        result["actions"].append("job-filter:search")
        time.sleep(0.25)
        option = client.evaluate(FIND_JOB_OPTION_POINT_JS, job_filter) or {}
    result["option"] = option
    if not option.get("ok"):
        result.update({"ok": False, "reason": option.get("reason") or "job-option-not-found"})
        return result

    client.click(float(option["x"]), float(option["y"]))
    result["actions"].append(f"job-filter:{option.get('text') or job_filter}")
    time.sleep(0.8)
    selected = (client.evaluate(PREPARE_CONTACTS_TAB_JS) or {}).get("selectedJob") or ""
    result["selectedJob"] = selected
    if not selected_job_matches(selected, job_filter):
        result.update({"ok": False, "reason": "selected-job-mismatch"})
        return result
    result["ok"] = True
    return result


def selected_job_matches(selected_job: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    selected = normalize_for_match(selected_job)
    target = normalize_for_match(requested)
    if not selected or selected == normalize_for_match("全部职位"):
        return False
    return target in selected or selected in target


def normalize_for_match(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def human_pause(base_ms: int, jitter_ms: int = 0, *, skip: bool = False) -> None:
    if skip:
        return
    delay_ms = max(0, int(base_ms or 0))
    if jitter_ms > 0:
        delay_ms += random.randint(0, int(jitter_ms))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000)


def load_contacts(client: CdpClient, limit: int) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    seen = set()
    stable_rounds = 0
    for _ in range(60):
        state = client.evaluate(COLLECT_CONTACTS_JS, max(limit, 1)) or {}
        for contact in state.get("contacts", []):
            key = contact.get("card_key") or contact.get("text")
            if not key or key in seen:
                continue
            seen.add(key)
            contacts.append(contact)
        if len(contacts) >= limit or state.get("endReached"):
            return contacts[:limit]
        before = len(contacts)
        scroll = client.evaluate(SCROLL_CONTACTS_JS) or {}
        if scroll.get("x") and scroll.get("y"):
            client.wheel(float(scroll["x"]), float(scroll["y"]), 900)
        time.sleep(1.0)
        stable_rounds = stable_rounds + 1 if len(contacts) == before else 0
        if stable_rounds >= 3:
            return contacts[:limit]
    return contacts[:limit]


def click_contact(client: CdpClient, contact: dict[str, Any], index: int) -> bool:
    point = client.evaluate(CLICK_CONTACT_JS, {"text": contact.get("text"), "index": index}) or {}
    if not point.get("ok"):
        return False
    client.click(float(point["x"]), float(point["y"]))
    return True


def capture_current_resume(
    client: CdpClient,
    output_dir: Path,
    scan_id: str,
    index: int,
    max_pages: int,
    *,
    detail_wait_ms: int = 1200,
    scroll_delta: int = 620,
    scroll_wait_ms: int = 900,
) -> dict[str, Any] | None:
    point = client.evaluate(CLICK_RESUME_BUTTON_JS) or {}
    if not point.get("ok"):
        return None
    client.click(float(point["x"]), float(point["y"]))
    time.sleep(max(0, detail_wait_ms) / 1000)

    screenshot_dir = output_dir / "application-resume-screenshots" / scan_id
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    seen_keys = set()
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
            image_path = screenshot_dir / f"candidate-{index + 1:03d}-page-{page_number:02d}.png"
            image_path.write_bytes(client.capture_screenshot(clip))
            ocr = ocr_image(image_path, ["zh-Hans", "en-US"])
            pages.append({"page": page_number, "screenshot_path": str(image_path), "text": ocr.get("text", ""), "ocr_engine": ocr.get("engine"), "ocr_error": ocr.get("error")})
            if page_number >= max_pages or state.get("atBottom"):
                break

            scroll_result = client.evaluate(SCROLL_RESUME_FRAME_JS, scroll_delta) or {}
            if not scroll_result.get("moved"):
                wheel_x = float(state["x"] + state["width"] / 2)
                wheel_y = float(min(max(state["y"] + state["height"] * 0.75, 80), state["viewportHeight"] - 100))
                client.wheel(wheel_x, wheel_y, scroll_delta)
            time.sleep(max(0, scroll_wait_ms) / 1000)
        parsed = parse_resume_text(merge_ocr_pages([page.get("text", "") for page in pages]))
        if not parsed.get("resume_text"):
            return None
        return {
            **parsed,
            "source_platform": "boss_zhipin",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "ocr_engine": next((page.get("ocr_engine") for page in pages if page.get("ocr_engine")), None),
            "ocr_pages_json": [{"page": page["page"], "screenshot_path": page["screenshot_path"], "ocr_error": page.get("ocr_error")} for page in pages],
        }
    finally:
        client.press_escape()
        time.sleep(0.2)


def prepare_greeting(client: CdpClient, payload: dict[str, Any]) -> dict[str, Any]:
    first = client.evaluate(PREPARE_QUICK_REPLY_JS, payload) or {}
    if not first.get("ok"):
        return {"status": "needs_manual", "message": f"未能准备常用语：{first.get('reason') or 'unknown'}", **first}
    if first.get("needs_click"):
        client.click(float(first["x"]), float(first["y"]))
    time.sleep(0.5)
    selected = first
    if first.get("source") in {"quick_reply_pending", "quick_reply_button"}:
        selected = client.evaluate(SELECT_QUICK_REPLY_JS, int(payload.get("quick_reply_index") or 0)) or {}
        if not selected.get("ok"):
            return {"status": "needs_manual", "message": f"未能选择常用语：{selected.get('reason') or 'unknown'}", **selected}
        client.click(float(selected["x"]), float(selected["y"]))
        time.sleep(0.35)
    profile = client.evaluate(READ_PROFILE_JS) or {}
    input_text = selected.get("input_text") or profile.get("input_text") or ""
    return {
        "status": "confirmation_required",
        "message": "常用语已填入输入框，请确认后再发送。",
        "required_confirmation": True,
        "input_text": input_text,
        "selected_text": selected.get("selected_text"),
    }


def send_greeting(client: CdpClient, payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
    if not payload.get("confirm"):
        return {"status": "confirmation_required", "message": "发送消息需要 confirm=true。", "required_confirmation": True}
    profile = client.evaluate(READ_PROFILE_JS) or {}
    current_text = profile.get("input_text") or ""
    expected = payload.get("expected_text")
    if expected and normalize_text(expected) != normalize_text(current_text):
        return {"status": "confirmation_required", "message": "输入框内容和 expected_text 不一致，已停止发送。", "input_text": current_text, "required_confirmation": True}
    result = client.evaluate(SEND_MESSAGE_JS) or {}
    if not result.get("ok"):
        return {"status": "needs_manual", "message": f"发送失败：{result.get('reason') or 'unknown'}", **result}
    source_fingerprint = payload.get("source_fingerprint")
    if source_fingerprint:
        with talent_store.connect(db_path) as conn:
            talent_store.record_interaction(
                conn,
                source_fingerprint,
                "greeting_sent",
                "sent",
                job_title=payload.get("job_title"),
                message_text=result.get("input_text"),
                raw={"via": "quick_reply"},
            )
    return {"status": "sent", "message": "已发送常用语。", "input_text": result.get("input_text")}


def build_candidate(contact: dict[str, Any], profile: dict[str, Any], resume_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    header = profile.get("header_text") or ""
    body = profile.get("body_text") or ""
    card = parse_contact_card(contact.get("text") or "")
    resume_snapshot = resume_snapshot or {}
    candidate = {
        "source_platform": "boss_zhipin",
        "masked_name": first_match(header, r"^([^\s|]+)") or card.get("masked_name"),
        "age": parse_int(first_match(header + "\n" + body, r"(\d{2})岁")),
        "years_experience": first_match(header + "\n" + body, r"(\d+年(?:以上)?|经验不限|应届)"),
        "education_level": first_education(header + "\n" + body),
        "school": first_match(body, r"([\u4e00-\u9fa5A-Za-z]+(?:大学|学院|学校)[^\n|]*)"),
        "expected_city": first_match(body, r"期望[:：]?\s*([^\s|·]+)"),
        "expected_position": first_match(body, r"期望[:：]?.*?[|·]\s*([^|·\s]+)") or card.get("expected_position"),
        "expected_salary": first_match(body, r"\d{1,3}(?:-\d{1,3})?K(?:·\d{1,2}薪)?|面议"),
        "active_status": first_match(header + "\n" + body, r"在线|刚刚活跃|今日活跃|本周活跃") or card.get("active_status"),
        "short_summary": summarize(body or contact.get("text")),
        "source_url": profile.get("url"),
        "detail_summary": resume_snapshot.get("detail_summary"),
        "detail_tags_json": resume_snapshot.get("detail_tags_json", []),
        "detail_schools_json": resume_snapshot.get("detail_schools_json", []),
        "detail_companies_json": resume_snapshot.get("detail_companies_json", []),
        "detail_positions_json": resume_snapshot.get("detail_positions_json", []),
    }
    candidate["source_fingerprint"] = create_candidate_fingerprint(candidate)
    return candidate


def build_application(contact: dict[str, Any], profile: dict[str, Any], scan_id: str, job_filter: str | None) -> dict[str, Any]:
    card = parse_contact_card(contact.get("text") or "")
    application = {
        "scan_run_id": scan_id,
        "job_title": job_filter or card.get("expected_position"),
        "job_filter": job_filter,
        "candidate_name": card.get("masked_name"),
        "chat_status": "application_chat",
        "last_message": card.get("last_message"),
        "message_time": card.get("message_time"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "raw_contact": contact,
        "raw_profile_head": (profile.get("body_text") or "")[:1000],
    }
    application["application_key"] = talent_store.hash_text("|".join([application.get("job_title") or "", application.get("candidate_name") or "", application.get("last_message") or ""]))
    return application


def parse_contact_card(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(text or "").split("\n") if line.strip()]
    if lines and re.fullmatch(r"\d+", lines[0]):
        lines = lines[1:]
    message_time = None
    if lines and re.fullmatch(r"\d{1,2}:\d{2}|昨天|刚刚", lines[0]):
        message_time = lines[0]
        lines = lines[1:]
    first = lines[0] if lines else ""
    second = lines[1] if len(lines) > 1 else ""
    inline_name = first_match(first, r"^([^\s]+)")
    inline_position = first_match(first, r"\s([A-Za-z\u4e00-\u9fa5]+(?:工程师|开发|经理|顾问|运营|设计|产品|Java|AI))")
    if inline_position:
        last_message = lines[1] if len(lines) > 1 else None
    else:
        last_message = "\n".join(lines[2:]) if len(lines) > 2 else None
    return {
        "masked_name": inline_name,
        "expected_position": inline_position or second or None,
        "last_message": last_message,
        "message_time": message_time or first_match(text, r"\b\d{1,2}:\d{2}\b|昨天|刚刚"),
    }


def public_scan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"message_text"}}


def first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text or "")
    return match.group(1).strip() if match and match.groups() else match.group(0).strip() if match else None


def first_education(text: str) -> str | None:
    return next((item for item in ("博士", "硕士", "本科", "大专", "高中", "中专") if item in str(text or "")), None)


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize(text: str | None, limit: int = 220) -> str | None:
    cleaned = normalize_text(text)
    return cleaned[:limit] + "…" if len(cleaned) > limit else cleaned or None


def normalize_text(text: str | None) -> str:
    return " ".join(str(text or "").split())
