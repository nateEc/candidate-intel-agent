import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from boss_recruiting_pipeline_flow import (
    build_application,
    build_candidate,
    parse_contact_card,
    selected_job_matches,
    send_greeting,
)


class BossRecruitingPipelineFlowTests(unittest.TestCase):
    def test_parse_contact_card_extracts_message_and_time(self):
        card = parse_contact_card("任校彤 AI工程师\n我对这个岗位很感兴趣，期待您的回复~\n10:16")

        self.assertEqual(card["masked_name"], "任校彤")
        self.assertEqual(card["expected_position"], "AI工程师")
        self.assertEqual(card["last_message"], "我对这个岗位很感兴趣，期待您的回复~")
        self.assertEqual(card["message_time"], "10:16")

    def test_parse_contact_card_handles_boss_chat_multiline_card(self):
        card = parse_contact_card("2\n18:16\n杨玉梅\nJava\n您好，我是杨玉梅，有 2 年 Java 开发经验")

        self.assertEqual(card["masked_name"], "杨玉梅")
        self.assertEqual(card["expected_position"], "Java")
        self.assertEqual(card["last_message"], "您好，我是杨玉梅，有 2 年 Java 开发经验")
        self.assertEqual(card["message_time"], "18:16")

    def test_build_candidate_prefers_profile_header(self):
        candidate = build_candidate(
            {"text": "伊先生 AI工程师\n刚刚看了您发布的这个职位"},
            {
                "header_text": "伊先生 34岁 10年以上 本科",
                "body_text": "期望：北京 | Java | 25-35K\n哈尔滨华德学院 · 计算机科学与技术\n熟悉 SpringBoot 和分布式系统",
                "url": "https://www.zhipin.com/web/chat/index",
            },
            None,
        )

        self.assertEqual(candidate["masked_name"], "伊先生")
        self.assertEqual(candidate["age"], 34)
        self.assertEqual(candidate["education_level"], "本科")
        self.assertEqual(candidate["expected_salary"], "25-35K")
        self.assertIn("SpringBoot", candidate["short_summary"])

    def test_application_key_uses_weak_dedupe_fields(self):
        contact = {"text": "伊先生 AI工程师\n刚刚看了您发布的这个职位\n16:10"}
        application = build_application(contact, {"body_text": "profile"}, "scan-1", "AI工程师 _ 北京 20-30K")

        self.assertEqual(application["candidate_name"], "伊先生")
        self.assertEqual(application["job_title"], "AI工程师 _ 北京 20-30K")
        self.assertTrue(application["application_key"])

    def test_send_greeting_requires_confirmation(self):
        response = send_greeting(FakeClient(), {"confirm": False}, Path(":memory:"))

        self.assertEqual(response["status"], "confirmation_required")

    def test_selected_job_matches_rejects_all_jobs_fallback(self):
        self.assertTrue(selected_job_matches("AI工程师 _ 北京 20-30K", "AI工程师"))
        self.assertFalse(selected_job_matches("全部职位", "AI工程师"))


class FakeClient:
    def evaluate(self, script, payload=None):
        return {"ok": True, "input_text": "方便发一份你的简历过来吗？"}


if __name__ == "__main__":
    unittest.main()
