from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class AdapterManifest:
    adapter_id: str
    version: str
    model_label: str
    default_filename: str | None
    input_width: int
    input_height: int
    input_layout: str
    input_color: str
    input_range: str
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    alignment: str
    keypoint_order: str
    output_dimension: int
    output_normalization: str
    supports_flip_tta: bool
    license_name: str
    license_url: str
    license_note: str
    model_source_url: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_INSIGHTFACE = AdapterManifest(
    adapter_id="buffalo_l",
    version="1",
    model_label="InsightFace buffalo_l w600k_r50",
    default_filename="w600k_r50.onnx",
    input_width=112,
    input_height=112,
    input_layout="NCHW",
    input_color="RGB",
    input_range="[-1,1]",
    mean=(127.5, 127.5, 127.5),
    std=(127.5, 127.5, 127.5),
    alignment="insightface-arcface-112-v1",
    keypoint_order="left-eye,right-eye,nose,left-mouth,right-mouth",
    output_dimension=512,
    output_normalization="l2",
    supports_flip_tta=True,
    license_name="InsightFace 非商业研究模型许可",
    license_url="https://github.com/deepinsight/insightface/tree/master/model_zoo",
    license_note="InsightFace 模型权重仅限非商业研究用途。",
    model_source_url="https://github.com/deepinsight/insightface/tree/master/model_zoo",
)


_ANTELOPEV2 = AdapterManifest(
    adapter_id="antelopev2",
    version="1",
    model_label="InsightFace antelopev2 glintr100",
    default_filename="glintr100.onnx",
    input_width=112,
    input_height=112,
    input_layout="NCHW",
    input_color="RGB",
    input_range="[-1,1]",
    mean=(127.5, 127.5, 127.5),
    std=(127.5, 127.5, 127.5),
    alignment="insightface-arcface-112-v1",
    keypoint_order="left-eye,right-eye,nose,left-mouth,right-mouth",
    output_dimension=512,
    output_normalization="l2",
    supports_flip_tta=True,
    license_name="InsightFace 非商业研究模型许可",
    license_url="https://github.com/deepinsight/insightface/tree/master/model_zoo",
    license_note="InsightFace 模型权重仅限非商业研究用途。",
    model_source_url="https://github.com/deepinsight/insightface/tree/master/model_zoo",
)


_ADAFACE_R101 = AdapterManifest(
    adapter_id="adaface-r101",
    version="1",
    model_label="AdaFace IR-101 WebFace12M ONNX export",
    default_filename=None,
    input_width=112,
    input_height=112,
    input_layout="NCHW",
    input_color="BGR",
    input_range="[-1,1]",
    mean=(127.5, 127.5, 127.5),
    std=(127.5, 127.5, 127.5),
    alignment="insightface-arcface-112-v1",
    keypoint_order="left-eye,right-eye,nose,left-mouth,right-mouth",
    output_dimension=512,
    output_normalization="l2",
    supports_flip_tta=True,
    license_name="AdaFace MIT 代码与模型仓库许可（权重来源需单独核对）",
    license_url="https://github.com/mk-minchul/AdaFace",
    license_note="AdaFace 官方实现针对低质量人脸；本实验使用公开 ONNX 导出权重。",
    model_source_url="https://github.com/yakhyo/adaface-onnx/releases",
)


def _lvface(adapter_id: str, size: str) -> AdapterManifest:
    return AdapterManifest(
        adapter_id=adapter_id,
        version="1",
        model_label=f"LVFace-{size}",
        default_filename=None,
        input_width=112,
        input_height=112,
        input_layout="NCHW",
        input_color="RGB",
        input_range="[-1,1]",
        mean=(127.5, 127.5, 127.5),
        std=(127.5, 127.5, 127.5),
        alignment="insightface-arcface-112-v1",
        keypoint_order="left-eye,right-eye,nose,left-mouth,right-mouth",
        output_dimension=512,
        output_normalization="l2",
        supports_flip_tta=True,
        license_name="LVFace 非商业研究模型许可",
        license_url="https://github.com/bytedance/LVFace",
        license_note="LVFace 模型权重仅限非商业研究用途。",
        model_source_url="https://github.com/bytedance/LVFace",
    )


ADAPTERS: dict[str, AdapterManifest] = {
    "buffalo_l": _INSIGHTFACE,
    "antelopev2": _ANTELOPEV2,
    "adaface-r101": _ADAFACE_R101,
    "lvface-t": _lvface("lvface-t", "T"),
    "lvface-s": _lvface("lvface-s", "S"),
    "lvface-b": _lvface("lvface-b", "B"),
}


def available_adapters() -> tuple[str, ...]:
    return tuple(sorted(ADAPTERS))


