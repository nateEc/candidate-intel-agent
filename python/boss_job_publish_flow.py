from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boss_cdp_capture import CdpClient


JOB_LIST_URL = "https://www.zhipin.com/web/chat/job/list"
JOB_EDIT_URL = "https://www.zhipin.com/web/chat/job/edit?encryptId=0&enterSource=2"


READ_JOB_PUBLISH_STATE_JS = r"""
() => {
  const scope = getJobScope();
  const doc = scope.document;
  const text = normalize(doc.body ? doc.body.innerText : "");
  return {
    url: location.href,
    frame_url: scope.frameUrl,
    title: document.title,
    text,
    has_job_list: location.href.includes("/web/chat/job/list") || text.includes("职位管理"),
    has_publish_button: Boolean(findText("发布职位")),
    has_edit_form: location.href.includes("/web/chat/job/edit") || (text.includes("职位基本信息") && text.includes("职位要求")),
    has_basic_info: text.includes("职位基本信息"),
    has_requirements: text.includes("职位要求"),
    has_submit_button: Boolean(findText("发布") || findText("发布职位") || findText("确认发布"))
  };

  function findText(label) {
    return [...doc.querySelectorAll("button, a, span, div")]
      .filter(visible)
      .find((node) => normalize(node.textContent) === label) || null;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function getJobScope() {
    const frame = [...document.querySelectorAll("iframe")]
      .find((item) => item.src.includes("/web/frame/job/edit"));
    if (frame && frame.contentDocument) {
      const rect = frame.getBoundingClientRect();
      return {
        document: frame.contentDocument,
        window: frame.contentWindow,
        frameUrl: frame.src,
        offset: { x: rect.left, y: rect.top }
      };
    }
    return {
      document,
      window,
      frameUrl: "",
      offset: { x: 0, y: 0 }
    };
  }
}
"""


GET_CLICK_POINT_BY_TEXT_JS = r"""
(label) => {
  const scope = getJobScope();
  const doc = scope.document;
  const target = findText(label);
  if (!target) return { ok: false, reason: "text-target-missing", label };
  target.scrollIntoView({ block: "center", inline: "center" });
  const rect = target.getBoundingClientRect();
  return {
    ok: true,
    label,
    click: {
      x: scope.offset.x + rect.left + rect.width / 2,
      y: scope.offset.y + rect.top + rect.height / 2
    }
  };

  function findText(value) {
    const nodes = [...doc.querySelectorAll("button, a, span, div")].filter(visible);
    const exact = nodes.find((node) => normalize(node.textContent) === value);
    if (exact) return exact;
    return nodes.find((node) => {
      const text = normalize(node.textContent);
      return text.length <= 40 && text.includes(value);
    }) || null;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function getJobScope() {
    const frame = [...document.querySelectorAll("iframe")]
      .find((item) => item.src.includes("/web/frame/job/edit"));
    if (frame && frame.contentDocument) {
      const rect = frame.getBoundingClientRect();
      return {
        document: frame.contentDocument,
        window: frame.contentWindow,
        frameUrl: frame.src,
        offset: { x: rect.left, y: rect.top }
      };
    }
    return {
      document,
      window,
      frameUrl: "",
      offset: { x: 0, y: 0 }
    };
  }
}
"""


DISMISS_JOB_PUBLISH_TIP_JS = r"""
() => {
  const scopes = getScopes();
  for (const scope of scopes) {
    const dismissed = dismissInScope(scope);
    if (dismissed.dismissed || dismissed.modal_found) return dismissed;
  }
  return { dismissed: false, modal_found: false };

  function dismissInScope(scope) {
    const doc = scope.document;
    const modal = findDraftTipModal(scope);
    if (!modal) return { dismissed: false, modal_found: false };
    const close = findCloseButton(scope, modal);
    if (!close) {
      return {
        dismissed: false,
        modal_found: true,
        reason: "close-not-found",
        text: normalize(modal.textContent).slice(0, 120)
      };
    }
    close.scrollIntoView({ block: "center", inline: "center" });
    close.click();
    return {
      dismissed: true,
      modal_found: true,
      reason: "closed-draft-tip",
      text: normalize(modal.textContent).slice(0, 120)
    };

    function findDraftTipModal(scope) {
      const candidates = [...doc.querySelectorAll("div, section, article")]
        .filter((node) => visible(scope, node))
        .map((node) => {
          const rect = node.getBoundingClientRect();
          return { node, text: normalize(node.textContent), area: rect.width * rect.height };
        })
        .filter((item) => {
          return item.text.includes("温馨提示")
            && (item.text.includes("未发布的职位") || item.text.includes("继续上次的编辑"));
        })
        .sort((left, right) => left.area - right.area);
      return candidates.find((item) => {
        return [...item.node.querySelectorAll("button, a, i, span, div")]
          .some((node) => String(node.className || "").toLowerCase().includes("close"));
      })?.node || candidates[0]?.node || null;
    }

    function findCloseButton(scope, modal) {
      const nodes = [...modal.querySelectorAll("button, a, i, span, div")]
        .filter((node) => visible(scope, node))
        .map((node) => {
          const rect = node.getBoundingClientRect();
          const cls = String(node.className || "").toLowerCase();
          return { node, rect, cls, text: normalize(node.textContent), area: rect.width * rect.height };
        });
      const byClass = nodes.find((item) => item.cls.includes("close"));
      if (byClass) return byClass.node;
      const byText = nodes.find((item) => item.text === "×" || item.text.toLowerCase() === "x");
      if (byText) return byText.node;
      const modalRect = modal.getBoundingClientRect();
      return nodes
        .filter((item) => {
          return item.rect.width <= 44
            && item.rect.height <= 44
            && item.rect.top <= modalRect.top + 80
            && item.rect.left >= modalRect.left + modalRect.width * 0.6;
        })
        .sort((left, right) => {
          return right.rect.left - left.rect.left || left.rect.top - right.rect.top || left.area - right.area;
        })[0]?.node || null;
    }
  }

  function getScopes() {
    const scopes = [{ document, window, name: "top" }];
    for (const frame of [...document.querySelectorAll("iframe")]) {
      if (frame.contentDocument && frame.contentWindow) {
        scopes.push({ document: frame.contentDocument, window: frame.contentWindow, name: frame.src || "iframe" });
      }
    }
    return scopes;
  }

  function visible(scope, el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }
}
"""


