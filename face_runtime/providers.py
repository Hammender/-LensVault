from __future__ import annotations

from collections.abc import Iterable


PROVIDER_BY_MODE = {
    "cpu": "CPUExecutionProvider",
    "coreml": "CoreMLExecutionProvider",
    "cuda": "CUDAExecutionProvider",
}


def _available_providers() -> set[str]:
    try:
        import onnxruntime as ort
    except Exception as exc:
        raise RuntimeError("ONNX Runtime 未安装或加载失败。") from exc
    return set(ort.get_available_providers())


def resolve_provider_mode(mode: str, available: Iterable[str] | None = None) -> list[str]:
    available_set = set(available) if available is not None else _available_providers()
    if mode == "auto":
        for candidate in ("cuda", "coreml", "cpu"):
            provider = PROVIDER_BY_MODE[candidate]
            if provider in available_set:
                return [provider] if candidate == "cpu" else [provider, "CPUExecutionProvider"]
        raise RuntimeError(f"没有可用的 ONNX Runtime Provider：{sorted(available_set)}")
    if mode not in PROVIDER_BY_MODE:
        raise RuntimeError(f"未知 Provider 模式：{mode}")
    primary = PROVIDER_BY_MODE[mode]
    if primary not in available_set:
        raise RuntimeError(f"显式选择的 {primary} 不可用，实际 Provider：{sorted(available_set)}")
    return [primary] if mode == "cpu" else [primary, "CPUExecutionProvider"]


def validate_configured_providers(
    configured: Iterable[str],
    *,
    require_primary: bool,
    available: Iterable[str] | None = None,
) -> list[str]:
    requested = [item.strip() for item in configured if item.strip()]
    if not requested:
        raise RuntimeError("FACE_EXECUTION_PROVIDERS 必须至少配置一个 Provider。")
    available_set = set(available) if available is not None else _available_providers()
    if require_primary and requested[0] not in available_set:
        raise RuntimeError(
            f"要求的首选 Provider 不可用：{requested[0]}；实际 Provider：{sorted(available_set)}"
        )
    usable = [provider for provider in requested if provider in available_set]
    if not usable:
        raise RuntimeError(
            f"配置的 Provider 均不可用：{requested}；实际 Provider：{sorted(available_set)}"
        )
    return usable
