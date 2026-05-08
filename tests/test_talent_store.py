import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import candidate_evaluator
import talent_store


class TalentStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "talent.sqlite"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_weak_identity_merges_same_application_candidate(self):
        candidate = {
            "masked_name": "伊先生",
            "age": 34,
            "education_level": "本科",
            "years_experience": "10年以上",
            "expected_position": "Java",
            "expected_salary": "25-35K",
            "short_summary": "熟悉 SpringBoot 和分布式系统",
        }
        application = {
            "job_title": "AI工程师",
            "job_filter": "AI工程师 _ 北京 20-30K",
            "candidate_name": "伊先生",
            "last_message": "刚刚看了您发布的这个职位",
        }

        with talent_store.connect(self.db_path) as conn:
            first = talent_store.upsert_application_candidate(conn, candidate, application)
            second = talent_store.upsert_application_candidate(conn, {**candidate, "expected_salary": "面议"}, application)
            count = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]

        self.assertEqual(first, second)
        self.assertEqual(count, 1)

    def test_resume_hash_identity_survives_changed_chat_summary(self):
        candidate = {"masked_name": "伊先生", "age": 34, "education_level": "本科", "expected_position": "Java"}
        first_application = {"job_title": "AI工程师", "last_message": "第一次消息"}
        second_application = {"job_title": "AI工程师", "last_message": "第二次消息"}
        snapshot = {"resume_text": "Java 高级开发", "resume_text_hash": "resume-hash-1"}

        with talent_store.connect(self.db_path) as conn:
            first = talent_store.upsert_application_candidate(conn, candidate, first_application, resume_snapshot=snapshot)
            second = talent_store.upsert_application_candidate(conn, candidate, second_application, resume_snapshot=snapshot)

        self.assertEqual(first, second)

    def test_evaluator_grades_strong_candidate_a(self):
        evaluation = candidate_evaluator.evaluate_candidate(
            {
                "years_experience": "10年以上",
                "education_level": "本科",
                "active_status": "刚刚活跃",
                "short_summary": "熟悉 SpringBoot Java 分布式系统",
            },
            {"job_title": "Java 后端工程师", "required_keywords": ["Java", "SpringBoot"], "min_years": 5, "education": "本科"},
            "Java SpringBoot Redis MySQL 分布式系统",
        )

        self.assertEqual(evaluation["grade"], "A")
        self.assertEqual(evaluation["recommended_action"], "greet")


if __name__ == "__main__":
    unittest.main()
