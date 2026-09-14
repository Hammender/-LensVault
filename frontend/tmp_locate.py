from pathlib import Path

p = Path(r"E:\code\PictureShow\frontend\src\ApplicationContent.tsx")
lines = p.read_text(encoding="utf-8").splitlines()
print("total", len(lines))
needles = [
    "const GalleryPageComponent",
    "const PeoplePageComponent",
    "const renderUploadPage",
    "const renderVideoUploadModal",
    "const renderVideosPage",
    "const navItems",
    'page === "video-play"',
    "isVideoEditModalOpen",
    "isCategoryManageModalOpen",
    "isVideoPersonManageModalOpen",
    "galleryExportModalOpen",
]
for i, line in enumerate(lines, 1):
    if any(n in line for n in needles):
        print(f"{i}: {line[:100]}")
