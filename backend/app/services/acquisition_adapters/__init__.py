import shutil
import subprocess
import time
from urllib.request import urlopen

from .contracts import (
    AccessBlockedError,
    RemoteItem,
    RemotePage,
    ScriptDefinition,
    ScriptParameter,
    SourceAdapter,
    max_pages_from,
    stable_key,
)
from .http import _RequestStartLimiter, _request_bytes, curl_request_bytes, is_tls_transport_error
from .registry import SCRIPT_REGISTRY, get_script, script_catalog

__all__ = [
    "AccessBlockedError", "RemoteItem", "RemotePage",
    "SCRIPT_REGISTRY", "ScriptDefinition", "ScriptParameter", "SourceAdapter",
    "_RequestStartLimiter", "_request_bytes", "curl_request_bytes", "get_script",
    "is_tls_transport_error", "max_pages_from", "script_catalog", "stable_key",
]

# http.curl_request_bytes 通过包属性调用这些名称，测试也按包路径打桩。
_ = (shutil, subprocess, time, urlopen)