GET_JOB_PUBLISH_SUBMIT_POINT_JS = r"""
() => {
  const scope = getJobScope();
  const doc = scope.document;
  const target = findSubmitButton();
  if (!target) return { ok: false, reason: "submit-button-not-found" };
  target.scrollIntoView({ block: "center", inline: "center" });
  const rect = target.getBoundingClientRect();
  return {
    ok: true,
    label: normalize(target.textContent),
    class_name: String(target.className || ""),
    click: {
      x: scope.offset.x + rect.left + rect.width / 2,
      y: scope.offset.y + rect.top + rect.height / 2
    }
  };

  function findSubmitButton() {
    const buttons = [
      ...doc.querySelectorAll("button.btn-sure-v2"),
      ...doc.querySelectorAll(".btn-publish button"),
      ...doc.querySelectorAll("button")
    ]
      .filter(visible)
      .filter((node) => !node.disabled && !node.getAttribute("disabled"))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { node, text: normalize(node.textContent), area: rect.width * rect.height };
      })
      .filter((item) => item.text === "发布")
      .sort((left, right) => {
        const leftInFooter = left.node.closest(".btn-publish, .form-btn") ? 0 : 1;
        const rightInFooter = right.node.closest(".btn-publish, .form-btn") ? 0 : 1;
        return leftInFooter - rightInFooter || left.area - right.area;
      });
    return buttons[0]?.node || null;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function getJobScope() {
    const frame = [...document.querySelectorAll("iframe")]
      .find((item) => item.src.includes("/web/frame/job/edit"));
    if (frame && frame.contentDocument) {
      const rect = frame.getBoundingClientRect();
      return {
        document: frame.contentDocument,
        window: frame.contentWindow,
        frameUrl: frame.src,
        offset: { x: rect.left, y: rect.top }
      };
    }
    return {
      document,
      window,
      frameUrl: "",
      offset: { x: 0, y: 0 }
    };
  }
}
"""


GET_JOB_PUBLISH_CONFIRM_POINT_JS = r"""
() => {
  const scopes = getScopes();
  for (const scope of scopes) {
    const target = findConfirmButton(scope);
    if (target) {
      target.scrollIntoView({ block: "center", inline: "center" });
      const rect = target.getBoundingClientRect();
      return {
        ok: true,
        label: normalize(target.textContent),
        click: {
          x: scope.offset.x + rect.left + rect.width / 2,
          y: scope.offset.y + rect.top + rect.height / 2
        }
      };
    }
  }
  return { ok: false, reason: "confirm-button-not-found" };

  function findConfirmButton(scope) {
    const labels = ["同意并继续发布职位", "确认发布", "继续发布", "确定"];
    const nodes = [...scope.document.querySelectorAll("button, a, span, div")]
      .filter((node) => visible(scope, node))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { node, text: normalize(node.textContent), area: rect.width * rect.height };
      })
      .filter((item) => labels.includes(item.text))
      .sort((left, right) => {
        const leftButtonish = isButtonish(left.node) ? 0 : 1;
        const rightButtonish = isButtonish(right.node) ? 0 : 1;
        return leftButtonish - rightButtonish || left.area - right.area;
      });
    return nodes[0]?.node || null;
  }

  function isButtonish(node) {
    const cls = String(node.className || "").toLowerCase();
    return node.tagName === "BUTTON" || cls.includes("button") || cls.includes("btn");
  }

  function getScopes() {
    const scopes = [{ document, window, offset: { x: 0, y: 0 } }];
    for (const frame of [...document.querySelectorAll("iframe")]) {
      if (frame.contentDocument && frame.contentWindow) {
        const rect = frame.getBoundingClientRect();
        scopes.push({
          document: frame.contentDocument,
          window: frame.contentWindow,
          offset: { x: rect.left, y: rect.top }
        });
      }
    }
    return scopes;
  }

  function visible(scope, el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }
}
"""


