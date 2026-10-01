import asyncio
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

TEST_DIR = tempfile.TemporaryDirectory(prefix="firm-security-")
os.environ["FIRM_MANAGER_DATA_DIR"] = TEST_DIR.name
os.environ["FIRM_MANAGER_ALLOWED_HOSTS"] = "testserver"
os.environ["FIRM_MANAGER_ALLOWED_PORTS"] = "80"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
import main
import models
from auth import get_password_hash
from database import SessionLocal, engine
from schema_init import initialize_schema
from sqlalchemy import create_engine


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with SessionLocal() as db:
            password = get_password_hash("Test-password-2026")
            admin = models.User(username="admin", real_name="管理", role_records=[models.UserRoleRecord(role_code="office_admin")], fiscal_year=2026, hashed_password=password)
            leader = models.User(username="leader", real_name="负责人", is_practitioner=True, role_records=[models.UserRoleRecord(role_code="practitioner")], fiscal_year=2026, hashed_password=password)
            outsider = models.User(username="outsider", real_name="无关人员", is_practitioner=True, role_records=[models.UserRoleRecord(role_code="practitioner")], fiscal_year=2026, hashed_password=password)
            db.add_all([admin, leader, outsider, models.FiscalYear(year=2026)])
            db.flush()
            cls.admin_id = admin.id
            cls.leader_id = leader.id
            cls.outsider_id = outsider.id
            for name, roles, practitioner in [("number", ["number_manager"], False), ("finance", ["finance"], False), ("clerk", ["clerk"], False), ("combined", ["number_manager", "practitioner"], True)]:
                db.add(models.User(username=name, real_name=name, fiscal_year=2026, hashed_password=password,
                       is_practitioner=practitioner, role_records=[models.UserRoleRecord(role_code=r) for r in roles]))
            customer = models.Customer(name="测试客户", tax_id="TEST-TAX", identity_status="confirmed")
            db.add(customer)
            db.flush()
            cls.customer_id = customer.id
            db.add(models.Project(project_id="PRJ-2026-0001", firm="测试所", report_type="审计", report_year=2026,
                                  customer_name="测试客户", customer_id=customer.id, contract_amount=1234.56,
                                  leader_id=leader.id, fiscal_year=2026))
            for year in (2025, 2026):
                fy = db.query(models.FiscalYear).filter_by(year=year).first()
                if not fy:
                    fy = models.FiscalYear(year=year); db.add(fy); db.flush()
                firm = models.FiscalYearFirm(fiscal_year_id=fy.id, firm="测试所")
                db.add(firm); db.flush()
                rule = models.ReportNumberRule(fiscal_year_firm_id=firm.id, rule_name="审计编号", template="测试〔{yyyy}〕{nnnn}", sequence_digits=4)
                db.add(rule); db.flush()
                db.add(models.FiscalYearReportType(fiscal_year_firm_id=firm.id, report_type="审计", rule_id=rule.id))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()
        TEST_DIR.cleanup()

    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def login(self, username="admin"):
        response = await self.client.post("/api/auth/login", json={"username": username, "password": "Test-password-2026"})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers["X-CSRF-Token"] = self.client.cookies["firm_csrf"]
        return response

    async def test_anonymous_data_and_activation_denied(self):
        self.assertEqual((await self.client.get("/api/projects")).status_code, 401)
        self.assertEqual((await self.client.post("/api/license/activate", json={"license_document": {}})).status_code, 401)

    async def test_unrelated_get_and_empty_update_denied(self):
        await self.login("outsider")
        for method in ("GET", "PUT"):
            response = await self.client.request(method, "/api/projects/1", **({"json": {}} if method == "PUT" else {}))
            self.assertIn(response.status_code, (403, 404), response.text)

    async def test_authorized_empty_update_rejected(self):
        await self.login("leader")
        response = await self.client.put("/api/projects/1", json={})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "empty_update")

    async def test_unknown_fields_rejected(self):
        await self.login("leader")
        response = await self.client.put("/api/projects/1", json={"report_no": "伪造编号"})
        self.assertEqual(response.status_code, 422)

    async def new_project(self, year=2026, **changes):
        payload = {"fiscal_year": year, "firm": "测试所", "report_type": "审计", "report_year": year,
                   "customer_name": "测试客户", "customer_id": self.customer_id, "leader_id": self.leader_id}
        payload.update(changes)
        result = await self.client.post("/api/projects", json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    async def test_five_roles_projection_and_finance_boundary(self):
        await self.login("number")
        project = (await self.client.get("/api/projects/1")).json()
        self.assertIsNone(project["contract_amount"])
        self.assertNotIn("phone", project["leader"])
        self.assertNotIn("roles", project["leader"])
        self.assertEqual((await self.client.get("/api/projects/1/finance/invoices")).status_code, 403)
        self.assertEqual((await self.client.patch("/api/projects/1", json={"expected_revision": project["revision"], "contract_amount": 1})).status_code, 403)
        await self.login("finance")
        self.assertEqual((await self.client.get("/api/projects/1")).json()["contract_amount"], 1234.56)
        self.assertEqual((await self.client.post("/api/numbered-years", json={"year": 2027})).status_code, 403)
        self.assertEqual((await self.client.get("/api/users")).status_code, 403)
        await self.login("combined")
        profile = (await self.client.get("/api/auth/me")).json()
        self.assertTrue(profile["is_practitioner"])
        self.assertIn("number.configure", profile["permissions"])
        self.assertNotIn("finance.write", profile["permissions"])
        with SessionLocal() as db:
            self.assertEqual(db.query(models.User).filter_by(is_active=True, is_practitioner=True).count(), 3)

    async def test_member_money_hidden_and_injection_rejected(self):
        await self.login()
        project = await self.new_project(member_ids=[self.outsider_id], contract_amount=123)
        await self.login("outsider")
        result = await self.client.get(f'/api/projects/{project["id"]}')
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()["contract_amount"])
        self.assertIsNone(result.json()["invoiced_amount"])
        for payload in ({"contract_amount": 9}, {"leader_id": self.outsider_id}, {"fiscal_year": 2025}, {"report_no": "BAD"}):
            result = await self.client.patch(f'/api/projects/{project["id"]}', json={"expected_revision": 1, **payload})
            self.assertIn(result.status_code, (403, 422))

    async def test_per_tab_year_and_revision_conflict(self):
        await self.login()
        first = await self.new_project(2025)
        await self.client.put("/api/users/current-fiscal-year", json={"fiscal_year": 2026})
        second = await self.new_project(2025)
        self.assertEqual(first["fiscal_year"], second["fiscal_year"])
        result = await self.client.get("/api/projects", params={"fiscal_year": 2025})
        self.assertTrue(all(p["fiscal_year"] == 2025 for p in result.json()["items"]))
        url = f'/api/projects/{first["id"]}'
        self.assertEqual((await self.client.patch(url, json={"expected_revision": 1, "priority": "高"})).status_code, 200)
        conflict = await self.client.patch(url, json={"expected_revision": 1, "priority": "低"})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual((await self.client.get(url)).json()["priority"], "高")

    async def test_number_idempotency_void_and_immutable_customer(self):
        await self.login()
        project = await self.new_project()
        url = f'/api/projects/{project["id"]}'
        headers = {"Idempotency-Key": f'test-number-{project["id"]}'}
        first = await self.client.post(url + "/generate-report-no", json={"expected_revision": 1}, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        retry = await self.client.post(url + "/generate-report-no", json={"expected_revision": 1}, headers=headers)
        self.assertEqual(first.json(), retry.json())
        wrong = await self.client.post(url + "/generate-report-no", json={"expected_revision": 2}, headers=headers)
        self.assertEqual(wrong.status_code, 409)
        changed = await self.client.patch(url, json={"expected_revision": 2, "customer_name": "伪造"})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual((await self.client.delete(url, params={"expected_revision": 2})).status_code, 403)
        void = await self.client.post(url + "/void-report-no", json={"expected_revision": 2, "reason": "验收作废"})
        self.assertEqual(void.status_code, 200, void.text)
        self.assertEqual((await self.client.post(url + "/generate-report-no", json={"expected_revision": 1}, headers=headers)).status_code, 409)
        with SessionLocal() as db:
            self.assertEqual(db.query(models.ReportNumberHistory).filter_by(project_id=project["id"]).count(), 1)

    async def test_customer_directory_null_tax_and_snapshots(self):
        await self.login()
        data = {"name": "个人验收主体", "type": "individual", "tax_id": None}
        first = await self.client.post("/api/customers", json=data)
        second = await self.client.post("/api/customers", json=data)
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        customer_id = first.json()["id"]
        create_tax = {"name": "并发税号客户", "tax_id": "REPEAT-TAX"}
        outcomes = await asyncio.gather(*(self.client.post("/api/customers", json=create_tax) for _ in range(5)))
        self.assertEqual(sum(r.status_code == 200 for r in outcomes), 1)
        self.assertTrue(all(r.status_code in (200, 409) for r in outcomes))
        project = await self.new_project(customer_id=customer_id)
        issue = await self.client.post(f'/api/projects/{project["id"]}/generate-report-no', json={"expected_revision": 1}, headers={"Idempotency-Key": "pending-identity"})
        self.assertEqual(issue.status_code, 409)
        renamed = await self.client.patch(f"/api/customers/{customer_id}", json={"expected_revision": 1, "name": "更名个人主体"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual((await self.client.get(f'/api/projects/{project["id"]}')).json()["customer_name"], data["name"])
        await self.login("clerk")
        lookup = (await self.client.get("/api/customers/lookup", params={"q": "个人"})).json()
        self.assertNotIn("total", lookup)
        self.assertNotIn("tax_id", lookup["items"][0])
        self.assertEqual((await self.client.get(f"/api/customers/{customer_id}")).status_code, 404)

    async def test_last_admin_and_identity_validation(self):
        await self.login()
        revision = (await self.client.get("/api/auth/me")).json()["permission_revision"]
        result = await self.client.put(f"/api/users/{self.admin_id}", json={"expected_revision": revision, "roles": ["clerk"]})
        self.assertEqual(result.status_code, 400, result.text)
        result = await self.client.post("/api/users", json={"username": "invalid-person", "password": "Test-password-2026", "real_name": "错误身份", "roles": ["practitioner"], "is_practitioner": False})
        self.assertEqual(result.status_code, 422)

    async def test_fifty_parallel_number_requests(self):
        await self.login()
        projects = [await self.new_project() for _ in range(50)]
        results = await asyncio.gather(*(self.client.post(f'/api/projects/{p["id"]}/generate-report-no',
            json={"expected_revision": 1}, headers={"Idempotency-Key": f'parallel-number-{p["id"]}'}) for p in projects))
        self.assertTrue(all(r.status_code == 200 for r in results), [r.text for r in results if r.status_code != 200])
        self.assertEqual(len({r.json()["report_no"] for r in results}), 50)
        with SessionLocal() as db:
            self.assertEqual(db.query(models.ReportNumberHistory).filter(models.ReportNumberHistory.project_id.in_([p["id"] for p in projects])).count(), 50)

    async def test_concurrent_last_admin_disable(self):
        await self.login()
        with SessionLocal() as db:
            extra = models.User(username="race_admin", real_name="并发管理员", fiscal_year=2026,
                hashed_password=get_password_hash("Test-password-2026"), role_records=[models.UserRoleRecord(role_code="office_admin")])
            db.add(extra); db.commit(); extra_id = extra.id
        other = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver")
        try:
            await other.post("/api/auth/login", json={"username": "race_admin", "password": "Test-password-2026"})
            other.headers["X-CSRF-Token"] = other.cookies["firm_csrf"]
            results = await asyncio.gather(
                self.client.put(f"/api/users/{extra_id}", json={"expected_revision": 1, "is_active": False}),
                other.put(f"/api/users/{self.admin_id}", json={"expected_revision": 1, "is_active": False}))
            self.assertEqual(sum(r.status_code == 200 for r in results), 1, [r.text for r in results])
            with SessionLocal() as db:
                self.assertEqual(db.query(models.User).filter(models.User.is_active == True,
                    models.User.role_records.any(models.UserRoleRecord.role_code == "office_admin")).count(), 1)
        finally:
            await other.aclose()
            with SessionLocal() as db:
                db.get(models.User, self.admin_id).is_active = True
                db.get(models.User, extra_id).is_active = False
                db.commit()

    async def test_ten_thousand_customer_cursor_search(self):
        with SessionLocal() as db:
            db.bulk_insert_mappings(models.Customer, [{"name": f"分页验收客户{i:05d}", "tax_id": f"PAGE-{i:05d}"} for i in range(10000)])
            db.commit()
        await self.login("clerk")
        cursor = 0
        found = []
        for _ in range(5):
            response = await self.client.get("/api/customers/lookup", params={"q": "分页验收", "cursor": cursor, "limit": 50})
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(len(data["items"]), 50)
            self.assertNotIn("total", data)
            found.extend(c["id"] for c in data["items"])
            cursor = data["next_cursor"]
        self.assertEqual(len(set(found)), 250)

    async def test_password_change_revokes_other_device(self):
        await self.login("leader")
        other = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver")
        try:
            await other.post("/api/auth/login", json={"username": "leader", "password": "Test-password-2026"})
            response = await self.client.post("/api/auth/change-password", json={"current_password": "Test-password-2026", "new_password": "New-test-password-2026"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((await other.get("/api/auth/me")).status_code, 401)
        finally:
            await other.aclose()
            hashed = get_password_hash("Test-password-2026")
            with SessionLocal() as db:
                db.query(models.User).filter_by(username="leader").one().hashed_password = hashed
                db.commit()

    async def test_cookie_flags_and_csrf(self):
        response = await self.login()
        cookie = response.headers.get_list("set-cookie")[0].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertNotIn("; secure", cookie)
        del self.client.headers["X-CSRF-Token"]
        self.assertEqual((await self.client.put("/api/projects/1", json={})).status_code, 403)

    async def test_cross_origin_login_and_write_denied(self):
        response = await self.client.post("/api/auth/login", headers={"Origin": "http://evil.example"}, json={"username": "admin", "password": "Test-password-2026"})
        self.assertEqual(response.status_code, 403)

    async def test_chunked_body_limit(self):
        async def body():
            for _ in range(33):
                yield b"x" * 65536
        response = await self.client.post("/api/auth/login", content=body())
        self.assertEqual(response.status_code, 413)

    async def test_logout_revokes_cookie(self):
        await self.login()
        original = self.client.cookies["firm_session"]
        self.assertEqual((await self.client.post("/api/auth/logout")).status_code, 200)
        self.client.cookies.set("firm_session", original)
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 401)

    async def test_admin_reset_revokes_existing_session(self):
        await self.login("outsider")
        with SessionLocal() as db:
            user = db.query(models.User).filter_by(username="outsider").one()
            user.session_version += 1
            db.commit()
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 401)

    async def test_spoofed_host_and_forwarded_origin(self):
        self.assertEqual((await self.client.get("/api/setup/status", headers={"Host": "evil.example"})).status_code, 400)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, client=("203.0.113.5", 12345)), base_url="http://testserver") as remote:
            response = await remote.post("/api/setup", headers={"X-Forwarded-For": "127.0.0.1"}, json={"admin_username": "other", "admin_password": "Test-password-2026", "admin_real_name": "管理", "fiscal_year": 2026, "firms": []})
            self.assertEqual(response.status_code, 403)

    async def test_request_id_and_no_store(self):
        response = await self.client.get("/api/projects")
        self.assertTrue(response.headers["X-Request-ID"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json()["detail"]["request_id"], response.headers["X-Request-ID"])

    def test_foreign_keys_and_full_durability(self):
        with engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
            self.assertEqual(connection.exec_driver_sql("PRAGMA synchronous").scalar(), 2)

    def test_unknown_schema_is_preserved(self):
        path = Path(TEST_DIR.name) / "unknown.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE old_data(value TEXT)")
            db.execute("INSERT INTO old_data VALUES('keep')")
        old = create_engine(f"sqlite:///{path}")
        with self.assertRaises(RuntimeError):
            initialize_schema(old)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT value FROM old_data").fetchone()[0], "keep")
        old.dispose()


if __name__ == "__main__":
    unittest.main()
