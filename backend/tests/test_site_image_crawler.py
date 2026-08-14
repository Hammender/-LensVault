from backend.scripts.site_image_crawler import (
    SiteImageCrawler,
    build_page_urls,
    parse_detail_page,
    parse_listing_page,
)


def test_saved_listing_page_extracts_posts_and_all_pages() -> None:
    html = """
    <div class="grid grid-show">
      <article class="post"><a href="/post/153740/"><img src="/files/thumb/a.jpg"></a></article>
      <article class="post"><a href="https://xxx.com/post/153050/">详情</a></article>
    </div>
    <div class="page-pagination"><ul class="pagination">
      <li><a class="page-link" href="/idols/iu/page/1/">1</a></li>
      <li><a class="page-link" href="/idols/iu/page/4/">4</a></li>
      <li><a class="page-link" href="/idols/iu/page/275/">末页</a></li>
    </ul></div>
    """
    page_url = "https://xxx.com/idols/iu/page/3/"

    posts, pagination = parse_listing_page(html, page_url)
    pages = build_page_urls(page_url, pagination)

    assert posts == [
        "https://xxx.com/post/153740/",
        "https://xxx.com/post/153050/",
    ]
    assert len(pages) == 275
    assert pages[0] == "https://xxx.com/idols/iu/page/1/"
    assert pages[-1] == "https://xxx.com/idols/iu/page/275/"


def test_saved_detail_page_extracts_original_images_only() -> None:
    html = """
    <div class="post-media">
      <a class="post-media-item" href="./IU_files/first.jpg">
        <img src="./IU_files/first.jpg" alt="image">
      </a>
      <a class="post-media-item" href="./IU_files/second.jpg">
        <img src="./IU_files/second.jpg" data-src="//media.xxx.com/files/src/second.jpg" alt="image">
      </a>
    </div>
    <div class="post-thumbs"><img class="post-thumb" src="/files/thumb/first.jpg"></div>
    """

    images = parse_detail_page(html, "https://xxx.com/post/153280/")

    assert images == [
        "https://media.xxx.com/files/src/first.jpg",
        "https://media.xxx.com/files/src/second.jpg",
    ]
    assert all("/files/thumb/" not in image for image in images)


def test_detail_parser_ignores_video_items_and_thumbnails() -> None:
    html = """
    <div class="post-media">
      <a class="post-media-item">
        <video><source src="/files/src/movie.mp4"></video>
        <img src="/files/src/movie-poster.jpg">
      </a>
      <a class="post-media-item"><img data-src="//media.example/files/src/photo.webp"></a>
    </div>
    <div class="post-thumbs"><img class="post-thumb" src="/files/thumb/photo.webp"></div>
    """

    images = parse_detail_page(html, "https://example.com/post/42/")

    assert images == ["https://media.example/files/src/photo.webp"]


def test_crawler_downloads_images_across_pages_and_skips_videos(tmp_path, monkeypatch) -> None:
    start_url = "https://example.com/idols/iu/"
    responses = {
        start_url: """
            <article class="post"><a href="/post/1/">一</a></article>
            <div class="page-pagination">
              <a class="page-link" href="/idols/iu/page/1/">1</a>
              <a class="page-link" href="/idols/iu/page/2/">2</a>
            </div>
        """,
        "https://example.com/idols/iu/page/2/": (
            '<article class="post"><a href="/post/2/">二</a></article>'
        ),
        "https://example.com/post/1/": (
            '<div class="post-media"><a class="post-media-item">'
            '<img src="//media.example.com/files/src/photo.jpg">'
            "</a></div>"
        ),
        "https://example.com/post/2/": (
            '<div class="post-media"><a class="post-media-item">'
            '<video><source src="//media.example.com/files/src/movie.mp4"></video>'
            "</a></div>"
        ),
    }
    requested_urls: list[str] = []

    def fake_request(url: str, *, referer: str):
        requested_urls.append(url)
        if url == "https://media.example.com/files/src/photo.jpg":
            return b"image payload", "image/jpeg", None
        return responses[url].encode(), "text/html", "utf-8"

    crawler = SiteImageCrawler(tmp_path, workers=2)
    monkeypatch.setattr(crawler, "_request", fake_request)

    summary = crawler.crawl(start_url)

    assert summary.page_count == 2
    assert summary.post_count == 2
    assert summary.image_count == 1
    assert summary.downloaded_count == 1
    assert summary.failed_count == 0
    assert "https://example.com/idols/iu/page/1/" not in requested_urls
    assert (tmp_path / "1" / "001_photo.jpg").read_bytes() == b"image payload"
