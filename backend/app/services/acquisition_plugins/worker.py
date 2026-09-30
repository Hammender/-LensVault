"""插件子进程协议。仅使用 Python 标准库，可在插件独立环境中运行。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    request = json.load(sys.stdin)
    entry = (root / request["entrypoint"]).resolve()
    if not entry.is_relative_to(root) or not entry.is_file():
        raise ValueError("插件入口不存在")
    spec = importlib.util.spec_from_file_location("pictureshow_acquisition_plugin", entry)
    if spec is None or spec.loader is None:
        raise ValueError("无法加载采集插件")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    operation = request["operation"]
    credentials = request.get("credentials") or {}
    if operation == "test_connection":
        if not hasattr(module, "test_connection"):
            raise ValueError("插件没有实现连接测试")
        result = module.test_connection(credentials)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    elif operation == "enumerate_pages":
        for page in module.enumerate_pages(
            request["crawl_url"], request.get("parameters") or {},
            credentials, set(request.get("known_external_keys") or []),
            bool(request.get("incremental")),
        ):
            print(json.dumps(page, ensure_ascii=False), flush=True)
    elif operation == "download":
        if not hasattr(module, "download"):
            raise ValueError("插件没有实现媒体下载")
        result = module.download(request["item"], credentials, request["temporary_dir"])
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        raise ValueError("未知插件操作")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"插件执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