GET_JOB_CLOSE_POINT_JS = r"""
(payload) => {
  const jobTitle = normalize((payload && payload.job_title) || "");
  for (const scope of getScopes()) {
    const target = findCloseTarget(scope, jobTitle);
    if (target) {
      target.button.scrollIntoView({ block: "center", inline: "center" });
      const rect = target.button.getBoundingClientRect();
      return {
        ok: true,
        label: normalize(target.button.textContent),
        job_title: target.job_title,
        row_text: target.row_text,
        click: {
          x: scope.offset.x + rect.left + rect.width / 2,
          y: scope.offset.y + rect.top + rect.height / 2
        }
      };
    }
  }
  return {
    ok: false,
    reason: jobTitle ? "open-job-close-button-not-found-for-title" : "open-job-close-button-not-found",
    job_title: jobTitle
  };

  function findCloseTarget(scope, title) {
    const rows = findOpenJobRows(scope, title);
    for (const item of rows) {
      const button = findCloseButton(scope, item.node);
      if (button) {
        return {
          button,
          row_text: item.text,
          job_title: extractJobTitle(item.text)
        };
      }
    }
    return null;
  }

  function findOpenJobRows(scope, title) {
    const doc = scope.document;
    return [...doc.querySelectorAll("li, tr, article, section, div")]
      .filter((node) => visible(scope, node))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          node,
          rect,
          text: normalize(node.textContent),
          area: rect.width * rect.height,
          depth: getDepth(node)
        };
      })
      .filter((item) => {
        if (!item.text.includes("开放中")) return false;
        if (!item.text.includes("关闭")) return false;
        if (item.text.includes("已关闭") && !item.text.includes("开放中")) return false;
        if (title && !item.text.includes(title)) return false;
        if (item.rect.width < 240 || item.rect.height < 40) return false;
        if (item.rect.height > Math.max(260, scope.window.innerHeight * 0.4)) return false;
        if (item.rect.width > scope.window.innerWidth * 0.96 && item.rect.height > 180) return false;
        return Boolean(findCloseButton(scope, item.node));
      })
      .sort((left, right) => {
        const leftExact = title && extractJobTitle(left.text) === title ? 0 : 1;
        const rightExact = title && extractJobTitle(right.text) === title ? 0 : 1;
        return leftExact - rightExact || left.area - right.area || right.depth - left.depth;
      });
  }

  function findCloseButton(scope, row) {
    const nodes = [...row.querySelectorAll("button, a, span, div")]
      .filter((node) => visible(scope, node))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          node,
          rect,
          text: normalize(node.textContent),
          cls: String(node.className || "").toLowerCase(),
          area: rect.width * rect.height
        };
      })
      .filter((item) => {
        if (item.text !== "关闭") return false;
        if (item.rect.width > 90 || item.rect.height > 60) return false;
        return true;
      })
      .sort((left, right) => {
        const leftButtonish = isButtonish(left.node) ? 0 : 1;
        const rightButtonish = isButtonish(right.node) ? 0 : 1;
        return leftButtonish - rightButtonish || right.rect.left - left.rect.left || left.area - right.area;
      });
    return nodes[0]?.node || null;
  }

  function extractJobTitle(text) {
    const clean = normalize(text);
    const beforeStatus = clean.split("开放中")[0] || clean;
    return normalize(beforeStatus.split(/\s+/)[0] || "");
  }

  function isButtonish(node) {
    const cls = String(node.className || "").toLowerCase();
    return node.tagName === "BUTTON" || cls.includes("button") || cls.includes("btn") || node.tagName === "A";
  }

  function getScopes() {
    const scopes = [{ document, window, offset: { x: 0, y: 0 } }];
    for (const frame of [...document.querySelectorAll("iframe")]) {
      if (frame.contentDocument && frame.contentWindow) {
        const rect = frame.getBoundingClientRect();
        scopes.push({
          document: frame.contentDocument,
          window: frame.contentWindow,
          offset: { x: rect.left, y: rect.top }
        });
      }
    }
    return scopes;
  }

  function getDepth(node) {
    let depth = 0;
    while (node && node.parentElement) {
      depth += 1;
      node = node.parentElement;
    }
    return depth;
  }

  function visible(scope, el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }
}
"""


