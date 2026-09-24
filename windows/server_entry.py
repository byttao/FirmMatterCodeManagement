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

    if getattr(sys, "frozen", False):
        os.environ["FIRM_MANAGER_STATIC_DIR"] = str(Path(sys._MEIPASS) / "static")
    else:
        sys.path.insert(0, str(root / "backend"))
        os.environ["FIRM_MANAGER_STATIC_DIR"] = str(root / "frontend" / "dist")

    from manager_core import load_config
    config = load_config(root)
    import main as backend_main
    import uvicorn

    uvicorn.run(
        backend_main.app,
        host=config["bind_host"],
        port=config["port"],
        access_log=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
