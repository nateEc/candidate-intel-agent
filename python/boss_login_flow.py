from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boss_cdp_capture import CdpClient


LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"
TALENT_SEARCH_URL = "https://www.zhipin.com/web/chat/search"


READ_LOGIN_STATE_JS = r"""
() => {
  const text = normalize(document.body ? document.body.innerText : "");
  const inputs = [...document.querySelectorAll("input")].filter(visible);
  const phoneInput = inputs.find((item) => /手机|phone|tel/i.test(inputName(item))) || inputs[0] || null;
  const smsInput = inputs.find((item) => /验证码|code/i.test(inputName(item))) || inputs[1] || null;
  const sendButton = findSendCodeButton();
  const sendButtonText = sendButton ? normalize(sendButton.textContent) : "";
  return {
    url: location.href,
    title: document.title,
    text,
    phone_value: phoneInput ? phoneInput.value : "",
    sms_value: smsInput ? smsInput.value : "",
    send_button_text: sendButtonText,
    sms_sent: isSmsSent(sendButtonText),
    has_recruiter_tab: text.includes("我要招聘"),
    has_jobseeker_tab: text.includes("我要找工作"),
    has_switch_dialog: text.includes("是否将身份切为招聘者"),
    has_slider_captcha: hasSliderCaptcha(text),
    has_safety_verify: text.includes("安全验证") || text.includes("请在手机上打开BOSS直聘"),
    has_login_form: text.includes("验证码登录/注册") || text.includes("短信验证码") || Boolean(sendButton)
  };

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function inputName(el) {
    return [el.placeholder, el.name, el.type, el.getAttribute("aria-label")].filter(Boolean).join(" ");
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function area(el) {
    const rect = el.getBoundingClientRect();
    return rect.width * rect.height;
  }

  function findSendCodeButton() {
    const candidates = [...document.querySelectorAll("button, a, span, div")]
      .filter(visible)
      .filter((node) => {
        const nodeText = normalize(node.textContent);
        return nodeText.length <= 32 && /发送验证码|获取验证码|重新发送|已发送|发送\s*\d+\s*s|发送\s*\d+秒|\d+\s*s|\d+秒/.test(nodeText);
      });
    candidates.sort((left, right) => area(left) - area(right));
    return candidates[0] || null;
  }

  function isSmsSent(value) {
    return /重新发送|已发送|发送\s*\d+\s*s|发送\s*\d+秒|\d+\s*s|\d+秒/.test(normalize(value));
  }

  function hasSliderCaptcha(value) {
    return value.includes("向右拖动滑块") || value.includes("拖动滑块填充拼图") || value.includes("完成拼图");
  }
}
"""


CLICK_RECRUITER_TAB_JS = r"""
() => {
  const target = findByText("我要招聘");
  if (!target) return { ok: false, reason: "recruiter-tab-missing" };
  target.scrollIntoView({ block: "center", inline: "center" });
  const rect = target.getBoundingClientRect();
  return {
    ok: true,
    reason: "",
    click: {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    }
  };

  function findByText(label) {
    const nodes = [...document.querySelectorAll("button, a, span, div, li")].filter(visible);
    return nodes.find((node) => normalize(node.textContent) === label) || null;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }
}
"""


SEND_CODE_JS = r"""
(phone) => {
  const inputs = [...document.querySelectorAll("input")].filter(visible);
  const phoneInput = inputs.find((item) => /手机|phone|tel/i.test(inputName(item))) || inputs[0];
  if (!phoneInput) return { ok: false, reason: "phone-input-missing" };
  nativeSetValue(phoneInput, phone);
  clickAgreement();
  const sendButton = findSendCodeButton();
  if (!sendButton) return { ok: false, reason: "send-code-button-missing" };
  sendButton.scrollIntoView({ block: "center", inline: "center" });
  const rect = sendButton.getBoundingClientRect();
  return {
    ok: true,
    reason: "",
    button_text: normalize(sendButton.textContent),
    click: {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    }
  };

  function nativeSetValue(input, value) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function clickAgreement() {
    const checkbox = [...document.querySelectorAll("input[type='checkbox']")].find((item) => !item.checked);
    if (checkbox) {
      checkbox.click();
      return true;
    }
    const textNode = [...document.querySelectorAll("span, label, div")].find((item) => {
      const text = normalize(item.textContent);
      return text.includes("已阅读并同意") || text.includes("用户协议");
    });
    if (textNode) {
      textNode.click();
      return true;
    }
    return false;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function inputName(el) {
    return [el.placeholder, el.name, el.type, el.getAttribute("aria-label")].filter(Boolean).join(" ");
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function area(el) {
    const rect = el.getBoundingClientRect();
    return rect.width * rect.height;
  }

  function findSendCodeButton() {
    const candidates = [...document.querySelectorAll("button, a, span, div")]
      .filter(visible)
      .filter((node) => {
        const nodeText = normalize(node.textContent);
        return nodeText.length <= 32 && /发送验证码|获取验证码/.test(nodeText);
      });
    candidates.sort((left, right) => area(left) - area(right));
    return candidates[0] || null;
  }
}
"""


