import unittest
from datetime import datetime, timezone

from python.boss_parse import (
    create_candidate_fingerprint,
    infer_last_seen_at,
    parse_candidate_card_text,
    parse_detail_text,
    parse_resume_text,
)


class BossParseTests(unittest.TestCase):
    def test_parse_one_line_candidate_card(self):
        text = " 黄** 25岁 3年 本科 在职-考虑机会 15-25K 23年7月在大模型独角兽公司minimax开始实习 24年成功转正 211院校 技术岗招聘 社会招聘 校园招聘 期望 北京 HRBP 职位 MiniMax 招聘 院校 北京化工大学 人工智能"
        candidate = parse_candidate_card_text(text)

        self.assertEqual(candidate["masked_name"], "黄**")
        self.assertEqual(candidate["age"], 25)
        self.assertEqual(candidate["years_experience"], "3年")
        self.assertEqual(candidate["expected_city"], "北京")
        self.assertEqual(candidate["expected_position"], "HRBP")
        self.assertEqual(candidate["school"], "北京化工大学 人工智能")
        self.assertIn("大模型独角兽公司", candidate["short_summary"])

    def test_graduate_year_is_not_work_years(self):
        text = " 赛** 刚刚活跃 20岁 27年应届生 本科 在校-月内到岗 如deepseek-v4、智谱glm5、minimax m2.7 期望 北京 资产评估 职位 华泰证券 卖方分析师 院校 中央财经大学 金融工程"
        candidate = parse_candidate_card_text(text)

        self.assertEqual(candidate["years_experience"], "27年应届生")
        self.assertEqual(candidate["active_status"], "刚刚活跃")
        self.assertEqual(candidate["short_summary"], "如deepseek-v4、智谱glm5、minimax m2.7")

    def test_parse_detail_text(self):
        detail = parse_detail_text(
            """
伊** 30岁 6年 本科 在职-考虑机会
3年市场营销策划工作经验，熟悉新品上市营销、内容种草营销、电商营销。
工作经历
北京唱吧科技股份有限公司 | 市场营销 · 市场部
教育经历
吉林外国语大学 | 英语(英德双语) | 本科
活动策划 市场策划 内容营销
"""
        )

        self.assertIn("市场营销", detail["detail_summary"])
        self.assertTrue(any("北京唱吧" in item for item in detail["detail_companies_json"]))
        self.assertTrue(any("吉林外国语大学" in item for item in detail["detail_schools_json"]))

    def test_parse_resume_text_keeps_sections_and_redacts_contacts(self):
        resume = parse_resume_text(
            """
曹** ◎热搜
本周活跃 26岁| 2年| 硕士| 在职-暂不考虑
微信：bosshelper123
期望职位 北京| HRBP | 人工智能、互联网|面议
工作经历
北京月之暗面科技有限公司（moonshot.ai）| 招聘
高端人才招聘
教育经历
德累斯顿工业大学 | 人力资源开发与管理 | 硕士
联系Ta
为妥善保护牛人在BOSS直聘平台提交、发布、展示的简历
未经BOSS直聘及牛人本人书面授权，任何用户不得将牛人信息复制。
"""
        )

        self.assertIn("[redacted-wechat]", resume["resume_text"])
        self.assertNotIn("联系Ta", resume["resume_text"])
        self.assertNotIn("未经BOSS直聘", resume["resume_text"])
        self.assertIn("工作经历", resume["resume_sections_json"])
        self.assertIn("北京月之暗面", resume["resume_sections_json"]["工作经历"])
        self.assertEqual(len(resume["resume_text_hash"]), 64)

    def test_fingerprint_is_compact(self):
        candidate = parse_candidate_card_text("伊** 30岁 6年 本科 在职-考虑机会 18-25K 简短摘要 期望 北京 市场营销 职位 唱吧 市场营销 院校 吉林外国语大学 英语")
        self.assertEqual(len(create_candidate_fingerprint(candidate)), 24)

    def test_parse_multiline_school_marker(self):
        text = """费**
热搜
刚刚活跃
27岁  3年  硕士  在职-月内到岗  面议
agent应用开发经验，java, go后端开发经验，云计算领域研发经验。
985院校
期望
北京
其他后端开发
职位
阿里云
基础平台开发工程师
院校
北京大学
软件工程"""
        candidate = parse_candidate_card_text(text)

        self.assertEqual(candidate["expected_city"], "北京")
        self.assertEqual(candidate["expected_position"], "其他后端开发")
        self.assertEqual(candidate["school"], "北京大学 软件工程")

    def test_infers_last_seen_at_from_activity_status(self):
        collected_at = datetime(2026, 4, 28, 9, 30, tzinfo=timezone.utc)

        self.assertEqual(infer_last_seen_at("刚刚活跃", collected_at), "2026-04-28T09:30:00+00:00")
        self.assertEqual(infer_last_seen_at("今日活跃", collected_at), "2026-04-27T16:00:00+00:00")
        self.assertEqual(infer_last_seen_at("本周活跃", collected_at), "2026-04-26T16:00:00+00:00")
        self.assertEqual(infer_last_seen_at("3日内活跃", collected_at), "2026-04-25T09:30:00+00:00")
        self.assertEqual(infer_last_seen_at("2周内活跃", collected_at), "2026-04-14T09:30:00+00:00")
        self.assertEqual(infer_last_seen_at("2月内活跃", collected_at), "2026-02-28T09:30:00+00:00")
        self.assertEqual(infer_last_seen_at("2月以上未活跃", collected_at), "2026-02-28T09:30:00+00:00")

    def test_missing_activity_status_defaults_to_two_months_inactive(self):
        candidate = parse_candidate_card_text(
            "王** 30岁 5年 硕士 在职-考虑机会 面议 期望 北京 Java 职位 三快在线 AI Agent开发 院校 天津大学 计算机科学与技术"
        )

        self.assertEqual(candidate["active_status"], "2月以上未活跃")


if __name__ == "__main__":
    unittest.main()