def model_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_model_path(manifest: AdapterManifest, model_path: Path | None, detector_pack: str) -> Path:
    if model_path is not None:
        resolved = model_path.expanduser().resolve()
    elif manifest.default_filename is not None:
        resolved = Path.home() / ".insightface" / "models" / detector_pack / manifest.default_filename
    else:
        raise RuntimeError(f"适配器 {manifest.adapter_id} 必须通过 --model-path 指定官方 ONNX 文件。")
    if not resolved.is_file():
        raise RuntimeError(f"识别模型不存在：{resolved}")
    return resolved


class OnnxFaceAdapter:
    def __init__(
        self,
        manifest: AdapterManifest,
        model_path: Path,
        providers: list[str],
        *,
        session: object | None = None,
    ) -> None:
        self.manifest = manifest
        self.model_path = model_path
        self.model_sha256 = model_sha256(model_path)
        if session is None:
            try:
                import onnxruntime as ort
            except Exception as exc:
                raise RuntimeError("ONNX Runtime 未安装或加载失败。") from exc
            session = ort.InferenceSession(str(model_path), providers=providers)
        self.session = session
        inputs = self.session.get_inputs()  # type: ignore[attr-defined]
        outputs = self.session.get_outputs()  # type: ignore[attr-defined]
        if len(inputs) != 1 or not outputs:
            raise RuntimeError("识别 ONNX 必须只有一个图像输入并至少有一个输出。")
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        self.providers = list(self.session.get_providers())  # type: ignore[attr-defined]
        self._validate_contract(inputs[0].shape, outputs[0].shape)

    def _validate_contract(self, input_shape: list[object], output_shape: list[object]) -> None:
        expected = [None, 3, self.manifest.input_height, self.manifest.input_width]
        if len(input_shape) != len(expected) or any(
            actual != wanted
            for actual, wanted in zip(input_shape, expected, strict=True)
            if wanted is not None
        ):
            raise RuntimeError(f"模型输入形状与适配器不一致：actual={input_shape}, expected={expected}")
        if not output_shape or output_shape[-1] != self.manifest.output_dimension:
            raise RuntimeError(
                f"模型输出维度与适配器不一致：actual={output_shape}, expected={self.manifest.output_dimension}"
            )

    def preprocess(self, aligned_bgr: np.ndarray) -> np.ndarray:
        import cv2

        expected_size = (self.manifest.input_width, self.manifest.input_height)
        image = cv2.resize(aligned_bgr, expected_size) if aligned_bgr.shape[1::-1] != expected_size else aligned_bgr
        if self.manifest.input_color == "RGB":
            image = image[:, :, ::-1]
        array = image.astype(np.float32)
        mean = np.asarray(self.manifest.mean, dtype=np.float32)
        std = np.asarray(self.manifest.std, dtype=np.float32)
        array = (array - mean) / std
        return np.ascontiguousarray(array.transpose(2, 0, 1)[None, ...])

    def embed_aligned(self, aligned_bgr: np.ndarray, *, flip_tta: bool) -> np.ndarray:
        if flip_tta and not self.manifest.supports_flip_tta:
            raise RuntimeError(f"适配器 {self.manifest.adapter_id} 不支持翻转 TTA。")
        images = [aligned_bgr]
        if flip_tta:
            images.append(np.ascontiguousarray(aligned_bgr[:, ::-1]))
        batch = np.concatenate([self.preprocess(image) for image in images], axis=0)
        output = np.asarray(
            self.session.run([self.output_name], {self.input_name: batch})[0],  # type: ignore[attr-defined]
            dtype=np.float32,
        )
        if output.ndim == 1:
            output = output[None, ...]
        output = output.reshape(output.shape[0], -1)
        if output.shape != (len(images), self.manifest.output_dimension):
            raise RuntimeError(
                f"识别模型输出形状异常：actual={output.shape}, expected=({len(images)}, {self.manifest.output_dimension})"
            )
        vector = output.sum(axis=0)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 1e-12:
            raise RuntimeError("识别模型输出了无效的零向量或非有限向量。")
        return np.asarray(vector / norm, dtype=np.float32)

    def report_metadata(self) -> dict[str, Any]:
        return {
            **self.manifest.as_dict(),
            "model_path": str(self.model_path),
            "model_sha256": self.model_sha256,
            "providers": self.providers,
        }


def create_adapter(
    adapter_id: str,
    *,
    model_path: Path | None,
    detector_pack: str,
    providers: list[str],
    session: object | None = None,
    create_session: Callable[..., Any] | None = None,
) -> OnnxFaceAdapter:
    try:
        manifest = ADAPTERS[adapter_id]
    except KeyError as exc:
        raise RuntimeError(f"未知适配器：{adapter_id}；可用值：{', '.join(available_adapters())}") from exc
    resolved = _resolve_model_path(manifest, model_path, detector_pack)
    if session is None and create_session is not None:
        session = create_session(resolved, providers=providers)
    return OnnxFaceAdapter(manifest, resolved, providers, session=session)
