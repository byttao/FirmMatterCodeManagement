"""Read and initialize the packaged server bind configuration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


DEFAULT_CONFIG = {"bind_host": "0.0.0.0", "port": 8000, "public_host": ""}


def validate_config(bind_host: str, port: int | str, public_host: str = "") -> dict:
    bind_host = str(bind_host).strip()
    if bind_host not in {"0.0.0.0", "127.0.0.1"}:
        raise ValueError("监听地址只能选择 0.0.0.0 或 127.0.0.1")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("端口必须是 1-65535 的整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError("端口必须是 1-65535 的整数")
    return {"bind_host": bind_host, "port": port, "public_host": str(public_host).strip()}


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return validate_config(data["bind_host"], data["port"], data.get("public_host", ""))


def _write_json(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".server-", delete=False) as output:
        staged = Path(output.name)
        json.dump(config, output, ensure_ascii=False, indent=2)
        output.write("\n")
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def load_config(data_dir: Path, package_root: Path | None = None, ensure: bool = False) -> dict:
    data_dir = Path(data_dir)
    destination = data_dir / "server.json"
    if destination.exists():
        return _read_json(destination)
    template = (package_root or data_dir.parent) / "server.default.json"
    config = _read_json(template) if template.exists() else DEFAULT_CONFIG.copy()
    if ensure:
        _write_json(destination, config)
    return config


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument("--ensure", action="store_true")
    args = parser.parse_args()
    config = load_config(args.data_dir, args.package_root, args.ensure)
    print(f"{config['bind_host']}\t{config['port']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