GET_JOB_CLOSE_CONFIRM_POINT_JS = r"""
() => {
  for (const scope of getScopes()) {
    const target = findConfirmButton(scope);
    if (target) {
      target.scrollIntoView({ block: "center", inline: "center" });
      const rect = target.getBoundingClientRect();
      return {
        ok: true,
        label: normalize(target.textContent),
        click: {
          x: scope.offset.x + rect.left + rect.width / 2,
          y: scope.offset.y + rect.top + rect.height / 2
        }
      };
    }
  }
  return { ok: false, reason: "close-confirm-button-not-found" };

  function findConfirmButton(scope) {
    const modal = findCloseModal(scope);
    if (!modal) return null;
    const nodes = [...modal.querySelectorAll("button, a, span, div")]
      .filter((node) => visible(scope, node))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          node,
          text: normalize(node.textContent),
          cls: String(node.className || "").toLowerCase(),
          area: rect.width * rect.height
        };
      })
      .filter((item) => item.text === "关闭职位")
      .sort((left, right) => {
        const leftButtonish = isButtonish(left.node) ? 0 : 1;
        const rightButtonish = isButtonish(right.node) ? 0 : 1;
        return leftButtonish - rightButtonish || left.area - right.area;
      });
    return nodes[0]?.node || null;
  }

  function findCloseModal(scope) {
    return [...scope.document.querySelectorAll("div, section, article")]
      .filter((node) => visible(scope, node))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { node, text: normalize(node.textContent), area: rect.width * rect.height };
      })
      .filter((item) => {
        return item.text.includes("温馨提示")
          && item.text.includes("关闭职位")
          && (item.text.includes("暂不关闭") || item.text.includes("无法看到推荐牛人") || item.text.includes("关闭后"));
      })
      .sort((left, right) => left.area - right.area)[0]?.node || null;
  }

  function isButtonish(node) {
    const cls = String(node.className || "").toLowerCase();
    return node.tagName === "BUTTON" || cls.includes("button") || cls.includes("btn") || node.tagName === "A";
  }

  function getScopes() {
    const scopes = [{ document, window, offset: { x: 0, y: 0 } }];
    for (const frame of [...document.querySelectorAll("iframe")]) {
      if (frame.contentDocument && frame.contentWindow) {
        const rect = frame.getBoundingClientRect();
        scopes.push({
          document: frame.contentDocument,
          window: frame.contentWindow,
          offset: { x: rect.left, y: rect.top }
        });
      }
    }
    return scopes;
  }

  function visible(scope, el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }
}
"""


