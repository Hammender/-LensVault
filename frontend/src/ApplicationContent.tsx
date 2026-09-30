import { useEffect, useRef, useState } from "react";
import { ArrowUp, BarChart3, Clapperboard, FolderSync, GalleryHorizontalEnd, HomeIcon, LogOut, ScanSearch, Settings, UploadCloud, UsersRound } from "lucide-react";

import AcquisitionCenter from "./pages/AcquisitionCenter";
import WorkspacePanel from "./components/WorkspacePanel";
import { useConfirm } from "./components/ConfirmDialog";
import Home from "./pages/Home";
import { useCatalog } from "./hooks/useCatalog";
import { useGallery } from "./hooks/useGallery";
import { usePeople, type PeopleModel } from "./hooks/usePeople";
import { useUpload } from "./hooks/useUpload";
import { useVideos } from "./hooks/useVideos";
import { hasPermission } from "./lib/permissions";
import GalleryPage from "./pages/GalleryPage";
import PeoplePage from "./pages/PeoplePage";
import UploadPage from "./pages/UploadPage";
import VideoPlayPage from "./pages/VideoPlayPage";
import VideosPage from "./pages/VideosPage";
import { routeFromHash, setRoute, type PageKey } from "./lib/routing";
import SimilarityReview from "./pages/SimilarityReview";
import Statistics from "./pages/Statistics";
import type { AuthSession } from "./types";

type MainAppProps = {
  authSession: AuthSession;
  onLogout: () => void;
  onSessionChange: (session: AuthSession) => void;
};

const navItems = [
  { key: "home", label: "首页", Icon: HomeIcon },
  { key: "gallery", label: "展示图库", Icon: GalleryHorizontalEnd },
  { key: "similarity", label: "相似整理", Icon: ScanSearch },
  { key: "acquisition", label: "采集中心", Icon: FolderSync },
  { key: "people", label: "人物样本", Icon: UsersRound },
  { key: "upload", label: "上传", Icon: UploadCloud },
  { key: "videos", label: "视频库", Icon: Clapperboard },
  { key: "statistics", label: "统计", Icon: BarChart3 }
] as const;

