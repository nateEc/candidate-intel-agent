import unittest
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from python.boss_hr_browser_agent import JobCloseRequest, JobPublishDraftRequest
from python.boss_job_publish_flow import close_job, read_job_publish_state, submit_job_publish


class FakeClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def evaluate(self, expression, arg=None):
        return self.snapshot


class BossJobPublishFlowTests(unittest.TestCase):
    def test_read_state_detects_publish_form(self):
        state = read_job_publish_state(
            FakeClient(
                {
                    "url": "https://www.zhipin.com/web/chat/job/edit?encryptId=0&enterSource=2",
                    "title": "BOSS直聘",
                    "has_edit_form": True,
                }
            )
        )

        self.assertEqual(state["status"], "job_publish_form_ready")

    def test_submit_requires_confirmation(self):
        state = submit_job_publish(FakeClient({}), confirm=False)

        self.assertEqual(state["status"], "confirmation_required")
        self.assertTrue(state["required_confirmation"])

    def test_close_requires_confirmation(self):
        state = close_job(FakeClient({}), {"confirm": False, "job_title": "AI工程师"})

        self.assertEqual(state["status"], "confirmation_required")
        self.assertTrue(state["required_confirmation"])
        self.assertEqual(state["job_title"], "AI工程师")

    def test_close_request_accepts_optional_title(self):
        request = JobCloseRequest(confirm=True, job_title="AI工程师")

        self.assertTrue(request.confirm)
        self.assertEqual(request.job_title, "AI工程师")

    def test_draft_request_validates_salary_range(self):
        with self.assertRaises(ValidationError):
            JobPublishDraftRequest(
                job_title="后端工程师",
                job_description="负责后端研发",
                salary_min_k=0,
            )

    def test_draft_request_rejects_inverted_salary(self):
        with self.assertRaises(ValidationError):
            JobPublishDraftRequest(
                job_title="后端工程师",
                job_description="负责后端研发",
                salary_min_k=50,
                salary_max_k=25,
            )

    def test_draft_request_accepts_required_fields(self):
        request = JobPublishDraftRequest(
            job_title="后端工程师",
            job_description="负责后端研发",
            recruitment_type="社招全职",
            overseas_status="境内岗位",
            job_type="其他后端开发",
            experience="3-5年",
            education="本科",
            salary_min_k=25,
            salary_max_k=50,
            salary_months=16,
        )

        self.assertEqual(request.salary_months, 16)


if __name__ == "__main__":
    unittest.main()