SUBMIT_CODE_JS = r"""
(smsCode) => {
  const inputs = [...document.querySelectorAll("input")].filter(visible);
  const smsInput = inputs.find((item) => /验证码|code/i.test(inputName(item))) || inputs[1];
  if (!smsInput) return { ok: false, reason: "sms-input-missing" };
  nativeSetValue(smsInput, smsCode);
  smsInput.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter" }));
  const submitButton = findSubmitButton();
  if (!submitButton) return { ok: false, reason: "login-button-missing" };
  submitButton.scrollIntoView({ block: "center", inline: "center" });
  const rect = submitButton.getBoundingClientRect();
  return {
    ok: true,
    reason: "",
    button_text: normalize(submitButton.textContent),
    click: {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    }
  };

  function nativeSetValue(input, value) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function inputName(el) {
    return [el.placeholder, el.name, el.type, el.getAttribute("aria-label")].filter(Boolean).join(" ");
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function area(el) {
    const rect = el.getBoundingClientRect();
    return rect.width * rect.height;
  }

  function findSubmitButton() {
    const candidates = [...document.querySelectorAll("button, a, span, div")]
      .filter(visible)
      .filter((node) => {
        const nodeText = normalize(node.textContent);
        return ["登录/注册", "登录", "注册"].includes(nodeText);
      });
    candidates.sort((left, right) => area(right) - area(left));
    return candidates[0] || null;
  }
}
"""


CLICK_SWITCH_TO_RECRUITER_JS = r"""
() => {
  if (!(document.body && document.body.innerText.includes("是否将身份切为招聘者"))) {
    return { visible: false, clicked: false };
  }
  const nodes = [...document.querySelectorAll("button, a, span, div")].filter(visible);
  const target = nodes.find((node) => normalize(node.textContent) === "切换");
  if (!target) return { visible: true, clicked: false };
  target.scrollIntoView({ block: "center", inline: "center" });
  target.click();
  return { visible: true, clicked: true };

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }
}
"""


NAVIGATE_JS = r"""
(url) => {
  location.href = url;
  return { ok: true, url };
}
"""


def redact_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]}****{digits[-4:]}"


def classify_login_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    url = str(snapshot.get("url") or "")
    text = str(snapshot.get("text") or "")
    phone_value = str(snapshot.get("phone_value") or "")

    if snapshot.get("has_switch_dialog") or "是否将身份切为招聘者" in text:
        return response("maybe_switch_to_recruiter", "检测到身份切换弹窗，正在切换到招聘者。")
    if snapshot.get("has_slider_captcha") or "向右拖动滑块" in text or "拖动滑块填充拼图" in text:
        return response(
            "waiting_slider_captcha",
            "BOSS 出现滑动拼图验证。请在浏览器里手动完成滑块验证，我会继续等待短信验证码状态。",
            needs_input="manual_slider",
        )
    if "/web/user/user-safe" in url or snapshot.get("has_safety_verify"):
        return response(
            "waiting_app_security_confirm",
            "BOSS 需要在手机 App 完成安全登录确认。请在手机上打开 BOSS 直聘并点击确认。",
            needs_input="app_confirm",
        )
    if is_recruiter_page(url, text):
        return response("logged_in", "BOSS 招聘者账号登录成功。", role="recruiter")
    if snapshot.get("has_login_form"):
        if phone_value and snapshot.get("sms_sent"):
            return response("waiting_sms_code", "验证码已发送，请输入短信验证码。", needs_input="sms_code")
        return response("waiting_phone", "请输入用于登录 BOSS 招聘者账号的手机号。", needs_input="phone")
    return response("needs_manual", "未能识别当前 BOSS 登录状态，请查看浏览器页面。")


