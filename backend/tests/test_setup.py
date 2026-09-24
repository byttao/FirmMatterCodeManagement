"""Integration checks against a fresh, isolated database."""

import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

import httpx


class FirstRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_and_number_lifecycle(self):
        backend_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as data_dir:
            old_cwd = Path.cwd()
            old_data_dir = os.environ.get("FIRM_MANAGER_DATA_DIR")
            os.environ["FIRM_MANAGER_DATA_DIR"] = data_dir
            sys.path.insert(0, str(backend_dir))
            os.chdir(backend_dir)
            try:
                app = importlib.import_module("main").app
                local_transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
                async with httpx.AsyncClient(transport=local_transport, base_url="http://testserver") as client:
                    status = await client.get("/api/setup/status")
                    self.assertEqual(status.json(), {"initialized": False})

                    setup = {
                        "admin_username": "office_admin",
                        "admin_password": "a-strong-test-password",
                        "admin_real_name": "管理员",
                        "fiscal_year": 2026,
                        "firms": [{
                            "name": "Example Firm",
                            "report_types": [{"report_type": "Audit", "template": "EX-{yyyy}-{nnn}"}],
                        }],
                    }
                    invalid = await client.post("/api/setup", json={
                        **setup,
                        "firms": [{"name": "Example Firm", "report_types": [{"report_type": "Audit", "template": "EX-{yyyy}"}]}],
                    })
                    self.assertEqual(invalid.status_code, 400)
                    self.assertEqual((await client.get("/api/setup/status")).json(), {"initialized": False})

                    remote_transport = httpx.ASGITransport(app=app, client=("192.0.2.1", 12345))
                    async with httpx.AsyncClient(transport=remote_transport, base_url="http://testserver") as remote:
                        self.assertEqual((await remote.post("/api/setup", json=setup)).status_code, 403)

                    self.assertEqual((await client.post("/api/setup", json=setup)).status_code, 200)
                    self.assertEqual((await client.get("/api/setup/status")).json(), {"initialized": True})
                    self.assertEqual((await client.post("/api/setup", json=setup)).status_code, 409)

                    login = await client.post("/api/auth/login", json={
                        "username": setup["admin_username"], "password": setup["admin_password"],
                    })
                    self.assertEqual(login.status_code, 200, login.text)
                    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
                    years = await client.get("/api/numbered-years", headers=auth)
                    self.assertEqual(years.json()[0]["firms"][0]["rules"][0]["template"], "EX-{yyyy}-{nnn}")

                    practitioner = await client.post("/api/users", headers=auth, json={
                        "username": "auditor", "password": "another-password", "real_name": "执业人员", "role": "practitioner",
                    })
                    self.assertEqual(practitioner.status_code, 200, practitioner.text)
                    project = await client.post("/api/projects", headers=auth, json={
                        "firm": "Example Firm", "report_type": "Audit", "report_year": 2026,
                        "customer_name": "Sample Client", "leader_id": practitioner.json()["id"],
                    })
                    self.assertEqual(project.status_code, 200, project.text)
                    project_id = project.json()["project_id"]

                    other_user = await client.post("/api/users", headers=auth, json={
                        "username": "other_auditor", "password": "another-password", "real_name": "其他人员", "role": "practitioner",
                    })
                    self.assertEqual(other_user.status_code, 200)
                    other_login = await client.post("/api/auth/login", json={
                        "username": "other_auditor", "password": "another-password",
                    })
                    other_auth = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
                    forbidden = await client.post(f"/api/projects/{project_id}/generate-report-no", headers=other_auth)
                    self.assertEqual(forbidden.status_code, 403)

                    first = await client.post(f"/api/projects/{project_id}/generate-report-no", headers=auth)
                    self.assertEqual(first.status_code, 200, first.text)
                    self.assertEqual(first.json()["report_no"], "EX-2026-001")
                    recycled = await client.post(f"/api/projects/{project_id}/recycle-report-no", headers=auth)
                    self.assertEqual(recycled.status_code, 200, recycled.text)
                    self.assertEqual((await client.get(f"/api/projects/{project_id}", headers=auth)).json()["report_no_status"], "recycled")
                    self.assertEqual((await client.post(f"/api/projects/{project_id}/recycle-report-no", headers=auth)).status_code, 400)
                    second = await client.post(f"/api/projects/{project_id}/generate-report-no", headers=auth)
                    self.assertEqual(second.status_code, 200, second.text)
                    self.assertEqual(second.json()["report_no"], "EX-2026-002")
            finally:
                os.chdir(old_cwd)
                sys.path.remove(str(backend_dir))
                if old_data_dir is None:
                    os.environ.pop("FIRM_MANAGER_DATA_DIR", None)
                else:
                    os.environ["FIRM_MANAGER_DATA_DIR"] = old_data_dir


if __name__ == "__main__":
    unittest.main()