FILL_JOB_PUBLISH_DRAFT_JS = r"""
async (payload) => {
  const scope = getJobScope();
  const doc = scope.document;
  const actions = [];
  const missing = [];

  await clickChoice(payload.recruitment_type || "社招全职", "recruitment_type");
  await setField("职位名称", payload.job_title, "job_title");
  await setField("职位描述", payload.job_description, "job_description");
  await clickChoice(payload.overseas_status || "境内岗位", "overseas_status");
  if (payload.job_type) {
    await selectDropdown("职位类型", payload.job_type, "job_type");
  }
  if (payload.experience) {
    await selectDropdown("经验", payload.experience, "experience");
  }
  if (payload.education) {
    await selectDropdown("学历", payload.education, "education");
  }
  if (payload.salary_min_k) {
    await selectDropdown("薪资范围", salaryLabel(payload.salary_min_k), "salary_min_k", { allowPrefix: true });
    await fillSalaryTail(payload.salary_max_k, payload.salary_months);
  }
  if (Array.isArray(payload.keywords)) {
    await fillKeywords(payload.keywords);
  }
  await dismissJobCategoryDialog();

  return {
    ok: missing.length === 0,
    status: missing.length === 0 ? "job_publish_draft_filled" : "needs_manual",
    message: missing.length === 0
      ? "岗位发布草稿已填写，请让用户确认后再发布。"
      : "岗位发布草稿部分字段未能自动填写，请查看页面。",
    actions,
    missing,
    current_url: location.href
  };

  async function setField(label, value, actionName) {
    if (!value) return;
    const control = findControlByLabel(label);
    if (!control) {
      missing.push({ field: actionName, label, reason: "control-not-found" });
      return;
    }
    nativeSetValue(control, value);
    actions.push({ action: "set_field", field: actionName, label });
    await pause();
  }

  async function clickChoice(label, actionName) {
    if (!label) return;
    const target = findText(label);
    if (!target) {
      missing.push({ field: actionName, label, reason: "choice-not-found" });
      return;
    }
    target.scrollIntoView({ block: "center", inline: "center" });
    target.click();
    actions.push({ action: "click_choice", field: actionName, label });
    await pause();
  }

  async function selectDropdown(label, value, actionName, options = {}) {
    if (!value) return;
    if (actionName === "job_type" && setJobCategoryByVue(value)) {
      actions.push({ action: "set_job_category", field: actionName, value, method: "vue-state" });
      await dismissJobCategoryDialog();
      await pause(300);
      return;
    }
    const row = findFormRow(label);
    const opener = findDropdownOpenerByLabel(label, options.controlIndex || 0) || findControlByLabel(label) || findText(label);
    if (!opener) {
      missing.push({ field: actionName, label, reason: "dropdown-not-found" });
      return;
    }
    await clickElement(opener);
    actions.push({ action: "open_dropdown", field: actionName, label, control_index: options.controlIndex || 0 });
    await pause(500);
    const option = findOption(value, { ...options, row });
    if (!option) {
      if (actionName === "job_type" && setJobCategoryByVue(value)) {
        actions.push({ action: "set_job_category", field: actionName, value, method: "vue-state" });
        await dismissJobCategoryDialog();
        await pause(300);
        return;
      }
      missing.push({ field: actionName, label, value, reason: "option-not-found" });
      return;
    }
    await clickElement(option);
    actions.push({ action: "select_option", field: actionName, value: normalize(option.textContent) });
    await pause(400);
  }

  async function fillSalaryTail(maxK, months) {
    if (maxK) {
      await selectDropdown("薪资范围", salaryLabel(maxK), "salary_max_k", { allowPrefix: true, controlIndex: 1 });
    }
    if (months) {
      await selectDropdown("薪资范围", salaryMonthLabel(months), "salary_months", { allowPrefix: true, controlIndex: 2 });
    }
    await pause();
  }

  async function fillKeywords(keywords) {
    const cleanKeywords = keywords.map((item) => normalize(item)).filter(Boolean).slice(0, 8);
    if (!cleanKeywords.length) return;
    const addButton = findText("+") || findText("职位关键词");
    if (!addButton) {
      missing.push({ field: "keywords", label: "职位关键词", reason: "add-button-not-found" });
      return;
    }
    actions.push({ action: "skip_keywords", count: cleanKeywords.length, reason: "keyword-widget-requires-interactive-confirmation" });
  }

  function findControlByLabel(label) {
    const controls = controlsNearLabel(label);
    return controls.find((item) => ["INPUT", "TEXTAREA"].includes(item.tagName))
      || controls.find((item) => item.getAttribute("contenteditable") === "true")
      || controls[0]
      || null;
  }

  function findDropdownOpenerByLabel(label, index = 0) {
    const row = findFormRow(label);
    if (!row) return null;
    const candidates = uniqueElements([
      ...row.querySelectorAll(".ui-select-selection"),
      ...row.querySelectorAll(".ui-select-inner"),
      ...row.querySelectorAll("input[readonly]"),
      ...row.querySelectorAll(".ipt-wrap"),
    ])
      .filter(visible)
      .filter((node) => {
        const rect = node.getBoundingClientRect();
        if (node.tagName === "INPUT") return true;
        if (String(node.className).includes("ui-select")) return true;
        if (String(node.className).includes("ipt-wrap")) return Boolean(node.querySelector("input[readonly]"));
        return rect.width >= 40 && rect.height >= 20;
      })
      .sort(compareByPosition);
    return candidates[index] || null;
  }

  function controlsNearLabel(label) {
    const row = findFormRow(label);
    if (row) {
      const rowControls = [...row.querySelectorAll("input, textarea, [contenteditable='true'], button, a, span, div")]
        .filter(visible)
        .filter((node) => {
          if (normalize(node.textContent) === label) return false;
          if (node.closest(".title")) return false;
          if (node.closest(".error-tip")) return false;
          const rect = node.getBoundingClientRect();
          if (["INPUT", "TEXTAREA"].includes(node.tagName)) return true;
          if (node.getAttribute("contenteditable") === "true") return true;
          if (String(node.className).includes("ui-select-selection")) return true;
          if (String(node.className).includes("ui-select-inner")) return true;
          if (String(node.className).includes("ipt-wrap")) return Boolean(node.querySelector("input, textarea"));
          return rect.width >= 40 && rect.height >= 20 && rect.width <= 560 && rect.height <= 220;
        })
        .sort(compareByPosition);
      if (rowControls.length) return uniqueElements(rowControls);
    }

    const labelNode = findText(label);
    if (!labelNode) return [];
    const labelRect = labelNode.getBoundingClientRect();
    return [...doc.querySelectorAll("input, textarea, [contenteditable='true'], button, a, span, div")]
      .filter(visible)
      .filter((node) => {
        if (node === labelNode || labelNode.contains(node)) return false;
        const rect = node.getBoundingClientRect();
        const sameRow = Math.abs((rect.top + rect.height / 2) - (labelRect.top + labelRect.height / 2)) < 34;
        const toRight = rect.left > labelRect.left;
        const usefulSize = rect.width > 40 && rect.height > 20;
        return sameRow && toRight && usefulSize;
      })
      .sort(compareByPosition);
  }

  function findFormRow(label) {
    const value = normalize(label);
    const exactLabel = [...doc.querySelectorAll(".title, label, span, div")]
      .filter(visible)
      .find((node) => normalize(node.textContent) === value);
    let node = exactLabel || findText(label);
    while (node && node !== doc.body) {
      if (String(node.className || "").includes("form-row")) return node;
      node = node.parentElement;
    }
    return [...doc.querySelectorAll(".form-row")]
      .filter(visible)
      .find((row) => normalize(row.textContent).includes(value)) || null;
  }

  function findText(label) {
    const value = normalize(label);
    const nodes = [...doc.querySelectorAll("button, a, span, div, label, li, p")]
      .filter(visible)
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { node, text: normalize(node.textContent), area: rect.width * rect.height };
      })
      .filter((item) => item.text.length <= Math.max(100, value.length + 30))
      .sort((left, right) => left.area - right.area);
    return (nodes.find((item) => item.text === value)
      || nodes.find((item) => item.text.includes(value))
      || {}).node
      || null;
  }

  function findOption(value, options = {}) {
    const normalizedValue = normalize(value).toLowerCase();
    const roots = options.row ? [options.row, doc] : [doc];
    const nodes = uniqueElements(roots.flatMap((root) => [...root.querySelectorAll("li, button, a, span, div")]))
      .filter(visible)
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { node, text: normalize(node.textContent), area: rect.width * rect.height };
      })
      .filter((item) => {
        const { text, node } = item;
        if (String(node.className).includes("ui-select-dropdown") || String(node.className).includes("ui-dropdown-list")) return false;
        return text.length > 0 && text.length <= 80;
      })
      .sort((left, right) => {
        const leftIsItem = String(left.node.className).includes("ui-select-item") ? 0 : 1;
        const rightIsItem = String(right.node.className).includes("ui-select-item") ? 0 : 1;
        return leftIsItem - rightIsItem || left.area - right.area;
      });
    const exact = nodes.find((item) => item.text.toLowerCase() === normalizedValue);
    if (exact) return exact.node;
    if (options.allowPrefix) {
      const prefix = nodes.find((item) => item.text.toLowerCase().startsWith(normalizedValue));
      if (prefix) return prefix.node;
    }
    return (nodes.find((item) => item.text.toLowerCase().includes(normalizedValue)) || {}).node || null;
  }

  function nativeSetValue(control, value) {
    if (control.getAttribute("contenteditable") === "true") {
      control.focus();
      control.textContent = value;
      control.dispatchEvent(new scope.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      control.dispatchEvent(new scope.window.Event("change", { bubbles: true }));
      return;
    }
    const proto = control.tagName === "TEXTAREA" ? scope.window.HTMLTextAreaElement.prototype : scope.window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    try {
      setter.call(control, value);
    } catch (error) {
      control.value = value;
    }
    control.dispatchEvent(new scope.window.Event("input", { bubbles: true }));
    control.dispatchEvent(new scope.window.Event("change", { bubbles: true }));
    control.dispatchEvent(new scope.window.KeyboardEvent("keyup", { bubbles: true }));
  }

  function salaryLabel(value) {
    const text = normalize(value);
    return /k$/i.test(text) ? text.toUpperCase() : `${text}K`;
  }

  function salaryMonthLabel(value) {
    const text = normalize(value);
    if (text.endsWith("个月")) return text;
    if (text.endsWith("薪")) return `${text.slice(0, -1)}个月`;
    return `${text}个月`;
  }

  async function clickElement(element) {
    element.scrollIntoView({ block: "center", inline: "center" });
    await pause(80);
    element.click();
  }

  function compareByPosition(left, right) {
    const leftRect = left.getBoundingClientRect();
    const rightRect = right.getBoundingClientRect();
    return leftRect.top - rightRect.top || leftRect.left - rightRect.left;
  }

  function uniqueElements(values) {
    return values.filter((value, index) => value && values.indexOf(value) === index);
  }

  function setJobCategoryByVue(value) {
    const row = doc.querySelector(".job-category-container");
    const vm = row && row.__vue__;
    if (!vm) return false;
    const found = findCategoryByName(vm.originData || [], value);
    if (!found) return false;
    if (typeof vm.updateJobCategory === "function") {
      vm.updateJobCategory(found);
    } else if (vm.formData$) {
      vm.formData$.position = found.code;
      vm.formData$.positionCategory = found.name;
    } else {
      return false;
    }
    const input = row.querySelector("input[name='jobCategory']");
    if (input) nativeSetValue(input, found.name);
    return Boolean(!vm.formData$ || vm.formData$.position === found.code || vm.formData$.positionCategory === found.name);
  }

  async function dismissJobCategoryDialog() {
    const dialog = findJobCategoryDialog();
    if (!dialog) return false;
    const close = findDialogClose(dialog);
    if (!close) return false;
    await clickElement(close);
    actions.push({ action: "dismiss_dialog", field: "job_type", label: "请选择职类" });
    await pause(200);
    return true;
  }

  function findJobCategoryDialog() {
    const candidates = [...doc.querySelectorAll("div, section, article")]
      .filter(visible)
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { node, text: normalize(node.textContent), area: rect.width * rect.height };
      })
      .filter((item) => {
        return item.text.includes("请选择职类")
          || item.text.includes("请选择职位类型")
          || (item.text.includes("请输入职位名称") && item.text.includes("后端开发"));
      })
      .sort((left, right) => {
        const leftHasClose = hasCloseNode(left.node) ? 0 : 1;
        const rightHasClose = hasCloseNode(right.node) ? 0 : 1;
        return leftHasClose - rightHasClose || left.area - right.area;
      });
    return candidates.find((item) => hasCloseNode(item.node))?.node || null;
  }

  function findDialogClose(dialog) {
    const nodes = [...dialog.querySelectorAll("button, a, i, span, div")]
      .filter(visible)
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { node, rect, text: normalize(node.textContent), cls: String(node.className || "").toLowerCase(), area: rect.width * rect.height };
      });
    const byClass = nodes.find((item) => item.cls.includes("close"));
    if (byClass) return byClass.node;
    const byText = nodes.find((item) => item.text === "×" || item.text.toLowerCase() === "x");
    if (byText) return byText.node;
    const dialogRect = dialog.getBoundingClientRect();
    return nodes
      .filter((item) => item.rect.width <= 48 && item.rect.height <= 48 && item.rect.top <= dialogRect.top + 80 && item.rect.left >= dialogRect.left + dialogRect.width * 0.7)
      .sort((left, right) => right.rect.left - left.rect.left || left.rect.top - right.rect.top || left.area - right.area)[0]?.node || null;
  }

  function hasCloseNode(node) {
    return [...node.querySelectorAll("button, a, i, span, div")]
      .some((item) => String(item.className || "").toLowerCase().includes("close") || normalize(item.textContent) === "×");
  }

  function findCategoryByName(items, value) {
    const target = normalize(value).toLowerCase();
    for (const item of items || []) {
      if (normalize(item.name).toLowerCase() === target) return item;
      const child = findCategoryByName(item.subLevelModelList || [], value);
      if (child) return child;
    }
    return null;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = scope.window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function pause(ms = 200) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function getJobScope() {
    const frame = [...document.querySelectorAll("iframe")]
      .find((item) => item.src.includes("/web/frame/job/edit"));
    if (frame && frame.contentDocument) {
      const rect = frame.getBoundingClientRect();
      return {
        document: frame.contentDocument,
        window: frame.contentWindow,
        frameUrl: frame.src,
        offset: { x: rect.left, y: rect.top }
      };
    }
    return {
      document,
      window,
      frameUrl: "",
      offset: { x: 0, y: 0 }
    };
  }
}
"""


