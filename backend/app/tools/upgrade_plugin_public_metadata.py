"""为本机常用插件生成带公开元数据的新版本 ZIP，不覆盖原包、不安装插件。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile

from app.services.acquisition_plugins.manager import validate_manifest


PLUGIN_KEYS = {"idolxxx-gallery", "raindrop-ftxsri-workers-dev", "shfwzwz-raindrop-page"}
ITEMS_EXPRESSION = "[asdict(item) for item in page.items]"


def upgrade_package(source: Path, output: Path) -> Path:
    with ZipFile(source) as archive:
        manifest = validate_manifest(json.loads(archive.read("plugin.json")))
        key = manifest["key"]
        if key not in PLUGIN_KEYS:
            raise ValueError("只支持已核对字段的本机常用插件")
        runtime = archive.read("_runtime.py").decode("utf-8-sig")
        if runtime.count(ITEMS_EXPRESSION) != 1 or "def _public_item(" in runtime:
            raise ValueError("插件桥接代码已变化或已升级，请人工核对")
        version = str(manifest["version"]).split(".")
        version[-1] = str(int(version[-1]) + 1)
        manifest["version"] = ".".join(version)
        # 白名单取现成的展示字段，绝不复制 plugin_data、下载地址或请求参数。
        identifier = '\n    public["work_id"] = item.external_key' if key == "raindrop-ftxsri-workers-dev" else ""
        helper = (
            '\n\ndef _public_item(item):\n'
            '    data = asdict(item)\n'
            '    public = {}\n'
            '    if item.title:\n'
            '        public["original_title"] = item.title'
            + identifier + '\n'
            '    data["public_metadata"] = public\n'
            '    return data\n'
        )
        runtime = runtime.replace(ITEMS_EXPRESSION, "[_public_item(item) for item in page.items]") + helper
        readme = archive.read("README.md").decode("utf-8-sig")
        readme += "\n\n## 公开来源\n\n此版本主动提供原帖标题；Workers 接口另提供作品编号。公开来源不读取 plugin_data、凭据、会话或下载地址。请上传新版本、准备并启用后重新采集。\n"
        replacements = {
            "plugin.json": json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            "_runtime.py": runtime.encode("utf-8"), "README.md": readme.encode("utf-8"),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "x") as target:
            for info in archive.infolist():
                target.writestr(info, replacements.get(info.filename, archive.read(info)))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(upgrade_package(args.source, args.out))


if __name__ == "__main__":
    main()
