"""交付文档目录白名单不能放行任意路径或可执行文件。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('package_manager_core', Path(__file__).resolve().parents[1] / 'windows/manager_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class PackageTests(unittest.TestCase):
    def test_documents_allowlist_and_unsafe_archive_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / 'package.zip'

            def create(extra=None, omit=None):
                with zipfile.ZipFile(archive_path, 'w') as archive:
                    for name in sorted(core.REQUIRED_FILES - {omit}):
                        archive.writestr(name, '0.6.3' if name == 'VERSION' else 'fixture')
                    archive.writestr('docs/', '')
                    for directory in core.RUNTIME_DIRS:
                        archive.writestr(directory + '/fixture.dll', b'fixture')
                    if extra:
                        archive.writestr(extra, b'fixture')

            create()
            files = core.validate_package(archive_path, '0.6.3')
            self.assertTrue(core.DOCUMENT_FILES.issubset(files))
            for path in ['docs/unexpected.exe', 'docs/../data/db.sqlite', '../escape.txt',
                         'data/db.sqlite', 'docs\\escape.md', '/absolute.md']:
                with self.subTest(path=path):
                    create(extra=path)
                    with self.assertRaises(RuntimeError):
                        core.validate_package(archive_path, '0.6.3')
            create(omit='docs/导出与备份恢复.md')
            with self.assertRaises(RuntimeError):
                core.validate_package(archive_path, '0.6.3')
