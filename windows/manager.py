"""Desktop control panel for the packaged Windows server."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.request import Request, urlopen
import webbrowser

import manager_core as core


def installation_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def wait_for_process(pid: int) -> None:
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            if kernel32.WaitForSingleObject(handle, 120000) == 0x102:
                raise RuntimeError("管理工具未能在两分钟内退出，升级已取消")
        finally:
            kernel32.CloseHandle(handle)


def wait_for_health(config: dict, version: str, seconds: int = 60) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if core.health(config, timeout=2, expected_version=version) is not None:
            return True
        time.sleep(1)
    return False


def record_result(root: Path, success: bool, message: str, backup: Path | None = None) -> None:
    destination = root / "data" / "updates" / "last-result.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        "success": success, "message": message, "backup": str(backup) if backup else "",
    }, ensure_ascii=False), encoding="utf-8")


def apply_update(root: Path, archive_path: Path, version: str, parent_pid: int) -> int:
    backup = None
    replaced = []
    service_was_running = False
    recovery_failed = False
    try:
        wait_for_process(parent_pid)
        core.validate_package(archive_path, version)
        config = core.load_config(root)
        service_was_running = core.service_state(root) == "running"
        core.stop_service(root)
        if core.service_state(root) == "running":
            raise RuntimeError("服务未能停止，已取消升级")
        backup = core.backup_database(root)
        with tempfile.TemporaryDirectory(prefix="firm-manager-originals-") as temp_dir:
            replaced = core.install_package(root, archive_path, version, Path(temp_dir))
            try:
                core.start_service(root)
                if not wait_for_health(config, version):
                    raise RuntimeError("新版本服务未能正常启动")
                if not service_was_running:
                    core.stop_service(root)
            except Exception as exc:
                recovery_errors = []
                for recover in (
                    lambda: core.stop_service(root),
                    lambda: core.rollback_files(replaced),
                    lambda: core.restore_database(root, backup) if backup else None,
                ):
                    try:
                        recover()
                    except Exception as recovery_error:
                        recovery_errors.append(str(recovery_error))
                if recovery_errors:
                    recovery_failed = True
                    raise RuntimeError(f"{exc}；程序或数据恢复失败：{'；'.join(recovery_errors)}") from exc
                if service_was_running:
                    core.start_service(root)
                    if not wait_for_health(config, core.read_version(root)):
                        raise RuntimeError(f"{exc}；原版本服务未能恢复") from exc
                raise
        record_result(root, True, f"已升级至 v{version}", backup)
        return 0
    except Exception as exc:
        if service_was_running and not recovery_failed and core.service_state(root) == "stopped":
            try:
                core.start_service(root)
            except Exception:
                pass
        record_result(root, False, str(exc), backup)
        return 1
    finally:
        manager = root / "Manager.exe"
        if manager.is_file():
            subprocess.Popen([str(manager)], cwd=root)


class Manager(tk.Tk):
    def __init__(self, root: Path):
        super().__init__()
        self.root_dir = root
        self.version = core.read_version(root)
        self.config = core.load_config(root)
        self.pending_release: dict | None = None
        self.events: queue.Queue = queue.Queue()

        self.title("业码汇 - 服务器管理")
        self.geometry("690x510")
        self.minsize(620, 470)
        self.columnconfigure(0, weight=1)

        self.bind_host = tk.StringVar(value=self.config["bind_host"])
        self.port = tk.StringVar(value=str(self.config["port"]))
        self.public_host = tk.StringVar(value=self.config["public_host"])
        self.status = tk.StringVar(value="正在检查服务...")
        self.local_address = tk.StringVar(value=core.local_url(self.config))
        self.external_address = tk.StringVar(value=core.public_url(self.config) or "未设置")
        self.update_status = tk.StringVar(value=f"当前版本 v{self.version}")
        self._build()
        self.after(100, self._poll_events)
        self.after(200, self._poll_status)
        self.after(1000, self._check_update)
        self._show_last_result()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=20)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(1, weight=1)

        ttk.Label(outer, text="服务器管理", font=("Microsoft YaHei UI", 17, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(outer, textvariable=self.status).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 18))

        ttk.Label(outer, text="监听范围").grid(row=2, column=0, sticky="w", pady=5)
        bind_select = ttk.Combobox(outer, textvariable=self.bind_host, state="readonly", width=24)
        bind_select["values"] = ("0.0.0.0", "127.0.0.1")
        bind_select.grid(row=2, column=1, sticky="w", pady=5)
        ttk.Label(outer, text="0.0.0.0 允许局域网访问").grid(row=2, column=2, sticky="w")

        ttk.Label(outer, text="端口").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(outer, textvariable=self.port, width=26).grid(row=3, column=1, sticky="w", pady=5)

        ttk.Label(outer, text="外部 IP 或域名").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(outer, textvariable=self.public_host, width=34).grid(row=4, column=1, sticky="ew", pady=5)
        ttk.Label(outer, text="DNS 需指向本服务器").grid(row=4, column=2, sticky="w", padx=(8, 0))

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, columnspan=3, sticky="w", pady=(18, 18))
        self.start_button = ttk.Button(actions, text="一键启动", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="停止服务", command=self._stop)
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(actions, text="打开本机页面", command=self._open_local).pack(side="left")
        ttk.Button(actions, text="检测外部地址", command=self._check_external).pack(side="left", padx=8)

        ttk.Separator(outer).grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 15))
        ttk.Label(outer, text="本机地址").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Label(outer, textvariable=self.local_address).grid(row=7, column=1, columnspan=2, sticky="w")
        ttk.Label(outer, text="外部地址").grid(row=8, column=0, sticky="w", pady=4)
        ttk.Label(outer, textvariable=self.external_address).grid(row=8, column=1, columnspan=2, sticky="w")

        ttk.Separator(outer).grid(row=9, column=0, columnspan=3, sticky="ew", pady=(16, 15))
        ttk.Label(outer, text="版本升级", font=("Microsoft YaHei UI", 11, "bold")).grid(row=10, column=0, columnspan=3, sticky="w")
        ttk.Label(outer, textvariable=self.update_status).grid(row=11, column=0, columnspan=3, sticky="w", pady=(6, 10))
        update_actions = ttk.Frame(outer)
        update_actions.grid(row=12, column=0, columnspan=3, sticky="w")
        self.check_button = ttk.Button(update_actions, text="检查更新", command=self._check_update)
        self.check_button.pack(side="left")
        self.update_button = ttk.Button(update_actions, text="安装新版", command=self._install_update, state="disabled")
        self.update_button.pack(side="left", padx=8)
        ttk.Button(update_actions, text="选择本地 ZIP 升级", command=self._install_local_update).pack(side="left")

        self.message = tk.StringVar(value="关闭管理工具不会停止后台服务。")
        ttk.Label(outer, textvariable=self.message, wraplength=620, foreground="#555555").grid(
            row=13, column=0, columnspan=3, sticky="w", pady=(22, 0)
        )

    def _run_background(self, task, on_success) -> None:
        def worker():
            try:
                result = task()
                self.events.put((on_success, result, None))
            except Exception as exc:
                self.events.put((on_success, None, exc))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        while not self.events.empty():
            callback, result, error = self.events.get()
            if error:
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="normal")
                self.check_button.configure(state="normal")
                self.update_button.configure(state="normal" if self.pending_release else "disabled")
                self.message.set(str(error))
                messagebox.showerror("操作失败", str(error), parent=self)
            else:
                callback(result)
        self.after(100, self._poll_events)

    def _current_form(self) -> dict:
        return core.validate_config(self.bind_host.get(), self.port.get(), self.public_host.get())

    def _start(self) -> None:
        try:
            config = self._current_form()
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc), parent=self)
            return
        self.start_button.configure(state="disabled")
        self.message.set("正在保存配置并启动服务...")

        def task():
            previous = core.load_config(self.root_dir)
            was_running = core.service_state(self.root_dir) == "running"
            try:
                core.save_config(self.root_dir, **config)
                core.stop_service(self.root_dir)
                core.configure_firewall(self.root_dir, config)
                core.start_service(self.root_dir)
                if not wait_for_health(config, self.version, seconds=45):
                    raise RuntimeError("服务已启动，但网页未能在 45 秒内响应；请检查 data/logs")
            except Exception as exc:
                recovery_errors = []
                for recover in (
                    lambda: core.stop_service(self.root_dir),
                    lambda: core.save_config(self.root_dir, **previous),
                    lambda: core.configure_firewall(self.root_dir, previous),
                    lambda: core.start_service(self.root_dir) if was_running else None,
                ):
                    try:
                        recover()
                    except Exception as recovery_error:
                        recovery_errors.append(str(recovery_error))
                if recovery_errors:
                    raise RuntimeError(f"{exc}；恢复原服务配置时又发生错误：{'；'.join(recovery_errors)}") from exc
                raise
            return core.health(config)

        def done(health_result):
            self.start_button.configure(state="normal")
            self.config = config
            self.local_address.set(core.local_url(config))
            self.external_address.set(core.public_url(config) or "未设置")
            self.message.set("服务已启动。" if health_result else "服务状态待确认。")
            self._refresh_status()
            self._open_local()

        self._run_background(task, done)

    def _stop(self) -> None:
        self.stop_button.configure(state="disabled")
        self._run_background(lambda: core.stop_service(self.root_dir), self._stopped)

    def _stopped(self, _result) -> None:
        self.stop_button.configure(state="normal")
        self.message.set("服务已停止。")
        self._refresh_status()

    def _poll_status(self) -> None:
        self._refresh_status()
        self.after(4000, self._poll_status)

    def _refresh_status(self) -> None:
        state = core.service_state(self.root_dir)
        labels = {"running": "服务运行中", "stopped": "服务已停止", "missing": "服务尚未安装", "unsupported": "仅支持 Windows 服务"}
        checked = core.health(self.config, timeout=1, expected_version=self.version) if state == "running" else None
        if state == "running" and checked is None:
            self.status.set("服务运行中，网页暂未响应")
        elif state == "running":
            self.status.set("服务运行中 · 首次启用待完成" if not checked["initialized"] else "服务运行中 · 网页可访问")
        else:
            self.status.set(labels.get(state, "服务状态未知"))

    def _open_local(self) -> None:
        status = core.health(self.config)
        path = "/setup" if status and not status["initialized"] else "/login"
        webbrowser.open(core.local_url(self.config) + path)

    def _check_external(self) -> None:
        try:
            config = self._current_form()
            if not core.public_url(config):
                raise ValueError("请先填写外部 IP 或域名")
        except ValueError as exc:
            messagebox.showerror("地址错误", str(exc), parent=self)
            return
        self.message.set("正在检测外部地址...")

        def task():
            request = Request(core.public_url(config) + "/api/setup/status", headers={"User-Agent": "FirmMatterCodeManagement-Manager"})
            with urlopen(request, timeout=8) as response:
                return json.load(response)

        self._run_background(task, lambda _: self.message.set("外部地址在本服务器上检测可访问。"))

    def _check_update(self) -> None:
        self.check_button.configure(state="disabled")
        self.update_status.set("正在查询 GitHub Release...")

        def done(release):
            self.check_button.configure(state="normal")
            self.pending_release = release
            if release:
                self.update_status.set(f"可升级至 v{release['version']}")
                self.update_button.configure(state="normal")
            else:
                self.update_status.set(f"当前版本 v{self.version}，已是最新版本")
                self.update_button.configure(state="disabled")

        self._run_background(lambda: core.latest_windows_release(self.version), done)

    def _install_update(self) -> None:
        release = self.pending_release
        if not release or not getattr(sys, "frozen", False):
            messagebox.showerror("无法升级", "请使用 Release 中的 Windows 管理工具执行升级。", parent=self)
            return
        if not messagebox.askyesno("安装新版", f"升级至 v{release['version']}？服务会短暂停止，数据库会先备份。", parent=self):
            return
        self._begin_upgrade(release["version"], release=release)

    def _install_local_update(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="选择 Windows Release 安装包", filetypes=[("ZIP 安装包", "*.zip")])
        if not path:
            return
        try:
            version = core.package_version(Path(path))
            core.validate_package(Path(path), version)
            if core.version_key(version) <= core.version_key(self.version):
                raise ValueError("所选安装包不是更新版本，已取消升级")
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("安装包无效", str(exc), parent=self)
            return
        if messagebox.askyesno("本地升级", f"使用所选安装包升级至 v{version}？服务会短暂停止，数据库会先备份。", parent=self):
            self._begin_upgrade(version, local_archive=Path(path))

    def _begin_upgrade(self, version: str, release: dict | None = None, local_archive: Path | None = None) -> None:
        if not getattr(sys, "frozen", False):
            messagebox.showerror("无法升级", "请使用 Release 中的 Windows 管理工具执行升级。", parent=self)
            return
        self.update_button.configure(state="disabled")
        self.message.set("正在准备升级包...")

        def task():
            staging = Path(tempfile.mkdtemp(prefix="FirmMatterCodeManagement-upgrade-"))
            archive = staging / core.WINDOWS_ASSET
            if release:
                core.download_package(release, archive)
            elif local_archive:
                shutil.copy2(local_archive, archive)
                core.validate_package(archive, version)
            helper = staging / "Manager-Update.exe"
            shutil.copy2(sys.executable, helper)
            return helper, archive

        def done(paths):
            helper, archive = paths
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen([
                str(helper), "--apply-update", str(self.root_dir), str(archive),
                version, str(os.getpid()),
            ], cwd=self.root_dir, creationflags=flags)
            self.destroy()

        self._run_background(task, done)

    def _show_last_result(self) -> None:
        path = self.root_dir / "data" / "updates" / "last-result.json"
        if not path.is_file():
            return
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            self.message.set(result["message"] + (f"；数据库备份：{result['backup']}" if result.get("backup") else ""))
        except (OSError, ValueError, KeyError):
            pass


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        root = installation_root()
        print(core.read_version(root), core.validate_config(**core.DEFAULT_CONFIG))
        return 0
    if len(sys.argv) == 6 and sys.argv[1] == "--apply-update":
        return apply_update(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], int(sys.argv[5]))
    if os.name != "nt":
        raise RuntimeError("服务器管理工具仅支持 Windows")
    root = installation_root()
    if not ctypes.windll.shell32.IsUserAnAdmin():
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, "", str(root), 1)
        if result <= 32:
            raise RuntimeError("安装或管理 Windows 服务需要管理员权限")
        return 0
    required = [root / name for name in core.REQUIRED_FILES]
    if any(not path.is_file() for path in required):
        raise RuntimeError("Windows 安装包不完整，请重新解压 Release ZIP")
    Manager(root).mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, str(exc), "事务所服务器管理", 0x10)
        else:
            print(exc, file=sys.stderr)
        raise SystemExit(1)
