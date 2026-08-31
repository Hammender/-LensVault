from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.telegram import extract_hashtags, media_matches


class TelegramAcquisitionTests(unittest.TestCase):
    def test_extract_hashtags_deduplicates_normalized_values(self) -> None:
        tags = extract_hashtags("#旅行 今天的 #旅行 #Tokyo")
        self.assertEqual(tags, [("旅行", "旅行"), ("Tokyo", "tokyo")])

    def test_media_filters_require_every_tag_and_keyword(self) -> None:
        published = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
        tags = extract_hashtags("东京旅行 #旅行 #Tokyo")
        self.assertTrue(media_matches(
            published_at=published,
            media_type="image",
            caption="东京旅行 #旅行 #Tokyo",
            hashtags=tags,
            date_from=datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc),
            date_to=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
            allowed_media_types={"image"},
            required_hashtags=["旅行", "#tokyo"],
            required_keywords=["东京", "旅行"],
        ))
        self.assertFalse(media_matches(
            published_at=published,
            media_type="image",
            caption="东京旅行 #旅行 #Tokyo",
            hashtags=tags,
            date_from=None,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=["缺失"],
            required_keywords=["东京"],
        ))
