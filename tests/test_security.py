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
            admin = models.User(username="admin", real_name="管理", role="admin", fiscal_year=2026, hashed_password=password)
            leader = models.User(username="leader", real_name="负责人", role="practitioner", fiscal_year=2026, hashed_password=password)
            outsider = models.User(username="outsider", real_name="无关人员", role="practitioner", fiscal_year=2026, hashed_password=password)
            db.add_all([admin, leader, outsider, models.FiscalYear(year=2026)])
            db.flush()
            cls.admin_id = admin.id
            db.add(models.Project(project_id="PRJ-2026-0001", firm="测试所", report_type="审计", report_year=2026,
                                  customer_name="测试客户", leader_id=leader.id, fiscal_year=2026))
            db.commit()

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
