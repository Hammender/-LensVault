from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    from app.services.acquisition import AcquisitionService
    from app.services.face import FaceService
    from app.services.importer import PictureService
    from app.services.ocr import OcrService
    from app.services.qdrant import QdrantVectorStore
    from app.services.storage import MinioStorage
    from app.services.similarity import GallerySimilarityScanner
    from app.services.subtitles import SubtitleService
    from app.services.videos import VideoService


@dataclass(frozen=True)
class ServiceContainer:
    storage: MinioStorage
    face: FaceService
    vector_store: QdrantVectorStore
    ocr: OcrService
    pictures: PictureService
    videos: VideoService
    subtitles: SubtitleService
    similarity: GallerySimilarityScanner
    acquisition: AcquisitionService


def build_service_container(settings: Settings) -> ServiceContainer:
    from app.services.acquisition import AcquisitionService
    from app.services.face import FaceService
    from app.services.importer import PictureService
    from app.services.ocr import OcrService
    from app.services.qdrant import QdrantVectorStore
    from app.services.storage import MinioStorage
    from app.services.similarity import GallerySimilarityScanner
    from app.services.subtitles import SubtitleService
    from app.services.videos import VideoService

    storage = MinioStorage(settings)
    face = FaceService(settings)
    vector_store = QdrantVectorStore(settings)
    ocr = OcrService()
    pictures = PictureService(storage, face, vector_store, ocr, settings)
    similarity = GallerySimilarityScanner(storage, vector_store, settings)
    return ServiceContainer(
        storage=storage,
        face=face,
        vector_store=vector_store,
        ocr=ocr,
        pictures=pictures,
        videos=VideoService(storage),
        subtitles=SubtitleService(storage, settings),
        similarity=similarity,
        acquisition=AcquisitionService(
            storage,
            pictures,
            settings,
            similarity.extractor,
            similarity,
        ),
    )
