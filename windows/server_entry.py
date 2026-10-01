"""Entry point bundled as BackendServer.exe for the Windows service."""

from pathlib import Path
import os
import sys


def installation_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> None:
    root = installation_root()
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FIRM_MANAGER_DATA_DIR"] = str(data_dir)
    os.environ["FIRM_MANAGER_VERSION_FILE"] = str(root / "VERSION")
    os.environ.pop("FIRM_MANAGER_DATABASE_URL", None)
    if len(sys.argv)==4 and sys.argv[1]=='--restore-backup':
        if not getattr(sys,'frozen',False):sys.path.insert(0,str(root/'backend'))
        from backups import restore_cli
        restore_cli(sys.argv[2],sys.argv[3])
        return
    if '--export-worker' in sys.argv:
        if not getattr(sys,'frozen',False):sys.path.insert(0,str(root/'backend'))
        from export_worker import main as run_worker
        run_worker()
        return
    public_key_file = root / "license-public-key.txt"
    if not public_key_file.is_file():
        raise RuntimeError('缺少预置发行公钥，请下载完整安装包')
    public_key = public_key_file.read_text(encoding='ascii').strip()
    import base64
    try:
        if len(base64.urlsafe_b64decode(public_key+'='*(-len(public_key)%4))) != 32:
            raise ValueError()
    except ValueError:
        raise RuntimeError('预置发行公钥无效，请下载完整安装包')
    os.environ['FIRM_MANAGER_LICENSE_PUBLIC_KEY'] = public_key

    if getattr(sys, "frozen", False):
        os.environ["FIRM_MANAGER_STATIC_DIR"] = str(Path(sys._MEIPASS) / "static")
    else:
        sys.path.insert(0, str(root / "backend"))
        os.environ["FIRM_MANAGER_STATIC_DIR"] = str(root / "frontend" / "dist")

    from manager_core import load_config
    config = load_config(root)
    os.environ["FIRM_MANAGER_PORT"] = str(config["port"])
    os.environ["FIRM_MANAGER_ALLOWED_HOSTS"] = config.get("public_host", "")
    import main as backend_main
    import uvicorn

    uvicorn.run(
        backend_main.app,
        host=config["bind_host"],
        port=config["port"],
        access_log=False,
        log_level="info",
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