def is_recruiter_page(url: str, text: str) -> bool:
    if "/web/user" in url:
        return False
    recruiter_markers = ("职位管理", "推荐牛人", "牛人管理", "沟通", "人才库")
    return "zhipin.com" in url and any(marker in text for marker in recruiter_markers)


def response(status: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "message": message}
    payload.update(extra)
    return payload


def read_login_state(client: CdpClient) -> dict[str, Any]:
    snapshot = client.evaluate(READ_LOGIN_STATE_JS) or {}
    return {
        **classify_login_state(snapshot),
        "current_url": snapshot.get("url"),
        "page_title": snapshot.get("title"),
    }


def start_recruiter_login(client: CdpClient) -> dict[str, Any]:
    state = read_login_state(client)
    if state["status"] in ("logged_in", "waiting_app_security_confirm", "maybe_switch_to_recruiter"):
        return state

    click_recruiter_tab_if_available(client)
    return read_login_state(client)


def click_recruiter_tab_if_available(client: CdpClient) -> bool:
    snapshot = client.evaluate(READ_LOGIN_STATE_JS) or {}
    if not snapshot.get("has_recruiter_tab"):
        return False

    result = client.evaluate(CLICK_RECRUITER_TAB_JS) or {}
    if not result.get("ok"):
        return False

    click_point = result.get("click") or {}
    try:
        client.click(float(click_point["x"]), float(click_point["y"]))
    except (KeyError, TypeError, ValueError):
        return False

    time.sleep(0.6)
    return True


def send_sms_code(client: CdpClient, phone: str) -> dict[str, Any]:
    click_recruiter_tab_if_available(client)
    result = client.evaluate(SEND_CODE_JS, phone) or {}
    if not result.get("ok"):
        return response("needs_manual", f"发送验证码失败：{result.get('reason') or 'unknown'}")
    click_point = result.get("click") or {}
    try:
        client.click(float(click_point["x"]), float(click_point["y"]))
    except (KeyError, TypeError, ValueError):
        return response("needs_manual", "发送验证码失败：未能定位验证码按钮点击位置。")

    deadline = time.time() + 4
    state = read_login_state(client)
    while time.time() < deadline:
        if state["status"] != "waiting_phone":
            return state
        time.sleep(0.5)
        state = read_login_state(client)

    return response(
        "needs_manual",
        "手机号已填入，但没有检测到验证码按钮进入倒计时。请查看页面上的“发送验证码”是否已触发。",
        send_button_text=result.get("button_text") or "",
    )


def submit_sms_code(client: CdpClient, sms_code: str) -> dict[str, Any]:
    result = client.evaluate(SUBMIT_CODE_JS, sms_code) or {}
    if not result.get("ok"):
        return response("needs_manual", f"提交验证码失败：{result.get('reason') or 'unknown'}")

    click_point = result.get("click") or {}
    try:
        client.click(float(click_point["x"]), float(click_point["y"]))
    except (KeyError, TypeError, ValueError):
        return response("needs_manual", "提交验证码失败：未能定位登录按钮点击位置。")

    deadline = time.time() + 8
    state = read_login_state(client)
    while time.time() < deadline:
        if state["status"] == "maybe_switch_to_recruiter":
            switch_result = client.evaluate(CLICK_SWITCH_TO_RECRUITER_JS) or {}
            if switch_result.get("visible"):
                time.sleep(1)
                state = read_login_state(client)
                if state["status"] != "maybe_switch_to_recruiter":
                    return state
        elif state["status"] in ("logged_in", "waiting_app_security_confirm", "waiting_slider_captcha", "needs_manual"):
            return state
        elif state["status"] == "waiting_sms_code":
            # BOSS may keep the same screen briefly while it validates the SMS code.
            time.sleep(0.5)
            state = read_login_state(client)
            continue
        else:
            time.sleep(0.5)
            state = read_login_state(client)
            continue

        time.sleep(0.5)
        state = read_login_state(client)

    return response(
        "needs_manual",
        "短信验证码已填入，但没有检测到登录流程继续。请查看页面上的“登录/注册”是否已触发。",
        submit_button_text=result.get("button_text") or "",
    )


def navigate_to(client: CdpClient, target: str) -> dict[str, Any]:
    targets = {
        "talent_search": TALENT_SEARCH_URL,
        "login": LOGIN_URL,
    }
    url = targets.get(target)
    if not url:
        return response("failed", f"不支持的导航目标：{target}")
    client.evaluate(NAVIGATE_JS, url)
    time.sleep(0.8)
    return {**read_login_state(client), "target": target}
