"""视频素材包流式导入导出；来源快照与素材同事务落库。"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
from zipfile import ZipFile, ZIP_STORED

from sqlalchemy import or_, select

from app.core.timezones import shanghai_now
from app.models import (Task, VideoExportJob, VideoItem, VideoPerson, VideoSubtitleTrack)
from app.services.import_spool import cleanup_import
from app.services.provenance import attach_provenance, export_source, imported_snapshot
from app.services.tasks import update_task

from app.services.media_archives import CHUNK, read_json_entry, safe_entry


def _write_object(storage, archive, key: str, name: str) -> tuple[str, int]:
    stream = storage.get_stream(key)
    digest, size = hashlib.sha256(), 0
    try:
        with archive.open(name, "w", force_zip64=True) as target:
            while chunk := stream.read(CHUNK):
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    finally:
        stream.close()
        stream.release_conn()
    return digest.hexdigest(), size


def export_video_package(db, service, job: VideoExportJob) -> None:
    ids = json.loads(job.selection_json)
    result = {"total": len(ids), "processed": 0, "exported": 0, "errors": [], "warnings": []}
    job.status = "running"
    db.commit()
    try:
        with tempfile.TemporaryDirectory(prefix="lensvault-video-export-", dir=package_temp_root(service.settings)) as folder:
            target = Path(folder) / "videos.zip"
            entries = []
            with ZipFile(target, "w", ZIP_STORED, allowZip64=True) as archive:
                for video_id in ids:
                    video = db.scalar(select(VideoItem).where(VideoItem.id == video_id, VideoItem.workspace_id == job.workspace_id))
                    try:
                        if video is None or video.status in {"processing", "processing_failed"}:
                            raise ValueError("视频不存在或正在处理，请稍后重试")
                        suffix = Path(video.filename).suffix or ".mp4"
                        name = f"videos/{video.id}{suffix}"
                        digest, size = _write_object(service.storage, archive, video.object_key, name)
                        entry = {
                            "filename": video.filename, "path": name, "sha256": digest, "size_bytes": size,
                            "title": video.title, "description": video.description, "video_type": video.video_type,
                            "content_type": video.content_type,
                            "category_tags": [link.tag.name for link in video.category_links],
                            "people": [link.person.name for link in video.person_links],
                            "provenance": export_source(video), "subtitles": [],
                        }
                        if video.cover_object_key:
                            cover = f"covers/{video.id}.bin"
                            try:
                                cover_hash, _ = _write_object(service.storage, archive, video.cover_object_key, cover)
                                entry["cover"] = {"path": cover, "sha256": cover_hash, "content_type": video.cover_content_type}
                            except Exception:
                                result["warnings"].append({"id": video_id, "message": "封面读取失败"})
                        for index, track in enumerate(video.subtitle_tracks):
                            if track.status != "ready" or not track.content_vtt:
                                continue
                            path = f"subtitles/{video.id}-{index}.vtt"
                            content = track.content_vtt.encode("utf-8")
                            archive.writestr(path, content)
                            entry["subtitles"].append({"path": path, "sha256": hashlib.sha256(content).hexdigest(),
                                                       "language": track.language, "label": track.label,
                                                       "source_language": track.source_language})
                        entries.append(entry)
                        result["exported"] += 1
                    except Exception as exc:
                        result["errors"].append({"id": video_id, "message": str(exc)[:300]})
                    result["processed"] += 1
                    job.result_json = json.dumps(result, ensure_ascii=False)
                    db.commit()
                archive.writestr("metadata.json", json.dumps({"kind": "video_export", "version": 1,
                                  "exported_at": shanghai_now().isoformat(), "videos": entries,
                                  "report": result}, ensure_ascii=False))
            key = f"workspaces/{job.workspace_id}/video-exports/{job.id}.zip"
            service.storage.put_file(key, target, "application/zip")
            job.object_key = key
            job.filename = f"videos_{job.id}.zip"
            job.expires_at = shanghai_now() + timedelta(hours=24)
            job.status = "ready"
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        result["errors"].append({"message": str(exc)[:300]})
    job.result_json = json.dumps(result, ensure_ascii=False)
    db.commit()


def cleanup_exports(db, storage, workspace_id=None):
    query = select(VideoExportJob).where(VideoExportJob.status == "ready", VideoExportJob.expires_at < shanghai_now())
    if workspace_id is not None:
        query = query.where(VideoExportJob.workspace_id == workspace_id)
    for job in db.scalars(query):
        if job.object_key:
            storage.remove_object(job.object_key)
        job.object_key = None
        job.status = "expired"
    db.commit()


def recover_exports(db, storage):
    for job in db.scalars(select(VideoExportJob).where(VideoExportJob.status.in_(["queued", "running"]))):
        job.status = "failed"
        job.result_json = json.dumps({"errors": [{"message": "服务重启导致导出中断，请重新导出"}]}, ensure_ascii=False)
    db.commit()
    cleanup_exports(db, storage)


def run_export(session_factory, service, job_id):
    with session_factory() as db:
        job = db.get(VideoExportJob, job_id)
        if job and job.status == "queued":
            export_video_package(db, service, job)


def package_temp_root(settings) -> Path:
    """素材包解压与导出的临时根目录；与图库导出一致放在 data_dir 下。"""
    root = Path(settings.data_dir) / "tmp" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_free_space(root: Path, required_bytes: int) -> None:
    if required_bytes <= 0:
        return
    free = shutil.disk_usage(root).free
    if free < required_bytes:
        raise ValueError(f"磁盘剩余空间不足：需要 {required_bytes} 字节，仅剩 {free} 字节")


def _strings(value, maximum):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("分类或人物列表格式无效")
    if any(not isinstance(v, str) or not v.strip() or len(v) > maximum for v in value):
        raise ValueError("分类或人物名称无效")
    return list(dict.fromkeys(v.strip() for v in value))


def _small_file(archive, item, maximum):
    info = safe_entry(archive, item["path"], maximum)
    payload = archive.read(info)
    if hashlib.sha256(payload).hexdigest() != item.get("sha256"):
        raise ValueError("附件哈希校验失败")
    return payload


def _declared_entries(entry):
    """清单中显式引用的压缩包路径（视频、封面、字幕）。"""
    if not isinstance(entry, dict):
        return []
    names = [entry.get("path")]
    cover = entry.get("cover")
    if isinstance(cover, dict):
        names.append(cover.get("path"))
    subtitles = entry.get("subtitles")
    if isinstance(subtitles, list):
        names.extend(track.get("path") for track in subtitles if isinstance(track, dict))
    return [name for name in names if isinstance(name, str) and name]


def scan_package(archive, entries, settings) -> int:
    """解压前校验清单引用的文件：路径、重复引用、大小上限与总占用；返回声明总字节数。"""
    maximum = settings.video_package_max_file_bytes
    used: set[str] = set()
    total = 0
    for entry in entries:
        for name in _declared_entries(entry):
            try:
                info = safe_entry(archive, name, maximum)
            except ValueError:
                # 无效或缺失的引用交给逐条导入报错，不让单个坏条目阻断整包。
                continue
            if info.filename in used:
                raise ValueError("素材包清单重复引用同一文件")
            used.add(info.filename)
            total += info.file_size
    if total > settings.video_package_max_total_bytes:
        raise ValueError("素材包解压总大小超过上限")
    return total


def _check_entry(archive, entry, settings):
    """解压前校验单个视频条目：大小与清单一致，且压缩比不异常。"""
    info = safe_entry(archive, entry["path"], settings.video_package_max_file_bytes)
    declared = entry.get("size_bytes")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 0:
        raise ValueError("视频清单缺少有效大小")
    if info.file_size != declared:
        raise ValueError("视频文件大小与清单不一致")
    if info.compress_size <= 0 or info.file_size / info.compress_size > settings.video_package_max_compression_ratio:
        raise ValueError("素材包压缩比异常")
    return info


def _existing_content(db, service, workspace_id, digest, size):
    existing = db.scalar(select(VideoItem).where(VideoItem.workspace_id == workspace_id,
                          or_(VideoItem.content_sha256 == digest, VideoItem.sha256 == digest)))
    if existing:
        return existing
    # 旧视频的sha256是原始入库哈希，播放优化后可能与对象字节不同。
    candidates = db.scalars(select(VideoItem).where(VideoItem.workspace_id == workspace_id,
                           VideoItem.content_sha256.is_(None), VideoItem.size_bytes == size,
                           VideoItem.status != "processing")).all()
    for video in candidates:
        video.content_sha256 = service.hash_object(video.object_key)
        if video.content_sha256 == digest:
            return video
    return None


def import_video_package(db, service, path, workspace_id, actor_id=None, actor_name=None, progress=None):
    result = {"total": 0, "processed": 0, "imported": 0, "duplicates": 0, "errors": [], "warnings": []}
    settings = service.settings
    root = package_temp_root(settings)
    with ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="lensvault-video-import-", dir=root) as folder:
        infos = archive.infolist()
        if len(infos) > 100000 or len({i.filename for i in infos}) != len(infos):
            raise ValueError("素材包文件数量或重复路径不支持")
        manifest = read_json_entry(archive)
        if not isinstance(manifest, dict) or manifest.get("kind") != "video_export" or manifest.get("version") != 1:
            raise ValueError("不是支持的视频素材包；图片ZIP请在图库导入")
        entries = manifest.get("videos")
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError("视频清单格式无效")
        ensure_free_space(root, scan_package(archive, entries, settings))
        result["total"] = len(entries)
        for index, entry in enumerate(entries):
            object_key = None
            cover_key = None
            video_id = None
            try:
                if not isinstance(entry, dict):
                    raise ValueError("视频条目格式无效")
                source = imported_snapshot(entry.get("provenance"))
                categories = _strings(entry.get("category_tags", []), 128)
                people = _strings(entry.get("people", []), 256)
                filename = entry.get("filename")
                title = entry.get("title")
                if not isinstance(filename, str) or not filename or len(filename) > 512 or not isinstance(title, str) or not title.strip() or len(title) > 256:
                    raise ValueError("视频文件名或标题无效")
                if entry.get("video_type") not in {"short", "long"}:
                    raise ValueError("视频类型无效")
                info = _check_entry(archive, entry, settings)
                digest = hashlib.sha256()
                temporary = Path(folder) / f"{index}{Path(filename).suffix}"
                try:
                    with archive.open(info) as src, temporary.open("wb") as dst:
                        while chunk := src.read(CHUNK):
                            dst.write(chunk)
                            digest.update(chunk)
                    actual_hash = digest.hexdigest()
                    if actual_hash != entry.get("sha256") or temporary.stat().st_size != entry.get("size_bytes"):
                        raise ValueError("视频文件大小或哈希校验失败")
                    if _existing_content(db, service, workspace_id, actual_hash, info.file_size):
                        result["duplicates"] += 1
                        db.commit()
                        continue
                    object_key = service._build_video_object_key(workspace_id, filename)
                    service.storage.put_file(object_key, temporary, entry.get("content_type"))
                    video = service._create_video_from_object(db, workspace_id=workspace_id, title=title,
                        description=entry.get("description"), filename=filename, content_type=entry.get("content_type"),
                        object_key=object_key, size_bytes=info.file_size, expected_sha256=actual_hash, video_type=entry["video_type"])
                    attach_provenance(db, video, source_type="import", actor_id=actor_id, actor_name=actor_name, snapshot=source)
                    service.replace_video_tags(db, video, [], categories)
                    person_ids = []
                    for name in people:
                        person = db.scalar(select(VideoPerson).where(VideoPerson.workspace_id == workspace_id, VideoPerson.name == name))
                        if person is None:
                            person = VideoPerson(workspace_id=workspace_id, name=name)
                            db.add(person)
                            db.flush()
                        person_ids.append(person.id)
                    service.replace_video_people(db, video, person_ids)
                    cover = entry.get("cover")
                    if cover:
                        try:
                            payload = _small_file(archive, cover, 20 * CHUNK)
                            from PIL import Image
                            from io import BytesIO
                            with Image.open(BytesIO(payload)) as image:
                                image.verify()
                            cover_key = f"workspaces/{workspace_id}/videos/covers/{uuid4().hex}"
                            service.storage.put_bytes(cover_key, payload, cover.get("content_type") or "image/jpeg")
                            video.cover_object_key, video.cover_content_type = cover_key, cover.get("content_type") or "image/jpeg"
                        except Exception:
                            result["warnings"].append({"index": index, "message": "封面缺失或无效，已跳过"})
                    languages = set()
                    subtitles = entry.get("subtitles", [])
                    if not isinstance(subtitles, list) or len(subtitles) > 100:
                        raise ValueError("字幕清单格式无效")
                    for track in subtitles:
                        try:
                            content = _small_file(archive, track, 10 * CHUNK).decode("utf-8-sig")
                            language = track["language"]
                            if not isinstance(language, str) or not language or len(language) > 16 or language in languages or not content.lstrip().startswith("WEBVTT"):
                                raise ValueError("字幕格式无效")
                            languages.add(language)
                            db.add(VideoSubtitleTrack(video_id=video.id, language=language, label=str(track.get("label") or language)[:128],
                                source_language=str(track["source_language"])[:32] if track.get("source_language") else None,
                                provider="import", status="ready", content_vtt=content))
                        except Exception:
                            result["warnings"].append({"index": index, "message": "字幕缺失或无效，已跳过"})
                    db.commit()
                    video_id = video.id
                    if service.playback_optimization_needed(temporary, filename):
                        try:
                            service.optimize_video_faststart(video.id, keep_existing_cover=True)
                        except Exception as exc:
                            db.rollback()
                            failed = db.get(VideoItem, video.id)
                            if failed is not None and failed.status in {"uploaded", "processing"}:
                                failed.status = "processing_failed"
                                failed.processing_error = str(exc)[:2000]
                                failed.processed_at = shanghai_now()
                                db.commit()
                            result["warnings"].append({"index": index, "message": f"播放优化失败：{str(exc)[:200]}"})
                    else:
                        video.status = "ready"
                        video.faststart_applied = service._has_faststart_moov(temporary) is True
                        db.commit()
                    result["imported"] += 1
                finally:
                    temporary.unlink(missing_ok=True)
            except Exception as exc:
                db.rollback()
                if object_key and video_id is None:
                    service.storage.remove_object(object_key)
                if cover_key and video_id is None:
                    service.storage.remove_object(cover_key)
                result["errors"].append({"index": index, "message": str(exc)[:300]})
            finally:
                result["processed"] += 1
                if progress:
                    progress(result)
    return result


def run_import(session_factory, service, task_id, path):
    with session_factory() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        try:
            update_task(db, task.id, status="running", message="正在读取视频素材包")
            def progress(result):
                update_task(db, task.id, progress=result["processed"] / max(result["total"], 1),
                            result_json=json.dumps(result, ensure_ascii=False),
                            message=f"正在导入视频 {result['processed']}/{result['total']}")
            result = import_video_package(db, service, path, task.workspace_id, task.created_by, task.actor_name, progress)
            update_task(db, task.id, status="completed", progress=1.0, result_json=json.dumps(result, ensure_ascii=False),
                        message=f"导入完成：新增 {result['imported']}，重复 {result['duplicates']}，失败 {len(result['errors'])}")
        except Exception as exc:
            db.rollback()
            update_task(db, task.id, status="failed", message=str(exc)[:500])
        finally:
            cleanup_import(service.settings, task_id)
