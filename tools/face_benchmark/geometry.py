from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol, Sequence


FACE_CROP_PADDING_RATIO = 0.35
TARGET_SELECTION_POLICY = "target-bbox-v1"
MIN_TARGET_IOU = 0.20

BBox = tuple[float, float, float, float]


class DetectionLike(Protocol):
    bbox: Sequence[float]


@dataclass(frozen=True)
class TargetSelection:
    index: int | None
    iou: float | None
    method: str


def parse_bbox(value: str | Sequence[object]) -> BBox:
    payload: Any = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, (list, tuple)) or len(payload) != 4:
        raise ValueError("身份题缺少有效的目标人脸框。")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in payload):
        raise ValueError("身份题目标人脸框坐标无效。")
    left, top, right, bottom = (float(item) for item in payload)
    if right <= left or bottom <= top:
        raise ValueError("身份题目标人脸框尺寸无效。")
    return left, top, right, bottom


def face_crop_box(bbox: BBox, image_width: int, image_height: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    padding = max(right - left, bottom - top) * FACE_CROP_PADDING_RATIO
    return (
        max(0, int(left - padding)),
        max(0, int(top - padding)),
        min(image_width, int(right + padding)),
        min(image_height, int(bottom + padding)),
    )


def target_bbox_in_crop(bbox: BBox) -> BBox:
    left, top, right, bottom = bbox
    padding = max(right - left, bottom - top) * FACE_CROP_PADDING_RATIO
    crop_left = max(0, int(left - padding))
    crop_top = max(0, int(top - padding))
    return left - crop_left, top - crop_top, right - crop_left, bottom - crop_top


def bbox_iou(first: BBox, second: BBox) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection == 0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def select_target_detection(
    detections: Sequence[DetectionLike],
    target_bbox: BBox,
    *,
    min_iou: float = MIN_TARGET_IOU,
) -> TargetSelection:
    if not detections:
        return TargetSelection(None, None, "target_not_detected")
    center_x = (target_bbox[0] + target_bbox[2]) / 2
    center_y = (target_bbox[1] + target_bbox[3]) / 2
    scored = [
        (index, bbox_iou(tuple(float(value) for value in detection.bbox), target_bbox))
        for index, detection in enumerate(detections)
    ]
    containing = [
        (index, iou)
        for index, iou in scored
        if detections[index].bbox[0] <= center_x <= detections[index].bbox[2]
        and detections[index].bbox[1] <= center_y <= detections[index].bbox[3]
    ]
    if containing:
        index, iou = max(containing, key=lambda item: (item[1], -item[0]))
        return TargetSelection(index, iou, "contains_target_center")
    index, iou = max(scored, key=lambda item: (item[1], -item[0]))
    if iou >= min_iou:
        return TargetSelection(index, iou, "iou_fallback")
    return TargetSelection(None, iou, "target_not_detected")