def response(status: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "message": message}
    payload.update(extra)
    return payload


def read_job_publish_state(client: CdpClient) -> dict[str, Any]:
    snapshot = client.evaluate(READ_JOB_PUBLISH_STATE_JS) or {}
    if snapshot.get("has_edit_form"):
        return response(
            "job_publish_form_ready",
            "岗位发布表单已打开。",
            current_url=snapshot.get("url"),
            page_title=snapshot.get("title"),
        )
    if snapshot.get("has_job_list"):
        return response(
            "job_list_ready",
            "职位管理列表已打开。",
            current_url=snapshot.get("url"),
            page_title=snapshot.get("title"),
            has_publish_button=snapshot.get("has_publish_button"),
        )
    return response(
        "needs_manual",
        "未能识别当前岗位发布页面，请查看浏览器。",
        current_url=snapshot.get("url"),
        page_title=snapshot.get("title"),
    )


def dismiss_job_publish_tip(client: CdpClient) -> dict[str, Any]:
    return client.evaluate(DISMISS_JOB_PUBLISH_TIP_JS) or {}


def wait_for_job_publish_form(client: CdpClient, deadline: float) -> dict[str, Any]:
    state = read_job_publish_state(client)
    while time.time() < deadline:
        if state["status"] == "job_publish_form_ready":
            dismiss_job_publish_tip(client)
            return state
        time.sleep(0.5)
        state = read_job_publish_state(client)
    if state["status"] == "job_publish_form_ready":
        dismiss_job_publish_tip(client)
    return state


