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
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen


DEFAULT_REPOSITORY = "byttao/FirmMatterCodeManagement"
PRESERVED_PATHS = {
    ".git",
    ".env",
    ".venv",
    ".workbuddy",
    "backend/data",
    "backend/static",
    "local-archive",
}


def read_version(root: Path) -> str:
    version_file = root / "VERSION"
    if not version_file.exists():
        return "0.0.0"
    return version_file.read_text(encoding="utf-8").strip()


def version_key(version: str) -> tuple[int, ...]:
    value = version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"无法识别版本号：{version}")
    return tuple(int(part) for part in value.split("."))


def github_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "FirmMatterCodeManagement-upgrader"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法读取 GitHub Release：{exc}") from exc


def latest_release(repository: str, target: str | None) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GitHub 仓库格式应为 owner/name")
    if target:
        version_key(target)
        tag = target if target.startswith("v") else f"v{target}"
        return tag, f"https://github.com/{repository}/archive/refs/tags/{tag}.tar.gz"
    release = github_json(f"https://api.github.com/repos/{repository}/releases/latest")
    tag = release.get("tag_name")
    archive = release.get("tarball_url")
    if not tag or not archive:
        raise RuntimeError("GitHub Release 缺少 tag_name 或 tarball_url")
    return tag, archive


def backup_database(root: Path) -> Path:
    data_dir = Path(os.getenv("FIRM_MANAGER_DATA_DIR", root / "backend" / "data"))
    database_url = os.getenv("FIRM_MANAGER_DATABASE_URL")
    if database_url:
        if not database_url.startswith("sqlite:///"):
            raise RuntimeError("自动升级只支持 SQLite 数据库连接串")
        database = Path(unquote(database_url.removeprefix("sqlite:///").split("?", 1)[0]))
    else:
        database = data_dir / "db.sqlite"
    if not database.is_absolute():
        raise RuntimeError("升级时数据库路径必须是绝对路径，请检查 FIRM_MANAGER_DATA_DIR 或 FIRM_MANAGER_DATABASE_URL")
    if not database.is_file():
        raise RuntimeError(f"找不到运行数据库：{database}；请核对数据目录后再升级")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.with_name(f"{database.stem}-before-code-upgrade-{stamp}{database.suffix}")
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as source, sqlite3.connect(backup) as target:
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
    return (any(value == item or value.startswith(f"{item}/") for item in PRESERVED_PATHS)
            or (relative.name.startswith(".env") and relative.name != ".env.example")
            or relative.name == "jwt_secret" or relative.suffix in {".db", ".sqlite", ".sqlite3"})


def install_archive(root: Path, archive_path: Path, target_version: str) -> Path:
    with tempfile.TemporaryDirectory(prefix="firm-manager-release-") as temp_dir:
        extraction = (Path(temp_dir) / "source").resolve()
        extraction.mkdir()
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                destination = (extraction / member.name).resolve()
                if (extraction not in destination.parents and destination != extraction
                        or not (member.isfile() or member.isdir())):
                    raise RuntimeError(f"Release 压缩包包含非法路径：{member.name}")
            for member in members:
                destination = extraction / member.name
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source_file, destination.open("wb") as output:
                        shutil.copyfileobj(source_file, output)
        roots = [path for path in extraction.iterdir() if path.is_dir()]
        if len(roots) != 1 or not (roots[0] / "backend" / "main.py").is_file():
            raise RuntimeError("下载的 Release 不是有效的系统源码包")
        source = roots[0]
        if read_version(source) != target_version:
            raise RuntimeError("Release 压缩包版本与目标版本不一致")
        package = source / "frontend" / "package.json"
        try:
            package_version = json.loads(package.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError) as exc:
            raise RuntimeError("Release 缺少有效的前端版本信息") from exc
        if package_version != target_version:
            raise RuntimeError("Release 前端版本与目标版本不一致")

        files = [path for path in source.rglob("*") if path.is_file() and not is_preserved(path.relative_to(source))]
        files.sort(key=lambda path: (path.relative_to(source) == Path("VERSION"), path.relative_to(source).as_posix()))
        backup = backup_database(root)
        originals = Path(temp_dir) / "originals"
        replaced: list[tuple[Path, Path | None]] = []
        try:
            for path in files:
                relative = path.relative_to(source)
                destination = root / relative
                if not destination.parent.resolve().is_relative_to(root.resolve()):
                    raise RuntimeError(f"安装路径超出程序目录：{relative}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                original = originals / relative if destination.exists() else None
                if original:
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, original)
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".upgrade-", delete=False) as staged:
                    staged_path = Path(staged.name)
                try:
                    shutil.copy2(path, staged_path)
                    os.replace(staged_path, destination)
                finally:
                    staged_path.unlink(missing_ok=True)
                replaced.append((destination, original))
        except Exception as exc:
            restore_errors = []
            for destination, original in reversed(replaced):
                try:
                    if original:
                        os.replace(original, destination)
                    else:
                        destination.unlink(missing_ok=True)
                except OSError as restore_exc:
                    restore_errors.append(f"{destination}: {restore_exc}")
            if restore_errors:
                raise RuntimeError(f"程序更新失败，自动恢复也未完成：{'; '.join(restore_errors)}；数据库备份：{backup}") from exc
            raise RuntimeError(f"程序更新失败，已恢复原程序文件；数据库备份：{backup}") from exc
        return backup


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
    if version_key(target) < version_key(current):
        raise RuntimeError("目标版本低于当前版本，禁止降级；旧程序可能无法读取新数据库")
    if version_key(target) == version_key(current):
        print("已是最新版本，无需升级。")
        return 0
    if not args.apply:
        print("这是检查模式；确认停掉后端后，使用 --apply 执行升级。")
        return 0

    with tempfile.TemporaryDirectory(prefix="firm-manager-download-") as temp_dir:
        archive = Path(temp_dir) / "release.tar.gz"
        print(f"下载 Release：{tag}")
        download(archive_url, archive)
        backup = install_archive(root, archive, target)
    print(f"数据库备份：{backup}")
    print("程序文件已更新。请启动后端，系统会自动执行数据库迁移；确认登录和数据无误后再删除备份。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"升级失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
