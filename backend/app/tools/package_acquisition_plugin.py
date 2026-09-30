"""校验采集插件目录并生成可上传的 ZIP 包。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.acquisition_plugins.manager import MAX_FILES, MAX_PACKAGE_BYTES, MAX_UNPACKED_BYTES, validate_manifest


def package_plugin(source: Path, output: Path) -> Path:
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("插件来源必须是目录")
    manifest = validate_manifest(json.loads((source / "plugin.json").read_text(encoding="utf-8")))
    if not (source / str(manifest["entrypoint"])).is_file() or not (source / "README.md").is_file():
        raise ValueError("插件目录缺少入口文件或中文 README.md")
    files = [path for path in source.rglob("*") if path.is_file()
             and not any(part in {"__pycache__", ".venv", ".git"} for part in path.relative_to(source).parts)
             and path.suffix not in {".pyc", ".pyo"}]
    if len(files) > MAX_FILES or sum(path.stat().st_size for path in files) > MAX_UNPACKED_BYTES:
        raise ValueError("插件文件过多或体积过大")
    for path in files:
        if path.is_symlink():
            raise ValueError("插件包不得包含符号链接")
    output = output.resolve()
    if output.exists():
        raise ValueError("输出文件已存在，请使用新的路径")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(source).as_posix())
    if output.stat().st_size > MAX_PACKAGE_BYTES:
        output.unlink()
        raise ValueError("生成包超过 20 MiB 上限")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="校验并打包 PictureShow 采集插件")
    parser.add_argument("source", type=Path, help="插件目录")
    parser.add_argument("--out", required=True, type=Path, help="输出 ZIP 文件路径")
    args = parser.parse_args()
    print(package_plugin(args.source, args.out))


if __name__ == "__main__":
    main()
