import unittest

from python.boss_login_flow import classify_login_state, redact_phone


class BossLoginFlowTests(unittest.TestCase):
    def test_redacts_phone(self):
        self.assertEqual(redact_phone("13800138000"), "138****8000")
        self.assertEqual(redact_phone("123456"), "***")

    def test_classifies_waiting_phone(self):
        state = classify_login_state(
            {
                "url": "https://www.zhipin.com/web/user/?ka=header-login",
                "text": "验证码登录/注册 我要找工作 我要招聘 发送验证码 短信验证码",
                "has_login_form": True,
                "phone_value": "",
            }
        )

        self.assertEqual(state["status"], "waiting_phone")
        self.assertEqual(state["needs_input"], "phone")

    def test_classifies_waiting_sms_code(self):
        state = classify_login_state(
            {
                "url": "https://www.zhipin.com/web/user/?ka=header-login",
                "text": "验证码登录/注册 短信验证码",
                "has_login_form": True,
                "phone_value": "13800138000",
                "sms_sent": True,
            }
        )

        self.assertEqual(state["status"], "waiting_sms_code")
        self.assertEqual(state["needs_input"], "sms_code")

    def test_does_not_treat_phone_value_as_sent_code(self):
        state = classify_login_state(
            {
                "url": "https://www.zhipin.com/web/user/?ka=header-login",
                "text": "验证码登录/注册 短信验证码 发送验证码",
                "has_login_form": True,
                "phone_value": "13800138000",
                "sms_sent": False,
            }
        )

        self.assertEqual(state["status"], "waiting_phone")
        self.assertEqual(state["needs_input"], "phone")

    def test_classifies_switch_dialog(self):
        state = classify_login_state(
            {
                "url": "https://www.zhipin.com/web/user/?ka=header-login",
                "text": "是否将身份切为招聘者 取消 切换",
                "has_switch_dialog": True,
            }
        )

        self.assertEqual(state["status"], "maybe_switch_to_recruiter")

    def test_classifies_app_security_confirm(self):
        state = classify_login_state(
            {
                "url": "https://www.zhipin.com/web/user/user-safe?uuid=abc",
                "text": "安全验证 请在手机上打开BOSS直聘 点击确认",
            }
        )

        self.assertEqual(state["status"], "waiting_app_security_confirm")
        self.assertEqual(state["needs_input"], "app_confirm")

    def test_classifies_slider_captcha(self):
        state = classify_login_state(
            {
                "url": "https://www.zhipin.com/web/user/?ka=header-login",
                "text": "向右拖动滑块填充拼图 验证码登录/注册",
                "has_slider_captcha": True,
                "has_login_form": True,
                "phone_value": "13800138000",
            }
        )

        self.assertEqual(state["status"], "waiting_slider_captcha")
        self.assertEqual(state["needs_input"], "manual_slider")

    def test_classifies_recruiter_success(self):
        state = classify_login_state(
            {
                "url": "https://www.zhipin.com/web/chat/search",
                "text": "职位管理 推荐牛人 搜索 沟通 牛人管理",
            }
        )

        self.assertEqual(state["status"], "logged_in")
        self.assertEqual(state["role"], "recruiter")


if __name__ == "__main__":
    unittest.main()
