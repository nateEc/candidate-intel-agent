import json
import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import org_intel_service
import org_job_store as store


class OrgDigestTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "org.sqlite"
        self.original_db = org_intel_service.DEFAULT_DB
        self.original_token = org_intel_service.ORG_INTEL_API_TOKEN
        org_intel_service.DEFAULT_DB = self.db_path
        org_intel_service.ORG_INTEL_API_TOKEN = "test-token"
        self.client = TestClient(org_intel_service.app)

    def tearDown(self):
        org_intel_service.DEFAULT_DB = self.original_db
        org_intel_service.ORG_INTEL_API_TOKEN = self.original_token
        self.tmpdir.cleanup()

    def auth(self):
        return {"Authorization": "Bearer test-token"}

    def create_subscription(self, status="active"):
        response = self.client.post(
            "/v1/org-intel/subscriptions",
            headers=self.auth(),
            json={
                "owner_id": "ceo-1",
                "display_name": "CEO关注公司",
                "cadence": "weekly_and_monthly",
                "companies": [
                    {"company": "月之暗面", "aliases": ["Moonshot"], "mode": "quick"},
                    {"company": "腾讯", "aliases": ["Tencent"], "mode": "quick"},
                ],
                "status": status,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seed_report(self, company, report_id=None):
        with store.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO org_intel_reports (
                  id, company_name, aliases_json, report_type, report_markdown,
                  source_counts_json, generated_at, report_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    company,
                    json.dumps([company], ensure_ascii=False),
                    "single_company",
                    f"# {company} 组织情报",
                    json.dumps({"candidate_signals": 3, "job_postings": 5}, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                    f"org-intel/{company}/report.md",
                ),
            )
            actual_report_id = report_id or cursor.lastrowid
            conn.execute(
                """
                INSERT INTO org_findings (
                  company_name, finding_type, title, severity, confidence,
                  summary, evidence_json, generated_at, report_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company,
                    "capability_build",
                    f"{company} 招聘建设重心明确",
                    "high",
                    0.91,
                    f"{company} 出现集中招聘和人才活跃信号。",
                    "{}",
                    datetime.now(timezone.utc).isoformat(),
                    actual_report_id,
                ),
            )
            conn.commit()
        return actual_report_id

    def test_subscription_api_requires_token_when_configured(self):
        response = self.client.post(
            "/v1/org-intel/subscriptions",
            json={
                "owner_id": "ceo-1",
                "companies": [{"company": "腾讯"}],
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_subscription_crud_and_paused_digest_guard(self):
        subscription = self.create_subscription(status="active")

        list_response = self.client.get("/v1/org-intel/subscriptions?owner_id=ceo-1", headers=self.auth())
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        patch_response = self.client.patch(
            f"/v1/org-intel/subscriptions/{subscription['id']}",
            headers=self.auth(),
            json={"status": "paused"},
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["status"], "paused")

        digest_response = self.client.post(
            f"/v1/org-intel/subscriptions/{subscription['id']}/digest-runs",
            headers=self.auth(),
            json={"cadence": "weekly"},
        )
        self.assertEqual(digest_response.status_code, 409)

    def test_digest_run_uses_fresh_reports_and_returns_ready_markdown(self):
        subscription = self.create_subscription()
        self.seed_report("月之暗面")
        self.seed_report("腾讯")

        response = self.client.post(
            f"/v1/org-intel/subscriptions/{subscription['id']}/digest-runs",
            headers=self.auth(),
            json={"cadence": "weekly", "client_request_id": "cron-1"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertIn("CEO 组织情报周报", payload["digest_markdown"])
        self.assertEqual({item["status"] for item in payload["company_statuses"]}, {"ready"})

        list_response = self.client.get(
            "/v1/org-intel/digest-runs?owner_id=ceo-1&cadence=weekly&limit=1",
            headers=self.auth(),
        )
        self.assertEqual(list_response.status_code, 200, list_response.text)
        self.assertEqual(list_response.json()[0]["digest_job_id"], payload["digest_job_id"])

    def test_digest_run_can_finish_partial_ready_when_one_company_blocks(self):
        report_id = self.seed_report("月之暗面")
        with store.connect(self.db_path) as conn:
            subscription = store.create_subscription(
                conn,
                {
                    "owner_id": "ceo-1",
                    "display_name": "CEO关注公司",
                    "cadence": "weekly",
                    "companies": [
                        {"company": "月之暗面", "aliases": ["月之暗面"], "mode": "quick"},
                        {"company": "腾讯", "aliases": ["腾讯"], "mode": "quick"},
                    ],
                },
            )
            blocked_job = store.create_job(
                conn,
                {"company": "腾讯", "aliases": ["腾讯"], "mode": "quick", "refresh": "auto", "report": True},
                eta_seconds=60,
            )
            store.update_job(
                conn,
                blocked_job["id"],
                status="blocked_needs_human",
                current_step="blocked_needs_human",
                error_message="BOSS 触发验证",
                finished_at=store.iso_now(),
            )
            digest = store.create_digest_run(
                conn,
                subscription,
                "weekly",
                {"cadence": "weekly"},
                [
                    {"company": "月之暗面", "status": "ready", "report_id": report_id},
                    {"company": "腾讯", "status": "blocked_needs_human", "job_id": blocked_job["id"]},
                ],
                eta_seconds=60,
            )
            advanced = org_intel_service.advance_digest_run(conn, digest)

        self.assertEqual(advanced["status"], "partial_ready")
        self.assertIn("风险/阻塞项", advanced["digest_markdown"])
        self.assertIn("腾讯", advanced["digest_markdown"])

    def test_eta_counts_running_jobs_as_queue_depth(self):
        with store.connect(self.db_path) as conn:
            running = store.create_job(
                conn,
                {"company": "月之暗面", "aliases": ["月之暗面"], "mode": "quick", "refresh": "all", "report": True},
                eta_seconds=600,
            )
            store.update_job(conn, running["id"], status="running_candidates", current_step="candidates")

            request = org_intel_service.OrgIntelRequest(
                company="腾讯",
                aliases=["腾讯"],
                mode="quick",
                refresh="all",
                report=True,
            )
            eta_seconds = org_intel_service.estimate_eta_seconds(request, conn)

        self.assertEqual(eta_seconds, 1200)


if __name__ == "__main__":
    unittest.main()
