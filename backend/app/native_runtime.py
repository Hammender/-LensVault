from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any
import os


_ENV_THREAD_KEYS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
_DEFAULT_LIBRARY_THREADS = 4
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

_opencv_configured = False
_opencv_lock = Lock()
_insightface_patch_lock = Lock()
_threadpool_controller: Any = None
_environment_applied = False


def _parse_positive_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 1 else None


def _dotenv_value(key: str) -> str | None:
    if not _ENV_FILE.is_file():
        return None
    prefix = f"{key}="
    for raw_line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        return line.split("=", 1)[1].strip()
    return None


def read_library_thread_count() -> int:
    value = _parse_positive_int(os.environ.get("IMAGE_COMPUTE_LIBRARY_THREADS"))
    if value is not None:
        return value
    value = _parse_positive_int(_dotenv_value("IMAGE_COMPUTE_LIBRARY_THREADS"))
    return value if value is not None else _DEFAULT_LIBRARY_THREADS


def apply_native_thread_environment() -> int:
    """在导入 NumPy / OpenCV / ONNX 之前写入环境变量。本函数不得 import 图像栈。"""
    global _environment_applied
    thread_count = read_library_thread_count()
    os.environ["IMAGE_COMPUTE_LIBRARY_THREADS"] = str(thread_count)
    for key in _ENV_THREAD_KEYS:
        os.environ.setdefault(key, str(thread_count))
    _environment_applied = True
    return thread_count


def create_onnx_session_options(thread_count: int | None = None) -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = thread_count or read_library_thread_count()
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return options


def create_onnx_inference_session(
    model_path: str | Path,
    *,
    providers: list[str],
    provider_options: list[dict[str, Any]] | None = None,
) -> Any:
    import onnxruntime as ort

    kwargs: dict[str, Any] = {
        "sess_options": create_onnx_session_options(),
        "providers": list(providers),
    }
    if provider_options is not None:
        kwargs["provider_options"] = provider_options
    return ort.InferenceSession(str(model_path), **kwargs)


def configure_opencv_threads(thread_count: int | None = None) -> None:
    global _opencv_configured
    resolved = thread_count or read_library_thread_count()
    with _opencv_lock:
        if _opencv_configured:
            return
        import cv2

        cv2.setNumThreads(resolved)
        _opencv_configured = True


def configure_blas_threads(thread_count: int | None = None) -> None:
    global _threadpool_controller
    if _threadpool_controller is not None:
        return
    try:
        import threadpoolctl
    except ImportError as exc:
        raise RuntimeError("threadpoolctl 未安装，无法限制 NumPy/OpenBLAS 线程。") from exc
    resolved = thread_count or read_library_thread_count()
    controller = threadpoolctl.threadpool_limits(limits=resolved)
    controller.__enter__()
    _threadpool_controller = controller


@contextmanager
def insightface_session_options() -> Iterator[None]:
    """在 FaceAnalysis 构造期间把 SessionOptions 注入检测会话，构造结束后恢复原类。"""
    try:
        from insightface.model_zoo import model_zoo as insightface_model_zoo
    except Exception:
        yield
        return

    original = insightface_model_zoo.PickableInferenceSession
    options = create_onnx_session_options()

    class SessionWithOptions(original):  # type: ignore[valid-type,misc]
        def __init__(self, model_path: str, **kwargs: Any) -> None:
            kwargs.setdefault("sess_options", options)
            super().__init__(model_path, **kwargs)

    with _insightface_patch_lock:
        insightface_model_zoo.PickableInferenceSession = SessionWithOptions
        try:
            yield
        finally:
            insightface_model_zoo.PickableInferenceSession = original


def configure_native_compute_runtime(thread_count: int | None = None) -> int:
    """人脸 warmup 前调用：环境变量、OpenCV、OpenBLAS。ONNX 选项在会话创建时注入。"""
    resolved = thread_count or apply_native_thread_environment()
    configure_opencv_threads(resolved)
    configure_blas_threads(resolved)
    return resolved
