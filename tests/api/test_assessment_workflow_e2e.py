import os
import unittest

from fastapi.testclient import TestClient


os.environ["AUTH_MODE"] = "dummy"
os.environ["DATABASE_URL"] = "sqlite:///./certora.db"

from app.main import app  # noqa: E402


def _h(role: str, user_id: int) -> dict[str, str]:
    return {
        "X-Dummy-Role": role,
        "X-Dummy-User-Id": str(user_id),
        "X-Dummy-Email": f"{role}{user_id}@e2e.local",
        "X-Dummy-Name": f"E2E {role.title()} {user_id}",
    }


class AssessmentWorkflowE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.provider_headers = _h("provider", 9101)
        self.student_headers = _h("student", 9201)

    def test_complete_assessment_workflow_provider_to_result(self) -> None:
        create_payload = {
            "course_id": 0,
            "title": "E2E Standalone Assessment",
            "assessment_type": "mcq",
            "instructions": "Answer all questions.",
            "about": "E2E test assessment",
            "tools": ["calculator"],
            "topics": ["tax", "compliance", "audit"],
            "duration_minutes": 25,
            "timing_mode": "question",
            "time_per_question_seconds": 25,
            "questions_per_attempt": 25,
            "pass_score": 70,
            "negative_marking": False,
            "shuffle_questions": False,
            "shuffle_options": False,
            "max_attempts": 3,
            "certificate_enabled": True,
        }
        create_res = self.client.post("/exams", json=create_payload, headers=self.provider_headers)
        self.assertEqual(create_res.status_code, 201, create_res.text)
        exam_id = int(create_res.json()["id"])

        for i in range(25):
            q_payload = {
                "question_text": f"E2E Question {i + 1}",
                "question_type": "mcq_single_correct",
                "marks": 1,
                "negative_marks": 0,
                "options": [
                    {"option_text": f"Q{i+1} Option A", "is_correct": True, "position": 1},
                    {"option_text": f"Q{i+1} Option B", "is_correct": False, "position": 2},
                    {"option_text": f"Q{i+1} Option C", "is_correct": False, "position": 3},
                    {"option_text": f"Q{i+1} Option D", "is_correct": False, "position": 4},
                ],
            }
            q_res = self.client.post(f"/exams/{exam_id}/questions", json=q_payload, headers=self.provider_headers)
            self.assertEqual(q_res.status_code, 200, q_res.text)

        publish_res = self.client.post(f"/exams/{exam_id}/publish", headers=self.provider_headers)
        self.assertEqual(publish_res.status_code, 200, publish_res.text)

        issue_payload = {
            "candidate_name": "Issued Candidate",
            "candidate_email": "issued.candidate.e2e@example.com",
        }
        issue_res = self.client.post(f"/exams/{exam_id}/issue", json=issue_payload, headers=self.provider_headers)
        self.assertEqual(issue_res.status_code, 200, issue_res.text)
        issue_data = issue_res.json()
        temp_password = str(issue_data["temporary_password"])

        issued_login_res = self.client.post(
            "/exams/issued/login",
            json={"email": issue_payload["candidate_email"], "password": temp_password},
        )
        self.assertEqual(issued_login_res.status_code, 200, issued_login_res.text)
        issued_token = issued_login_res.json()["token"]

        issued_me_res = self.client.get("/exams/issued/me", headers={"Authorization": f"Bearer {issued_token}"})
        self.assertEqual(issued_me_res.status_code, 200, issued_me_res.text)
        issued_me = issued_me_res.json()
        self.assertEqual(issued_me["assessment_type"], "mcq")
        self.assertTrue(len(issued_me["questions"]) > 0)

        issued_answers = {}
        for q in issued_me["questions"]:
            first_option_id = int(q["options"][0]["id"])
            issued_answers[str(q["question_id"])] = [first_option_id]
        issued_submit_res = self.client.post(
            "/exams/issued/submit",
            headers={"Authorization": f"Bearer {issued_token}"},
            json={
                "answers": issued_answers,
                "submitted_data": {},
                "time_taken_seconds": 120,
                "proctoring_events": [],
            },
        )
        self.assertEqual(issued_submit_res.status_code, 200, issued_submit_res.text)
        self.assertIn("score_pct", issued_submit_res.json())

        catalog_res = self.client.get("/student/assessments/catalog", headers=self.student_headers)
        self.assertEqual(catalog_res.status_code, 200, catalog_res.text)
        catalog = catalog_res.json()
        row = next((r for r in catalog if int(r["exam_id"]) == exam_id), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "available")

        start_res = self.client.post(f"/student/exams/{exam_id}/attempts/start", headers=self.student_headers)
        self.assertEqual(start_res.status_code, 201, start_res.text)
        attempt_id = int(start_res.json()["attempt_id"])

        paper_res = self.client.get(f"/student/attempts/{attempt_id}/paper", headers=self.student_headers)
        self.assertEqual(paper_res.status_code, 200, paper_res.text)
        paper = paper_res.json()
        self.assertTrue(len(paper["questions"]) > 0)

        for idx, q in enumerate(paper["questions"]):
            save_res = self.client.post(
                f"/student/attempts/{attempt_id}/answers",
                headers=self.student_headers,
                json={"question_id": q["question_id"], "selected_option_ids": [int(q["options"][0]["option_id"])]},
            )
            self.assertEqual(save_res.status_code, 200, save_res.text)
            event_res = self.client.post(
                f"/student/attempts/{attempt_id}/events",
                headers=self.student_headers,
                json={
                    "event_type": "answer_saved",
                    "payload": {"question_index": idx, "question_id": q["question_id"]},
                },
            )
            self.assertEqual(event_res.status_code, 200, event_res.text)

        submit_res = self.client.post(f"/student/attempts/{attempt_id}/submit", headers=self.student_headers)
        self.assertEqual(submit_res.status_code, 200, submit_res.text)
        result = submit_res.json()
        self.assertIn("percentage", result)
        self.assertIn("passed", result)


if __name__ == "__main__":
    unittest.main()
