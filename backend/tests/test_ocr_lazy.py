from app.services.ocr import OcrService


def test_ocr_service_does_not_load_models_on_init() -> None:
    service = OcrService()

    status = service.engine_status()

    assert service._rapid_ocr is None
    assert service._rapid_ocr_attempted is False
    assert service._tesseract_checked is False
    assert status["rapidocr_ready"] is False
    assert status["tesseract_ready"] is False