export function ApplicationContent({ authSession, onLogout, onSessionChange }: MainAppProps) {
  const confirm = useConfirm();
  const [page, setPageState] = useState<PageKey>(() => routeFromHash());
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
  const canAddGallery = hasPermission(authSession, "can_add_gallery");
  const canDeleteGallery = hasPermission(authSession, "can_delete_gallery");
  const canEditGallery = hasPermission(authSession, "can_edit_gallery");
  const canAddSamples = hasPermission(authSession, "can_add_samples");
  const canDeleteSamples = hasPermission(authSession, "can_delete_samples");
  const canEditSamples = hasPermission(authSession, "can_edit_samples");
  const canAddVideos = hasPermission(authSession, "can_add_videos");
  const canDeleteVideos = hasPermission(authSession, "can_delete_videos");
  const canEditVideos = hasPermission(authSession, "can_edit_videos");

  const catalog = useCatalog();
  const peopleRef = useRef<PeopleModel | null>(null);

  function onNavigate(next: PageKey) {
    setPageState(next);
    setRoute(next);
  }

  const gallery = useGallery({
    persons: catalog.persons,
    tags: catalog.tags,
    page,
    workspaceId: authSession.workspace.id,
    confirm,
    refreshPeople: catalog.refreshPeople,
    refreshTags: catalog.refreshTags,
    canAddGallery,
    canDeleteGallery,
    canEditGallery,
    onOpenMatchedSample: (personId, samplePhotoId) => {
      peopleRef.current?.handleOpenMatchedSample(personId, samplePhotoId);
    }
  });

  const people = usePeople({
    persons: catalog.persons,
    tags: catalog.tags,
    confirm,
    refreshPeople: catalog.refreshPeople,
    refreshTags: catalog.refreshTags,
    refreshGallery: async () => {
      await gallery.refreshGallery();
    },
    onNavigate,
    onOpenGalleryPhoto: (photoId) => gallery.openGalleryPhoto(photoId),
    canAddSamples,
    canDeleteSamples,
    canEditSamples,
    canEditGallery
  });
  peopleRef.current = people;

  const upload = useUpload({
    persons: catalog.persons,
    tags: catalog.tags,
    refreshPeople: catalog.refreshPeople,
    refreshTags: catalog.refreshTags,
    refreshGallery: async () => {
      await gallery.refreshGallery();
    },
    canAddGallery,
    canAddVideos
  });

  const videos = useVideos({
    page,
    confirm,
    canAddVideos,
    canDeleteVideos,
    canEditVideos,
    onNavigate
  });

  useEffect(() => {
    void catalog.refreshPeople().catch((cause) => {
      gallery.setError(cause instanceof Error ? cause.message : "初始化人物失败。");
    });
    void catalog.refreshTags().catch((cause) => {
      gallery.setError(cause instanceof Error ? cause.message : "初始化标签失败。");
    });
  }, []);

  useEffect(() => {
    const onHashChange = () => {
      const newPage = routeFromHash();
      setPageState(newPage);
      if (newPage === "video-play") {
        const hash = window.location.hash.replace(/^#\/?/, "");
        const id = hash.split("/")[1];
        if (id) {
          void videos.openVideo(parseInt(id, 10));
        }
      }
    };
    window.addEventListener("hashchange", onHashChange);
    if (!window.location.hash) {
      setRoute("home");
    } else if (routeFromHash() === "video-play") {
      onHashChange();
    }
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const error = gallery.error ?? people.error ?? upload.error ?? videos.error;
  function clearError() {
    gallery.setError(null);
    people.setError(null);
    upload.setError(null);
    videos.setError(null);
  }

  function scrollToPageTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div className="app-shell">
      <div className="sunwash sunwash-a" />
      <div className="sunwash sunwash-b" />

      <header className="topbar">
        <div>
          <p className="eyebrow">本地相册</p>
          <h1>PictureShow</h1>
          <div className="session-strip">
            <button type="button" onClick={() => setWorkspacePanelOpen(true)}>
              <Settings size={14} aria-hidden="true" />
              {authSession.workspace.name}
            </button>
            <span>{authSession.user.display_name || authSession.user.username}</span>
            <span>{authSession.workspace.kind === "private" ? "私人空间" : authSession.workspace.role === "owner" ? "共享 owner" : "共享成员"}</span>
            <button type="button" onClick={onLogout}>
              <LogOut size={14} aria-hidden="true" />
              退出登录
            </button>
          </div>
        </div>
        <nav className="nav-tabs">
          {navItems.map(({ key, label, Icon }) => (
            <button
              key={key}
              className={page === key ? "nav-tab active" : "nav-tab"}
              onClick={() => onNavigate(key as PageKey)}
            >
              <Icon size={16} aria-hidden="true" />
              {label}
            </button>
          ))}
        </nav>
      </header>

      {workspacePanelOpen && (
        <WorkspacePanel
          session={authSession}
          onSessionChange={onSessionChange}
          onClose={() => setWorkspacePanelOpen(false)}
        />
      )}

      {page === "statistics" && <Statistics />}
      {page === "videos" && <VideosPage model={videos} />}
      {page === "video-play" && (
        <VideoPlayPage
          busy={videos.busy}
          canDeleteVideos={canDeleteVideos}
          canEditVideos={canEditVideos}
          selectedVideo={videos.selectedVideo}
          videoPlayerUrl={videos.videoPlayerUrl}
          videoPlaybackDiagnostics={videos.videoPlaybackDiagnostics}
          videoPlaybackDiagnosticsLoading={videos.videoPlaybackDiagnosticsLoading}
          onEditVideo={() => videos.openVideoEditModal()}
          onGenerateSubtitles={() => void videos.handleGenerateSelectedVideoSubtitles()}
          onReplaceCover={(files) => void videos.handleReplaceVideoCover(files)}
          onLoadDiagnostics={() => void videos.handleLoadVideoPlaybackDiagnostics()}
          onOptimizePlayback={() => void videos.handleOptimizeSelectedVideoPlayback()}
          onDeleteVideo={() => {
            void videos.handleDeleteCurrentVideo().then((deleted) => {
              if (deleted) onNavigate("videos");
            });
          }}
        />
      )}
      {page === "home" && <Home />}
      {page === "gallery" && <GalleryPage model={gallery} />}
      {page === "similarity" && (
        <SimilarityReview persons={catalog.persons} canEdit={canEditGallery} canDelete={canDeleteGallery} />
      )}
      {page === "acquisition" && (
        <AcquisitionCenter canEdit={canEditGallery} canAdd={canAddGallery} canDelete={canDeleteGallery}
          canAdmin={authSession.user.is_admin} canManageAccounts={authSession.workspace.role === "owner"} />
      )}
      {page === "people" && <PeoplePage model={people} />}
      {page === "upload" && <UploadPage upload={upload} videos={videos} />}

      {(page === "gallery" || page === "videos") && (
        <button className="floating-top-button" type="button" onClick={scrollToPageTop} aria-label="回到顶部" title="回到顶部">
          <ArrowUp size={24} aria-hidden="true" />
        </button>
      )}

      {error && (
        <div className="error-banner" role="alert">
          <span className="error-banner-message">{error}</span>
          <button type="button" className="error-banner-close" aria-label="关闭提示" onClick={clearError}>
            ×
          </button>
        </div>
      )}
    </div>
  );
}
