"""Application version exposed in FastAPI metadata and diagnostics."""

from pathlib import Path
import os


_version_file = Path(os.getenv("FIRM_MANAGER_VERSION_FILE", Path(__file__).resolve().parents[1] / "VERSION"))
APP_VERSION = _version_file.read_text(encoding="utf-8").strip() if _version_file.exists() else "0.0.0"
