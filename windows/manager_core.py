"""Windows service and release management for the packaged server."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import zipfile


REPOSITORY = "byttao/FirmMatterCodeManagement"
SERVICE_NAME = "FirmMatterCodeManagement"
FIREWALL_RULE = "FirmMatterCodeManagement TCP"
WINDOWS_ASSET = "FirmMatterCodeManagement-win-x64.zip"
REQUIRED_FILES = {
    "Manager.exe",
    "BackendServer.exe",
    "FirmMatterService.exe",
    "FirmMatterService.xml",
    "VERSION",
    "README-Windows.txt",
    "安装与初始化.html",
}
DEFAULT_CONFIG = {"bind_host": "0.0.0.0", "port": 8000, "public_host": ""}


def version_key(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"无法识别版本号：{value}")
    return tuple(int(part) for part in value.split("."))


def read_version(root: Path) -> str:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    version_key(version)
    return version


def validate_config(bind_host: str, port: int | str, public_host: str) -> dict:
    bind_host = bind_host.strip()
    if bind_host not in {"0.0.0.0", "127.0.0.1"}:
        raise ValueError("监听地址只能选择 0.0.0.0 或 127.0.0.1")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("端口必须是 1-65535 的整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError("端口必须是 1-65535 的整数")
    public_host = public_host.strip().lower().rstrip(".")
    if public_host and bind_host == "127.0.0.1":
        raise ValueError("设置外部地址时，监听范围应选择 0.0.0.0")
    if public_host:
        try:
            ipaddress.IPv4Address(public_host)
        except ipaddress.AddressValueError:
            labels = public_host.split(".")
            if len(public_host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            ):
                raise ValueError("外部地址只能填写 IPv4 或域名，不含协议和端口")
    return {"bind_host": bind_host, "port": port, "public_host": public_host}


def load_config(root: Path) -> dict:
    path = root / "data" / "server.json"
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    data = json.loads(path.read_text(encoding="utf-8"))
    return validate_config(data["bind_host"], data["port"], data.get("public_host", ""))


def save_config(root: Path, bind_host: str, port: int | str, public_host: str) -> dict:
    config = validate_config(bind_host, port, public_host)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    destination = data_dir / "server.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=data_dir, prefix=".server-", delete=False) as output:
        staged = Path(output.name)
        json.dump(config, output, ensure_ascii=False, indent=2)
    try:
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)
    return config


def local_url(config: dict) -> str:
    return f"http://127.0.0.1:{config['port']}"


def public_url(config: dict) -> str:
    host = config["public_host"]
    return f"http://{host}:{config['port']}" if host else ""


def health(config: dict, timeout: float = 2, expected_version: str | None = None) -> dict | None:
    try:
        request = Request(f"{local_url(config)}/api/setup/status", headers={"User-Agent": "FirmMatterCodeManagement-Manager"})
        with urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        if expected_version:
            version_request = Request(f"{local_url(config)}/openapi.json", headers={"User-Agent": "FirmMatterCodeManagement-Manager"})
            with urlopen(version_request, timeout=timeout) as response:
                schema = json.load(response)
            if schema.get("info", {}).get("version") != expected_version:
                return None
        return data if isinstance(data.get("initialized"), bool) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _run(command: list[str], root: Path, timeout: int = 45, check: bool = True) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout, creationflags=flags)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"命令执行失败：{command[0]}")
    return result


def service_state(root: Path) -> str:
    if os.name != "nt":
        return "unsupported"
    result = _run(["sc", "query", SERVICE_NAME], root, check=False)
    if result.returncode:
        return "missing"
    match = re.search(r"STATE\s*:\s*\d+\s+(\w+)", result.stdout)
    return match.group(1).lower() if match else "unknown"


def service_command(root: Path, command: str) -> None:
    if os.name != "nt":
        raise RuntimeError("服务管理仅支持 Windows")
    wrapper = root / "FirmMatterService.exe"
    if not wrapper.is_file():
        raise RuntimeError("安装包缺少 Windows 服务程序")
    _run([str(wrapper), command], root)


def wait_for_service(root: Path, expected: str, seconds: int = 45) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = service_state(root)
        if state == expected:
            return
        if state == "missing" and expected != "missing":
            break
        time.sleep(1)
    raise RuntimeError(f"Windows 服务未进入 {expected} 状态，当前状态：{service_state(root)}")


def start_service(root: Path) -> None:
    (root / "data" / "logs").mkdir(parents=True, exist_ok=True)
    state = service_state(root)
    if state == "missing":
        service_command(root, "install")
        state = service_state(root)
    if state != "running":
        service_command(root, "start")
        wait_for_service(root, "running")


def stop_service(root: Path) -> bool:
    state = service_state(root)
    if state == "stop_pending":
        wait_for_service(root, "stopped")
        return True
    if state == "start_pending":
        wait_for_service(root, "running")
        state = "running"
    if state != "running":
        return False
    service_command(root, "stop")
    wait_for_service(root, "stopped")
    return True


def configure_firewall(root: Path, config: dict) -> None:
    if os.name != "nt":
        raise RuntimeError("防火墙设置仅支持 Windows")
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}"], root, check=False)
    if config["bind_host"] == "0.0.0.0":
        _run([
            "netsh", "advfirewall", "firewall", "add", "rule", f"name={FIREWALL_RULE}",
            "dir=in", "action=allow", "protocol=TCP", f"localport={config['port']}",
        ], root)


def latest_windows_release(current: str) -> dict | None:
    request = Request(
        f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "FirmMatterCodeManagement-Manager"},
    )
    with urlopen(request, timeout=30) as response:
        release = json.load(response)
    target = release["tag_name"].removeprefix("v")
    if version_key(target) <= version_key(current):
        return None
    asset = next((item for item in release.get("assets", []) if item["name"] == WINDOWS_ASSET), None)
    if not asset:
        raise RuntimeError(f"v{target} 尚未提供 Windows 安装包，请稍后再检查")
    return {"version": target, "url": asset["browser_download_url"], "digest": asset.get("digest")}


def download_package(release: dict, destination: Path) -> None:
    request = Request(release["url"], headers={"User-Agent": "FirmMatterCodeManagement-Manager"})
    digest = hashlib.sha256()
    try:
        with urlopen(request, timeout=120) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
        expected = release.get("digest")
        if expected and expected != f"sha256:{digest.hexdigest()}":
            raise RuntimeError("Windows 安装包校验失败")
        validate_package(destination, release["version"])
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def package_version(archive_path: Path) -> str:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            version = archive.read("VERSION").decode("utf-8").strip()
    except (OSError, KeyError, UnicodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError("无法读取 Windows 安装包版本") from exc
    version_key(version)
    return version


def validate_package(archive_path: Path, target_version: str) -> list[str]:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len({name.casefold() for name in names}) != len(names) or not REQUIRED_FILES.issubset(names):
            raise RuntimeError("Windows 安装包文件不完整或存在重复文件")
        for name in names:
            parts = PurePosixPath(name).parts
            if (not name or name.startswith("/") or "\\" in name or ":" in name
                    or any(part in {"", ".", ".."} for part in name.split("/"))
                    or len(parts) > 1
                    or parts[0].startswith(".") or parts[0] == "data"):
                raise RuntimeError(f"Windows 安装包包含非法路径：{name}")
            info = archive.getinfo(name)
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError(f"Windows 安装包包含非法目录：{name}")
        if archive.read("VERSION").decode("utf-8").strip() != target_version:
            raise RuntimeError("Windows 安装包版本与目标版本不一致")
    return names


def backup_database(root: Path) -> Path | None:
    database = root / "data" / "db.sqlite"
    if not database.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.with_name(f"db-before-win-upgrade-{stamp}.sqlite")
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


def restore_database(root: Path, backup: Path) -> None:
    database = root / "data" / "db.sqlite"
    for suffix in ("-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)
    with tempfile.NamedTemporaryFile(dir=database.parent, prefix=".restore-", delete=False) as output:
        staged = Path(output.name)
    try:
        shutil.copy2(backup, staged)
        os.replace(staged, database)
    finally:
        staged.unlink(missing_ok=True)


def rollback_files(replaced: list[tuple[Path, Path | None]]) -> None:
    errors = []
    for destination, original in reversed(replaced):
        try:
            if original:
                os.replace(original, destination)
            else:
                destination.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{destination}: {exc}")
    if errors:
        raise RuntimeError("程序文件未能全部恢复：" + "; ".join(errors))


def install_package(root: Path, archive_path: Path, target_version: str, originals: Path) -> list[tuple[Path, Path | None]]:
    names = validate_package(archive_path, target_version)
    names.sort(key=lambda name: (name == "VERSION", name))
    replaced: list[tuple[Path, Path | None]] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for name in names:
                destination = root / name
                if not destination.parent.resolve().is_relative_to(root.resolve()):
                    raise RuntimeError(f"安装路径超出程序目录：{name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                original = originals / name if destination.exists() else None
                if original:
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, original)
                with tempfile.NamedTemporaryFile(dir=root, prefix=".upgrade-", delete=False) as output:
                    staged = Path(output.name)
                try:
                    with archive.open(name) as source, staged.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    os.replace(staged, destination)
                finally:
                    staged.unlink(missing_ok=True)
                replaced.append((destination, original))
    except Exception:
        rollback_files(replaced)
        raise
    return replaced
