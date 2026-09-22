from __future__ import annotations

from app.tools.summarize_gallery_rerecognition import analyze_audit_rows, source_aware_photo_stats


def _plan(photo_id: int, old_tags: list[dict[str, object]], new_known: list[int], *, faces: int = 1, category: str = "auto_equal") -> dict[str, object]:
    return {
        "gallery_photo_id": photo_id,
        "category": category,
        "old_tags": old_tags,
        "current_known_person_ids": new_known,
        "old_face_count": faces,
        "current_face_count": faces,
    }


def test_source_aware_stats_split_auto_loss_and_manual_recovery() -> None:
    stats = source_aware_photo_stats(
        [
            _plan(1, [{"person_id": 10, "source": "auto"}], [10]),
            _plan(2, [{"person_id": 10, "source": "auto"}], [], category="auto_conflict"),
            _plan(3, [{"person_id": 20, "source": "manual"}], [20], category="preserved_sources_equal"),
            _plan(4, [{"person_id": 20, "source": "manual"}], [], faces=0, category="preserved_sources_conflict"),
            _plan(5, [{"person_id": 30, "source": "face_manual"}], [30], category="preserved_sources_equal"),
        ]
    )
    assert stats["lost_tags_by_source"] == {"auto": 1, "manual": 1}
    assert stats["kept_tags_by_source"] == {"auto": 1, "manual": 1, "face_manual": 1}
    assert stats["photos_lost_auto"] == 1
    assert stats["photos_lost_manual"] == 1
    assert stats["manual_photos"] == 3
    assert stats["manual_photos_any_auto_matched"] == 2
    assert stats["manual_photos_all_auto_matched"] == 2
    assert stats["manual_photos_none_auto_matched"] == 1
    assert stats["manual_photos_no_old_face"] == 1
    assert stats["manual_person_tags_auto_matched"] == 2
    assert stats["manual_person_tags_auto_matched_by_source"] == {"manual": 1, "face_manual": 1}


def test_audit_known_to_unknown_uses_old_tag_source() -> None:
    bbox = [0, 0, 10, 10]
    stats = analyze_audit_rows(
        [
            {
                "status": "success",
                "gallery_photo_id": 1,
                "before": {
                    "person_tags": [{"person_id": 10, "source": "auto"}],
                    "faces": [{"bbox": bbox, "matched_person_id": 10, "needs_review": False}],
                },
                "after": {
                    "person_tags": [{"person_id": 99, "source": "unknown"}],
                    "faces": [
                        {
                            "bbox": bbox,
                            "matched_person_id": 99,
                            "predicted_person_id": None,
                            "needs_review": True,
                        }
                    ],
                },
            },
            {
                "status": "success",
                "gallery_photo_id": 2,
                "before": {
                    "person_tags": [{"person_id": 20, "source": "manual"}],
                    "faces": [{"bbox": bbox, "matched_person_id": 20, "needs_review": False}],
                },
                "after": {
                    "person_tags": [{"person_id": 99, "source": "unknown"}],
                    "faces": [
                        {
                            "bbox": bbox,
                            "matched_person_id": 99,
                            "predicted_person_id": None,
                            "needs_review": True,
                        }
                    ],
                },
            },
        ]
    )
    assert stats["known_to_unknown_by_source"] == {"auto": 1, "manual": 1}
    assert stats["known_to_unknown_total"] == 2


def test_audit_counts_true_lift_when_old_auto_failed() -> None:
    stats = analyze_audit_rows(
        [
            {
                "status": "success",
                "gallery_photo_id": 8,
                "before": {
                    "person_tags": [{"person_id": 20, "source": "manual"}],
                    "faces": [{"bbox": [0, 0, 10, 10], "matched_person_id": None, "needs_review": True}],
                },
                "after": {
                    "person_tags": [{"person_id": 20, "source": "auto"}],
                    "faces": [
                        {
                            "bbox": [0, 0, 10, 10],
                            "matched_person_id": 20,
                            "predicted_person_id": 20,
                            "needs_review": False,
                        }
                    ],
                },
            }
        ]
    )
    assert stats["manual_photos_old_auto_failed_now_matched"] == 1
    assert stats["manual_photos_true_lift"] == 1
    assert stats["manual_photos_old_already_matched"] == 0