def start_job_publish(client: CdpClient) -> dict[str, Any]:
    client.evaluate("(url) => { location.href = url; return { ok: true }; }", JOB_LIST_URL)
    time.sleep(1)
    click_result = client.evaluate(GET_CLICK_POINT_BY_TEXT_JS, "发布职位") or {}
    if not click_result.get("ok"):
        client.evaluate("(url) => { location.href = url; return { ok: true }; }", JOB_EDIT_URL)
        time.sleep(1)
        return wait_for_job_publish_form(client, time.time() + 8)

    click_point = click_result.get("click") or {}
    try:
        client.click(float(click_point["x"]), float(click_point["y"]))
    except (KeyError, TypeError, ValueError):
        return response("needs_manual", "未能定位“发布职位”按钮，请查看浏览器。")

    return wait_for_job_publish_form(client, time.time() + 8)


def fill_job_publish_draft(client: CdpClient, payload: dict[str, Any]) -> dict[str, Any]:
    state = read_job_publish_state(client)
    if state["status"] != "job_publish_form_ready":
        started = start_job_publish(client)
        if started["status"] != "job_publish_form_ready":
            return started
    dismiss_job_publish_tip(client)
    result = client.evaluate(FILL_JOB_PUBLISH_DRAFT_JS, payload) or {}
    status = str(result.get("status") or "needs_manual")
    message = str(result.get("message") or "岗位发布草稿填写完成状态未知。")
    return response(
        status,
        message,
        actions=result.get("actions") or [],
        missing=result.get("missing") or [],
        current_url=result.get("current_url"),
        requires_confirmation=True,
    )


