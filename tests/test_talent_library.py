import hashlib
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import talent_library


class TalentLibraryPostgresModelTests(unittest.TestCase):
    def test_schema_defines_postgres_pgvector_model(self):
        schema = talent_library.SCHEMA_PATH.read_text(encoding="utf-8")

        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS candidate_profiles", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS resume_evidence_spans", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS candidate_sensitive_attributes", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS candidate_embeddings", schema)
        self.assertIn("embedding VECTOR(384)", schema)
        self.assertIn("USING ivfflat", schema)

    def test_normalize_legacy_candidate_and_identifiers(self):
        resume_text = "伊先生 34岁 邮箱 yi.test@example.com 期望职位 Java 25-35K"
        row = {
            "source_fingerprint": "fp-1",
            "application_key": "app-1",
            "masked_name": "伊先生",
            "age": 34,
            "education_level": "本科",
            "expected_position": "Java",
            "expected_salary": "25-35K",
            "resume_text": resume_text,
            "resume_text_hash": hashlib.sha256(resume_text.encode("utf-8")).hexdigest(),
        }

        normalized = talent_library.normalize_legacy_candidate(row)
        identifiers = talent_library.candidate_identifier_values(normalized)
        identifier_types = {item[0] for item in identifiers}

        self.assertEqual(normalized["source_type"], "boss_application")
        self.assertEqual(normalized["expected_salary_text"], "25-35K")
        self.assertIn("boss_source_fingerprint", identifier_types)
        self.assertIn("resume_text_hash", identifier_types)
        self.assertIn("email_hash", identifier_types)
        self.assertIn("weak_profile_hash", identifier_types)

    def test_extractors_and_scoring_are_evidence_friendly(self):
        resume_text = """
伊先生 34岁 10年以上 本科 在职-考虑机会
邮箱 yi.test@example.com 微信: yitest888
深圳市鲲鹏快付科技有限公司 | java高级开发 | 2023.02 - 至今
负责 SpringBoot、Redis、Kafka 系统架构，完成核心链路性能优化，提升稳定性。
已婚，有孩子。
"""
        contacts = talent_library.extract_contacts(resume_text)
        sensitive = talent_library.extract_sensitive_attributes(resume_text)
        salary = talent_library.parse_salary("25-35K·16薪")
        embedding = talent_library.simple_embedding(resume_text)

        self.assertTrue(any(item["contact_type"] == "email" for item in contacts))
        self.assertTrue(any(item["contact_type"] == "wechat" for item in contacts))
        self.assertTrue(any(item["attribute_type"] == "marital_or_family" for item in sensitive))
        self.assertEqual(salary["annual_max_k"], 560)
        self.assertEqual(len(embedding), talent_library.EMBEDDING_DIMS)
        self.assertAlmostEqual(sum(value * value for value in embedding), 1.0, places=5)

    def test_match_job_does_not_use_sensitive_attributes(self):
        detail = {
            "profile": {
                "candidate_id": "candidate-1",
                "profile_summary": "Java 后端，熟悉 SpringBoot、Redis、Kafka 和 AI Agent",
                "expected_position": "Java 后端工程师",
                "work_years_value": 6,
                "education_level": "本科",
                "city": "北京",
            },
            "skills": [{"skill_name": "Java"}, {"skill_name": "SpringBoot"}, {"skill_name": "Redis"}],
            "work_experiences": [{"description": "负责 SpringBoot、Redis、Kafka 系统架构"}],
            "sensitive_attributes": [{"attribute_type": "marital_or_family", "attribute_value": "已婚"}],
        }
        score, reasons, risks, evidence = talent_library.score_job_match(
            detail,
            {
                "job_title": "Java 后端工程师",
                "required_keywords": ["Java", "SpringBoot", "Redis"],
                "min_years": 5,
                "education": "本科",
                "city": "北京",
            },
        )

        self.assertGreaterEqual(score, 80)
        self.assertTrue(any("关键词" in reason for reason in reasons))
        self.assertNotIn("sensitive_attributes", evidence)
        self.assertFalse(any("已婚" in item for item in reasons + risks))

    def test_update_sql_does_not_depend_on_python_grade_rank_as_sql_function(self):
        source = Path(talent_library.__file__).read_text(encoding="utf-8")

        self.assertNotIn("grade_rank(%(", source)
        self.assertNotIn("grade_rank(highest_grade)", source)


if __name__ == "__main__":
    unittest.main()
