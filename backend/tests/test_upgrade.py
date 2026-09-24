import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import upgrade


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.installed = self.base / "installed"
        self.release = self.base / "release"
        environment = patch.dict(os.environ, {
            "FIRM_MANAGER_DATA_DIR": str(self.installed / "backend" / "data"),
            "FIRM_MANAGER_DATABASE_URL": "",
        })
        environment.start()
        self.addCleanup(environment.stop)
        for root in (self.installed, self.release):
            (root / "backend" / "data").mkdir(parents=True)
            (root / "frontend").mkdir()
        (self.installed / "VERSION").write_text("0.1.9\n", encoding="utf-8")
        (self.installed / "upgrade.py").write_text("old updater", encoding="utf-8")
        (self.installed / "backend" / "main.py").write_text("old backend", encoding="utf-8")
        (self.installed / ".env").write_text("local config", encoding="utf-8")
        (self.installed / ".env.production").write_text("local production config", encoding="utf-8")
        (self.installed / "backend" / "data" / "jwt_secret").write_text("local secret", encoding="utf-8")
        database = self.installed / "backend" / "data" / "db.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute("INSERT INTO projects (name) VALUES ('existing client')")
        (self.release / "VERSION").write_text("0.1.10\n", encoding="utf-8")
        (self.release / "upgrade.py").write_text("new updater", encoding="utf-8")
        (self.release / ".env.production").write_text("release config", encoding="utf-8")
        (self.release / "backend" / "main.py").write_text("new backend", encoding="utf-8")
        (self.release / "frontend" / "package.json").write_text(
            json.dumps({"version": "0.1.10"}), encoding="utf-8"
        )
        self.archive = self.base / "release.tar.gz"
        self.pack()

    def pack(self):
        with tarfile.open(self.archive, "w:gz") as archive:
            archive.add(self.release, arcname="source")

    def test_upgrade_preserves_data_and_updates_updater(self):
        backup = upgrade.install_archive(self.installed, self.archive, "0.1.10")
        self.assertTrue(backup.exists())
        with sqlite3.connect(backup) as connection:
            self.assertEqual(connection.execute("SELECT name FROM projects").fetchone(), ("existing client",))
        with sqlite3.connect(self.installed / "backend" / "data" / "db.sqlite") as connection:
            self.assertEqual(connection.execute("SELECT name FROM projects").fetchone(), ("existing client",))
        self.assertEqual((self.installed / "backend" / "data" / "jwt_secret").read_text(), "local secret")
        self.assertEqual((self.installed / ".env").read_text(), "local config")
        self.assertEqual((self.installed / ".env.production").read_text(), "local production config")
        self.assertEqual((self.installed / "upgrade.py").read_text(), "new updater")
        self.assertEqual(upgrade.read_version(self.installed), "0.1.10")

    def test_wrong_version_does_not_touch_installation(self):
        (self.release / "VERSION").write_text("0.1.11\n", encoding="utf-8")
        self.pack()
        with self.assertRaisesRegex(RuntimeError, "版本与目标版本不一致"):
            upgrade.install_archive(self.installed, self.archive, "0.1.10")
        self.assertEqual(upgrade.read_version(self.installed), "0.1.9")
        self.assertEqual(list((self.installed / "backend" / "data").glob("*before-code-upgrade*")), [])

    def test_copy_failure_restores_original_program(self):
        real_replace = os.replace
        failed = False

        def fail_once(source, destination):
            nonlocal failed
            if Path(destination).name == "VERSION" and not failed:
                failed = True
                raise OSError("simulated write failure")
            return real_replace(source, destination)

        with patch.object(upgrade.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "已恢复原程序文件"):
                upgrade.install_archive(self.installed, self.archive, "0.1.10")
        self.assertTrue(failed)
        self.assertEqual(upgrade.read_version(self.installed), "0.1.9")
        self.assertEqual((self.installed / "backend" / "main.py").read_text(), "old backend")
        self.assertEqual((self.installed / "upgrade.py").read_text(), "old updater")

    def test_missing_database_stops_upgrade(self):
        (self.installed / "backend" / "data" / "db.sqlite").unlink()
        with self.assertRaisesRegex(RuntimeError, "找不到运行数据库"):
            upgrade.install_archive(self.installed, self.archive, "0.1.10")
        self.assertEqual(upgrade.read_version(self.installed), "0.1.9")

    def test_explicit_target_cannot_downgrade(self):
        with patch.object(upgrade, "__file__", str(self.installed / "upgrade.py")), \
                patch.object(sys, "argv", ["upgrade.py", "--target", "0.1.8", "--apply"]), \
                patch.object(upgrade, "download") as download:
            with self.assertRaisesRegex(RuntimeError, "禁止降级"):
                upgrade.main()
        download.assert_not_called()
        self.assertEqual(upgrade.read_version(self.installed), "0.1.9")


if __name__ == "__main__":
    unittest.main()
