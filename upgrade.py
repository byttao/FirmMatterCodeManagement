"""Download and apply a GitHub release while preserving installed data.

Run this command from the application directory while the backend is stopped:

    python upgrade.py                 # check the latest release
    python upgrade.py --apply         # backup data and install the latest release

Database migrations run when the new backend starts.  A service manager can
invoke this script and restart the backend after it exits; this script does
not guess how a particular Windows service, Docker container, or supervisor
is managed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPOSITORY = "byttao/FirmMatterCodeManagement"
PRESERVED_PATHS = {
    ".git",
    ".env",
    ".venv",
    "backend/data",
    "backend/static",
    "local-archive",
    "upgrade.py",
}


def read_version(root: Path) -> str:
    version_file = root / "VERSION"
    if not version_file.exists():
        return "0.0.0"
    return version_file.read_text(encoding="utf-8").strip()


def version_key(version: str) -> tuple[int, ...]:
    value = version.removeprefix("v")
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise ValueError(f"无法识别版本号：{version}") from exc


def github_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "FirmMatterCodeManagement-upgrader"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法读取 GitHub Release：{exc}") from exc


def latest_release(repository: str, target: str | None) -> tuple[str, str]:
    if target:
        tag = target if target.startswith("v") else f"v{target}"
        return tag, f"https://github.com/{repository}/archive/refs/tags/{tag}.tar.gz"
    release = github_json(f"https://api.github.com/repos/{repository}/releases/latest")
    tag = release.get("tag_name")
    archive = release.get("tarball_url")
    if not tag or not archive:
        raise RuntimeError("GitHub Release 缺少 tag_name 或 tarball_url")
    return tag, archive


def backup_database(root: Path) -> Path | None:
    data_dir = Path(os.getenv("FIRM_MANAGER_DATA_DIR", root / "backend" / "data"))
    database = Path(os.getenv("FIRM_MANAGER_DATABASE_URL", "").removeprefix("sqlite:///")) if os.getenv("FIRM_MANAGER_DATABASE_URL") else data_dir / "db.sqlite"
    if not database.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.with_name(f"{database.stem}-before-code-upgrade-{stamp}{database.suffix}")
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("升级前数据库备份完整性检查失败")
        os.chmod(backup, 0o600)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


def is_preserved(relative: Path) -> bool:
    value = relative.as_posix()
    return any(value == item or value.startswith(f"{item}/") for item in PRESERVED_PATHS)


def install_archive(root: Path, archive_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="firm-manager-release-") as temp_dir:
        extraction = Path(temp_dir) / "source"
        extraction.mkdir()
        with tarfile.open(archive_path, "r:gz") as archive:
            # Python 3.11 has no extractall(filter=...), so validate members
            # before extraction and keep the updater compatible with the
            # documented Python version.
            for member in archive.getmembers():
                destination = (extraction / member.name).resolve()
                if extraction not in destination.parents and destination != extraction:
                    raise RuntimeError("Release 压缩包包含非法路径")
            archive.extractall(extraction)
        roots = [path for path in extraction.iterdir() if path.is_dir()]
        if len(roots) != 1 or not (roots[0] / "backend" / "main.py").exists():
            raise RuntimeError("下载的 Release 不是有效的系统源码包")
        source = roots[0]
        for path in source.rglob("*"):
            relative = path.relative_to(source)
            if is_preserved(relative):
                continue
            destination = root / relative
            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)


def download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "FirmMatterCodeManagement-upgrader"})
    try:
        with urlopen(request, timeout=120) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (HTTPError, URLError, TimeoutError) as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"下载 Release 失败：{exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="事务所业务编号管理系统安全升级工具")
    parser.add_argument("--apply", action="store_true", help="备份数据并安装 Release；省略时只检查版本")
    parser.add_argument("--target", help="指定版本，例如 0.1.8 或 v0.1.8；默认使用最新 Release")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY, help="GitHub 仓库 owner/name")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    current = read_version(root)
    tag, archive_url = latest_release(args.repository, args.target)
    target = tag.removeprefix("v")
    print(f"当前版本：v{current}")
    print(f"目标版本：v{target}")
    if version_key(target) <= version_key(current) and not args.target:
        print("已是最新版本，无需升级。")
        return 0
    if not args.apply:
        print("这是检查模式；确认停掉后端后，使用 --apply 执行升级。")
        return 0

    backup = backup_database(root)
    if backup:
        print(f"数据库备份：{backup}")
    with tempfile.TemporaryDirectory(prefix="firm-manager-download-") as temp_dir:
        archive = Path(temp_dir) / "release.tar.gz"
        print(f"下载 Release：{tag}")
        download(archive_url, archive)
        install_archive(root, archive)
    print("程序文件已更新。请启动后端，系统会自动执行数据库迁移；确认登录和数据无误后再删除备份。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"升级失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
