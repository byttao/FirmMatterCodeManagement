import os
import json
from io import BytesIO
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "windows"))
import manager_core as core
import manager


class WindowsManagerCoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "installed"
        (self.root / "data").mkdir(parents=True)
        (self.root / "VERSION").write_text("0.1.10\n", encoding="utf-8")
        (self.root / "Manager.exe").write_text("old manager", encoding="utf-8")
        (self.root / "BackendServer.exe").write_text("old backend", encoding="utf-8")
        database = self.root / "data" / "db.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE projects (name TEXT)")
            connection.execute("INSERT INTO projects VALUES ('existing client')")
        self.archive = Path(self.temp.name) / "release.zip"
        self.package = {
            "VERSION": "0.1.11\n",
            "Manager.exe": "new manager",
            "BackendServer.exe": "new backend",
            "FirmMatterService.exe": "wrapper",
            "FirmMatterService.xml": "<service />",
            "README-Windows.txt": "instructions",
            "安装与初始化.html": "<html></html>",
            "prerequisites/README.txt": "no runtime needed",
        }
        self.pack()

    def pack(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, content in self.package.items():
                archive.writestr(name, content)

    def test_config_and_access_addresses(self):
        config = core.save_config(self.root, "0.0.0.0", "8010", "Firm.Example.com")
        self.assertEqual(core.load_config(self.root), config)
        self.assertEqual(core.local_url(config), "http://127.0.0.1:8010")
        self.assertEqual(core.public_url(config), "http://firm.example.com:8010")
        with self.assertRaisesRegex(ValueError, "监听范围"):
            core.validate_config("127.0.0.1", 8010, "firm.example.com")
        with self.assertRaisesRegex(ValueError, "端口"):
            core.validate_config("0.0.0.0", 70000, "")

    def test_health_rejects_a_server_with_the_wrong_version(self):
        responses = [BytesIO(b'{"initialized": false}'), BytesIO(b'{"info": {"version": "0.1.10"}}')]
        with patch.object(core, "urlopen", side_effect=responses):
            self.assertIsNone(core.health(core.DEFAULT_CONFIG, expected_version="0.1.11"))

    def test_local_package_upgrade_keeps_business_data(self):
        self.assertEqual(core.package_version(self.archive), "0.1.11")
        backup = core.backup_database(self.root)
        originals = Path(self.temp.name) / "originals"
        replaced = core.install_package(self.root, self.archive, "0.1.11", originals)
        self.assertTrue(replaced)
        self.assertEqual(core.read_version(self.root), "0.1.11")
        self.assertEqual((self.root / "Manager.exe").read_text(), "new manager")
        self.assertEqual((self.root / "prerequisites" / "README.txt").read_text(), "no runtime needed")
        with sqlite3.connect(self.root / "data" / "db.sqlite") as connection:
            self.assertEqual(connection.execute("SELECT name FROM projects").fetchone(), ("existing client",))
        with sqlite3.connect(backup) as connection:
            self.assertEqual(connection.execute("SELECT name FROM projects").fetchone(), ("existing client",))
        core.rollback_files(replaced)
        self.assertEqual(core.read_version(self.root), "0.1.10")
        self.assertEqual((self.root / "Manager.exe").read_text(), "old manager")

    def test_copy_failure_rolls_back_program(self):
        original_replace = os.replace
        failed = False

        def fail_once(source, destination):
            nonlocal failed
            if Path(destination).name == "VERSION" and not failed:
                failed = True
                raise OSError("simulated failure")
            return original_replace(source, destination)

        with patch.object(core.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "simulated failure"):
                core.install_package(self.root, self.archive, "0.1.11", Path(self.temp.name) / "originals")
        self.assertTrue(failed)
        self.assertEqual(core.read_version(self.root), "0.1.10")
        self.assertEqual((self.root / "Manager.exe").read_text(), "old manager")
        self.assertEqual((self.root / "BackendServer.exe").read_text(), "old backend")

    def test_archive_cannot_replace_data_or_escape_install_directory(self):
        for name in ("data/db.sqlite", "../outside.exe", "prerequisites/../../outside.exe"):
            with self.subTest(name=name):
                self.package[name] = "bad"
                self.pack()
                with self.assertRaisesRegex(RuntimeError, "非法路径"):
                    core.validate_package(self.archive, "0.1.11")
                del self.package[name]
        self.assertEqual(core.read_version(self.root), "0.1.10")

    def test_wrong_version_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "版本与目标版本不一致"):
            core.install_package(self.root, self.archive, "0.1.12", Path(self.temp.name) / "originals")
        self.assertEqual(core.read_version(self.root), "0.1.10")

    def test_upgrade_failure_restores_program_and_database(self):
        database = self.root / "data" / "db.sqlite"
        service = {"state": "running"}

        def stop_service(_root):
            service["state"] = "stopped"
            return True

        def start_service(_root):
            service["state"] = "running"
            if core.read_version(self.root) == "0.1.11":
                with sqlite3.connect(database) as connection:
                    connection.execute("INSERT INTO projects VALUES ('new version change')")

        def version_health(_config, version, seconds=60):
            return version == "0.1.10"

        with (patch.object(manager, "wait_for_process"),
              patch.object(core, "service_state", side_effect=lambda _root: service["state"]),
              patch.object(core, "stop_service", side_effect=stop_service),
              patch.object(core, "start_service", side_effect=start_service),
              patch.object(manager, "wait_for_health", side_effect=version_health),
              patch.object(manager.subprocess, "Popen")):
            result = manager.apply_update(self.root, self.archive, "0.1.11", 1)

        self.assertEqual(result, 1)
        self.assertEqual(core.read_version(self.root), "0.1.10")
        self.assertEqual((self.root / "BackendServer.exe").read_text(), "old backend")
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT name FROM projects").fetchall(), [("existing client",)])
        last_result = json.loads((self.root / "data" / "updates" / "last-result.json").read_text(encoding="utf-8"))
        self.assertFalse(last_result["success"])
        self.assertTrue(Path(last_result["backup"]).is_file())

    def test_upgrade_before_first_start_has_no_database_backup(self):
        (self.root / "data" / "db.sqlite").unlink()
        self.assertIsNone(core.backup_database(self.root))


if __name__ == "__main__":
    unittest.main()