def submit_job_publish(client: CdpClient, confirm: bool) -> dict[str, Any]:
    if not confirm:
        return response(
            "confirmation_required",
            "发布职位是高影响操作。请明确确认后再发布。",
            required_confirmation=True,
        )
    state = read_job_publish_state(client)
    if state["status"] != "job_publish_form_ready":
        return state
    dismiss_job_publish_tip(client)
    click_result = client.evaluate(GET_JOB_PUBLISH_SUBMIT_POINT_JS) or {}
    if not click_result.get("ok"):
        return response(
            "needs_manual",
            "未能定位底部真实发布按钮，请查看浏览器。",
            reason=click_result.get("reason"),
        )

    click_point = click_result.get("click") or {}
    try:
        client.click(float(click_point["x"]), float(click_point["y"]))
    except (KeyError, TypeError, ValueError):
        return response("needs_manual", "未能点击底部发布按钮，请查看浏览器。")

    time.sleep(1)
    confirm_result = client.evaluate(GET_JOB_PUBLISH_CONFIRM_POINT_JS) or {}
    if confirm_result.get("ok"):
        confirm_point = confirm_result.get("click") or {}
        try:
            client.click(float(confirm_point["x"]), float(confirm_point["y"]))
        except (KeyError, TypeError, ValueError):
            return response(
                "needs_manual",
                "已点击发布按钮，但未能点击二次确认，请查看浏览器。",
                clicked_label=click_result.get("label"),
                confirm_label=confirm_result.get("label"),
            )
        time.sleep(1.5)
    else:
        time.sleep(1)

    snapshot = client.evaluate(READ_JOB_PUBLISH_STATE_JS) or {}
    text = str(snapshot.get("text") or "")
    current_url = snapshot.get("url")
    if not snapshot.get("has_edit_form") or "发布成功" in text or "职位管理" in text:
        return response(
            "job_publish_submitted",
            "岗位发布请求已提交，请在 BOSS 页面确认发布结果。",
            clicked_label=click_result.get("label"),
            confirm_label=confirm_result.get("label") if confirm_result.get("ok") else None,
            current_url=current_url,
        )
    return response(
        "needs_manual",
        "已点击底部发布按钮，但页面仍停留在岗位编辑页，可能还有校验错误或平台二次确认，请查看浏览器。",
        clicked_label=click_result.get("label"),
        confirm_label=confirm_result.get("label") if confirm_result.get("ok") else None,
        current_url=current_url,
    )


def close_job(client: CdpClient, payload: dict[str, Any]) -> dict[str, Any]:
    confirm = bool(payload.get("confirm"))
    job_title = str(payload.get("job_title") or "").strip()
    if not confirm:
        return response(
            "confirmation_required",
            "关闭职位是高影响操作。请明确确认后再关闭。",
            required_confirmation=True,
            job_title=job_title or None,
        )

    client.evaluate("(url) => { location.href = url; return { ok: true }; }", JOB_LIST_URL)
    time.sleep(1)

    click_result = client.evaluate(GET_JOB_CLOSE_POINT_JS, {"job_title": job_title}) or {}
    if not click_result.get("ok"):
        return response(
            "needs_manual",
            "未能定位开放中职位的“关闭”按钮，请查看职位管理页面。",
            reason=click_result.get("reason"),
            job_title=job_title or None,
            current_url=read_job_publish_state(client).get("current_url"),
        )

    click_point = click_result.get("click") or {}
    try:
        client.click(float(click_point["x"]), float(click_point["y"]))
    except (KeyError, TypeError, ValueError):
        return response(
            "needs_manual",
            "未能点击职位行里的“关闭”按钮，请查看职位管理页面。",
            job_title=click_result.get("job_title") or job_title or None,
        )

    time.sleep(0.8)
    confirm_result = client.evaluate(GET_JOB_CLOSE_CONFIRM_POINT_JS) or {}
    if not confirm_result.get("ok"):
        return response(
            "needs_manual",
            "已点击“关闭”，但未能定位二次确认里的“关闭职位”按钮，请查看浏览器。",
            reason=confirm_result.get("reason"),
            job_title=click_result.get("job_title") or job_title or None,
            row_text=click_result.get("row_text"),
        )

    confirm_point = confirm_result.get("click") or {}
    try:
        client.click(float(confirm_point["x"]), float(confirm_point["y"]))
    except (KeyError, TypeError, ValueError):
        return response(
            "needs_manual",
            "已打开关闭确认框，但未能点击“关闭职位”，请查看浏览器。",
            job_title=click_result.get("job_title") or job_title or None,
            confirm_label=confirm_result.get("label"),
        )

    time.sleep(1.5)
    closed_title = str(click_result.get("job_title") or job_title or "").strip()
    verification = client.evaluate(GET_JOB_CLOSE_POINT_JS, {"job_title": closed_title}) or {}
    if not verification.get("ok"):
        state = read_job_publish_state(client)
        return response(
            "job_closed",
            "已关闭职位。",
            job_title=closed_title or None,
            clicked_label=click_result.get("label"),
            confirm_label=confirm_result.get("label"),
            current_url=state.get("current_url"),
        )

    return response(
        "needs_manual",
        "已点击“关闭职位”，但页面上仍能识别到同名开放职位，请查看 BOSS 页面确认结果。",
        job_title=closed_title or None,
        clicked_label=click_result.get("label"),
        confirm_label=confirm_result.get("label"),
        current_url=read_job_publish_state(client).get("current_url"),
    )
