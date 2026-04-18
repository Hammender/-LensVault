from __future__ import annotations

import logging
import re
from io import BytesIO

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OcrService:
    def __init__(self) -> None:
        self._rapid_ocr = None
        self._rapid_ocr_load_err: str | None = None
        self._tesseract_ready = False
        self._tesseract_err: str | None = None
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            self._rapid_ocr = RapidOCR()
            logger.info("OCR engine ready: RapidOCR")
        except Exception as exc:  # pragma: no cover - optional dependency
            self._rapid_ocr_load_err = str(exc)
            logger.warning("RapidOCR unavailable, fallback to pytesseract. reason=%s", exc)
        try:
            import pytesseract  # type: ignore

            _ = pytesseract.get_tesseract_version()
            self._tesseract_ready = True
            logger.info("OCR engine ready: Tesseract")
        except Exception as exc:  # pragma: no cover - optional dependency
            self._tesseract_ready = False
            self._tesseract_err = str(exc)
            logger.warning("Tesseract unavailable. reason=%s", exc)

    def engine_status(self) -> dict[str, str | bool]:
        return {
            "rapidocr_ready": self._rapid_ocr is not None,
            "rapidocr_error": self._rapid_ocr_load_err or "",
            "tesseract_ready": self._tesseract_ready,
            "tesseract_error": self._tesseract_err or "",
        }

    def extract_text(self, payload: bytes) -> str | None:
        if self._rapid_ocr is None and not self._tesseract_ready:
            logger.error("OCR skipped: no available OCR engines")
            return None
        text = self._extract_with_rapidocr(payload)
        if text is None:
            text = self._extract_with_tesseract(payload)
        cleaned = self._clean_text(text or "")
        return cleaned or None

    def _extract_with_rapidocr(self, payload: bytes) -> str | None:
        if self._rapid_ocr is None:
            return None
        try:
            image = np.array(Image.open(BytesIO(payload)).convert("RGB"))
            result, _ = self._rapid_ocr(image)
            if not result:
                return None
            lines = [str(item[1]) for item in result if len(item) > 1 and item[1]]
            return "\n".join(lines).strip() or None
        except Exception:
            logger.exception("RapidOCR extraction failed")
            return None

    def _extract_with_tesseract(self, payload: bytes) -> str | None:
        if not self._tesseract_ready:
            return None
        try:
            import pytesseract  # type: ignore

            image = Image.open(BytesIO(payload)).convert("RGB")
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            return text.strip() or None
        except Exception:
            logger.exception("Tesseract extraction failed")
            return None

    def _clean_text(self, text: str) -> str:
        value = text.replace("\r", " ").replace("\n", " ")
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(r"(.)\1{3,}", r"\1\1", value)
        return value
