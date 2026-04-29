import unittest

from python.boss_jobs_parse import create_job_fingerprint, parse_job_card_text
from python.org_intel import contains_alias, role_family, salary_range_k


class OrgIntelTests(unittest.TestCase):
    def test_parse_boss_job_card_text(self):
        posting = parse_job_card_text(
            """
算法工程师
40-70K·16薪
北京·海淀区
3-5年
硕士
腾讯科技
机器学习 大模型 推荐算法
""",
            {"source_url": "https://www.zhipin.com/job_detail/example.html"},
        )

        self.assertEqual(posting["job_title"], "算法工程师")
        self.assertEqual(posting["salary_text"], "40-70K·16薪")
        self.assertEqual(posting["job_city"], "北京·海淀区")
        self.assertEqual(posting["company_name"], "腾讯科技")
        self.assertEqual(posting["experience_requirement"], "3-5年")
        self.assertEqual(posting["education_requirement"], "硕士")

    def test_parse_boss_left_job_card_without_company_suffix(self):
        posting = parse_job_card_text(
            """
Agent 全栈工程师
25-50K·16薪
5-10年
本科
月之暗面
上海·黄浦区·淮海路
"""
        )

        self.assertEqual(posting["job_title"], "Agent 全栈工程师")
        self.assertEqual(posting["company_name"], "月之暗面")
        self.assertEqual(posting["job_city"], "上海·黄浦区")

    def test_parse_daily_intern_salary(self):
        posting = parse_job_card_text(
            """
增长工程实习生
500-600元/天
5天/周
4个月
本科
月之暗面
上海·黄浦区
"""
        )

        self.assertEqual(posting["salary_text"], "500-600元/天")
        self.assertEqual(posting["company_name"], "月之暗面")

    def test_decodes_boss_obfuscated_salary_digits(self):
        posting = parse_job_card_text(
            """
Agent 全栈工程师
-K·薪
5-10年
本科
月之暗面
上海·黄浦区·淮海路
""",
            {"salary_text": "-K·薪"},
        )

        self.assertEqual(posting["salary_text"], "25-50K·16薪")

    def test_job_fingerprint_is_compact(self):
        posting = parse_job_card_text("产品经理\n25-45K\n上海\n本科\n腾讯科技")
        self.assertEqual(len(create_job_fingerprint(posting)), 24)

    def test_org_helpers(self):
        self.assertTrue(contains_alias("北京腾讯科技有限公司", ["Tencent", "腾讯科技"]))
        self.assertEqual(role_family("大模型算法工程师"), "算法/AI")
        self.assertEqual(salary_range_k("40-70K·16薪"), (40, 70))
        self.assertEqual(salary_range_k("面议"), (None, None))


if __name__ == "__main__":
    unittest.main()
