import { useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  BarChart3,
  ArrowUp,
  Clapperboard,
  Download,
  Edit3,
  FileUp,
  GalleryHorizontalEnd,
  HomeIcon,
  ImagePlus,
  Info,
  LogOut,
  RotateCcw,
  Search,
  Settings,
  Trash2,
  UploadCloud,
  UserPlus,
  UsersRound
} from "lucide-react";

import Home from "./Home";
import Statistics from "./Statistics";
import BiliVideoPlayer from "./BiliVideoPlayer";
import { sortByPinyinName } from "./sort";
import {
  addGalleryPhotoPerson,
  addGalleryPhotoTag,
  addPersonSamples,
  bootstrapAdmin,
  batchDeleteGalleryPhotos,
  batchDeletePersons,
  bindPersonTag,
  cancelVideoUpload,
  clearAuthToken,
  clearSelectedWorkspaceId,
  completeVideoUpload,
  createPerson,
  createVideoCategoryTag,
  createVideoPerson,
  createVideoUploadSession,
  createWorkspace,
  createWorkspaceUser,
  deleteGalleryPhoto,
  deleteGalleryPhotoPerson,
  deleteGalleryPhotoTag,
  deletePerson,
  deletePersonSample,
  deleteVideo,
  deleteVideoCategoryTag,
  deleteVideoPerson,
  cancelVideoSubtitles,
  generateVideoSubtitles,
  getBootstrapStatus,
  getCurrentSession,
  getSubtitleServiceLogs,
  getSubtitleServiceStatus,
  getVideo,
  getVideoPlaybackDiagnostics,
  getVideoUploadSession,
  getGalleryExportUrl,
  getGalleryPhoto,
  getPersonExportUrl,
  getTask,
  importGalleryExportZip,
  importGalleryPhotos,
  importGalleryRichPhotos,
  importPersonSamples,
  listGalleryPhotos,
  listPersonSamples,
  listPersons,
  listPersonTags,
  listTags,
  listSubtitleJobs,
  listVideoCategoryTags,
  listVideoPeople,
  listVideos,
  listWorkspaceInvitations,
  listWorkspaceMembers,
  login,
  registerAccount,
  renamePerson,
  replaceVideoCover,
  optimizeVideoPlayback,
  reRecognizeGalleryPhoto,
  reRecognizeUnknownGalleryPhotos,
  updateGalleryPhotoRichText,
  uploadVideoPart,
  unbindPersonTag,
  updateVideo,
  addVideoCategoryTag,
  removeVideoCategoryTag,
  addVideoPerson,
  removeVideoPerson,
  startSubtitleService,
  setAuthToken,
  setSelectedWorkspaceId,
  stopSubtitleService,
  acceptWorkspaceInvitation,
  declineWorkspaceInvitation,
  inviteWorkspaceMember,
  leaveWorkspace,
  removeWorkspaceMember,
  updateVideoCategoryTag,
  updateVideoPerson,
  updateWorkspaceMember,
  type GalleryExportScope,
  type GalleryUploadMetadata,
  type WorkspacePermissionsPayload
} from "./api";
import type {
  AuthSession,
  GalleryPhotoDetail,
  GalleryPhotoListItem,
  Person,
  SamplePhoto,
  SubtitleJob,
  SubtitleServiceLogs,
  SubtitleServiceStatus,
  Tag,
  Task,
  VideoCategoryTag,
  VideoDetail,
  VideoItem,
  VideoPlaybackDiagnostics,
  VideoPerson,
  VideoUploadSession,
  WorkspaceInvitation,
  WorkspaceMember,
} from "./types";

type PageKey = "home" | "gallery" | "people" | "upload" | "videos" | "statistics" | "video-play";

type PendingSampleUpload = {
  file: File;
  previewUrl: string;
};

type PendingGalleryUpload = {
  file: File;
  previewUrl: string;
  personNamesText: string;
  tagNamesText: string;
  richText: string;
};

type UploadMode = "normal" | "rich";

type VideoUploadQueueStatus = "queued" | "uploading" | "completed" | "failed" | "needs_file";

type VideoUploadQueueItem = {
  id: string;
  filename: string;
  size: number;
  lastModified: number;
  contentType: string | null;
  title: string;
  description: string;
  categoryTagIds: number[];
  categoryTagNames: string[];
  personIds: number[];
  generateZhSubtitles: boolean;
  sessionId: string | null;
  partSize: number;
  totalParts: number;
  uploadedParts: number[];
  progress: number;
  status: VideoUploadQueueStatus;
  error: string | null;
  completedVideoId: number | null;
};

function isSystemUnknownPerson(person: Person | null | undefined): boolean {
  return Boolean(person?.is_unknown && person.display_name === systemUnknownPersonName);
}

const galleryPageSize = 20;
const videoPageSize = 24;
const videoPartSize = 16 * 1024 * 1024;
const legacyVideoResumeStorageKey = "pictureshow-video-upload-session";
const videoUploadQueueStorageKey = "pictureshow-video-upload-queue";
const videoPartUploadMaxAttempts = 4;
const videoPartUploadRetryDelayMs = 1200;
const videoSeekSeconds = 10;
const videoSeekLargeSeconds = 30;
const videoLongPressDelayMs = 300;
const videoLongPressRate = 3;
const supportedVideoExtensions = [".mp4", ".mkv", ".mov", ".webm"];
const supportedVideoAccept = "video/mp4,video/x-matroska,video/quicktime,video/webm,.mp4,.mkv,.mov,.webm";
const supportedVideoFormatLabel = "MP4/MKV/MOV/WEBM";
const systemUnknownPersonName = "未知人物";
const workspacePermissionFields: Array<{ key: keyof WorkspacePermissionsPayload; label: string }> = [
  { key: "can_add_gallery", label: "新增展示图" },
  { key: "can_delete_gallery", label: "删除展示图" },
  { key: "can_edit_gallery", label: "修改展示图" },
  { key: "can_add_samples", label: "新增样本图" },
  { key: "can_delete_samples", label: "删除样本图" },
  { key: "can_edit_samples", label: "修改样本图" },
  { key: "can_add_videos", label: "新增视频" },
  { key: "can_delete_videos", label: "删除视频" },
  { key: "can_edit_videos", label: "修改视频" }
];

const emptyWorkspacePermissions: WorkspacePermissionsPayload = Object.fromEntries(
  workspacePermissionFields.map((item) => [item.key, false])
) as WorkspacePermissionsPayload;

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "未记录时间";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatDurationSeconds(value: number | null | undefined): string {
  if (!value || !Number.isFinite(value)) {
    return "时长未知";
  }
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatResolution(width: number | null | undefined, height: number | null | undefined): string {
  if (!width || !height) {
    return "分辨率未知";
  }
  return `${width}x${height}`;
}

function formatCodecs(
  videoCodec: string | null | undefined,
  audioCodec: string | null | undefined,
  status?: string
): string {
  const pending = status === "uploaded" || status === "processing";
  const video = videoCodec || (pending ? "识别中" : "未知视频编码");
  const audio = audioCodec || (pending ? "识别中" : "无音频/未知音频");
  return `${video} / ${audio}`;
}

function getFileExtension(filename: string): string {
  const match = filename.toLowerCase().match(/\.[^.]+$/);
  return match?.[0] ?? "";
}

function getVideoFormatLabel(filename: string): string {
  const extension = getFileExtension(filename);
  return extension ? extension.slice(1).toUpperCase() : "VIDEO";
}

function isSupportedVideoFile(filename: string): boolean {
  return supportedVideoExtensions.includes(getFileExtension(filename));
}

function isVideoCodecMissing(video: VideoDetail): boolean {
  return video.status === "ready" && (!video.original_video_codec || !video.video_codec);
}

function isVideoMetadataRepairPending(video: VideoDetail): boolean {
  return (
    isVideoCodecMissing(video) ||
    (
      video.status === "processing_failed" &&
      Boolean(video.processing_error?.includes("UNIQUE constraint failed: video_items.filename, video_items.size_bytes"))
    )
  );
}

function isTextEditingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function videoStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    uploaded: "等待优化",
    processing: "优化中",
    ready: "可播放",
    processing_failed: "优化失败"
  };
  return labels[status] ?? status;
}

function subtitleTrackStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "排队中",
    running: "生成中",
    ready: "可用",
    failed: "失败",
    canceled: "已取消"
  };
  return labels[status] ?? status;
}

function subtitleServiceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    running: "运行中",
    stopped: "未运行",
    unhealthy: "异常"
  };
  return labels[status] ?? status;
}

function subtitleAsrStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    not_loaded: "未加载",
    waiting: "等待中",
    loading: "加载中",
    transcribing: "识别中",
    ready: "已就绪",
    error: "异常"
  };
  return labels[status] ?? status;
}

function routeFromHash(): PageKey {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash.startsWith("video-play/")) {
    return "video-play";
  }
  if (hash === "people" || hash === "upload" || hash === "videos" || hash === "statistics" || hash === "gallery") {
    return hash;
  }
  return "home";
}

function setRoute(page: PageKey) {
  window.location.hash = `/${page}`;
}

function splitCommaList(input: string): string[] {
  return Array.from(
    new Set(
      input
        .split(/[，,]/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function videoFileFingerprint(file: File): string {
  return `${file.name}::${file.size}::${file.lastModified}`;
}

function makeVideoQueueItem(
  file: File,
  options: {
    title: string;
    description: string;
    categoryTagIds: number[];
    categoryTagNames: string[];
    personIds: number[];
    generateZhSubtitles: boolean;
  }
): VideoUploadQueueItem {
  return {
    id: videoFileFingerprint(file),
    filename: file.name,
    size: file.size,
    lastModified: file.lastModified,
    contentType: file.type || null,
    title: options.title,
    description: options.description,
    categoryTagIds: [...options.categoryTagIds],
    categoryTagNames: [...options.categoryTagNames],
    personIds: [...options.personIds],
    generateZhSubtitles: options.generateZhSubtitles,
    sessionId: null,
    partSize: videoPartSize,
    totalParts: Math.max(1, Math.ceil(file.size / videoPartSize)),
    uploadedParts: [],
    progress: 0,
    status: "queued",
    error: null,
    completedVideoId: null
  };
}

function normalizeVideoQueueItem(source: Partial<VideoUploadQueueItem>): VideoUploadQueueItem | null {
  if (!source.id || !source.filename || typeof source.size !== "number" || typeof source.lastModified !== "number") {
    return null;
  }
  const uploadedParts = Array.isArray(source.uploadedParts)
    ? source.uploadedParts.filter((part): part is number => Number.isInteger(part) && part >= 0)
    : [];
  const totalParts = typeof source.totalParts === "number" && source.totalParts > 0 ? source.totalParts : Math.max(1, uploadedParts.length);
  const status: VideoUploadQueueStatus =
    source.status === "completed"
      ? "completed"
      : source.status === "failed"
        ? "failed"
        : "needs_file";
  return {
    id: source.id,
    filename: source.filename,
    size: source.size,
    lastModified: source.lastModified,
    contentType: source.contentType ?? null,
    title: source.title ?? source.filename.replace(/\.[^.]+$/, ""),
    description: source.description ?? "",
    categoryTagIds: Array.isArray(source.categoryTagIds) ? source.categoryTagIds.filter((id): id is number => Number.isInteger(id)) : [],
    categoryTagNames: Array.isArray(source.categoryTagNames) ? source.categoryTagNames.filter((name): name is string => typeof name === "string") : [],
    personIds: Array.isArray(source.personIds) ? source.personIds.filter((id): id is number => Number.isInteger(id)) : [],
    generateZhSubtitles: Boolean(source.generateZhSubtitles),
    sessionId: source.sessionId ?? null,
    partSize: typeof source.partSize === "number" && source.partSize > 0 ? source.partSize : videoPartSize,
    totalParts,
    uploadedParts,
    progress:
      typeof source.progress === "number"
        ? Math.min(100, Math.max(0, source.progress))
        : Math.round((uploadedParts.length / totalParts) * 100),
    status,
    error: status === "needs_file" ? "浏览器刷新已中断上传，请重新选择这个原视频文件后继续。" : source.error ?? null,
    completedVideoId: typeof source.completedVideoId === "number" ? source.completedVideoId : null
  };
}

function loadStoredVideoUploadQueue(): VideoUploadQueueItem[] {
  try {
    const raw = window.localStorage.getItem(videoUploadQueueStorageKey);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .map((item) => normalizeVideoQueueItem(item))
      .filter((item): item is VideoUploadQueueItem => Boolean(item));
  } catch {
    window.localStorage.removeItem(videoUploadQueueStorageKey);
    return [];
  }
}

function saveStoredVideoUploadQueue(queue: VideoUploadQueueItem[]) {
  const visibleQueue = queue.filter((item) => item.status !== "completed");
  if (visibleQueue.length === 0) {
    window.localStorage.removeItem(videoUploadQueueStorageKey);
    return;
  }
  window.localStorage.setItem(videoUploadQueueStorageKey, JSON.stringify(visibleQueue));
}

function videoQueueStatusLabel(status: VideoUploadQueueStatus): string {
  const labels: Record<VideoUploadQueueStatus, string> = {
    queued: "待上传",
    uploading: "上传中",
    completed: "已完成",
    failed: "失败",
    needs_file: "需重选文件"
  };
  return labels[status];
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function withImageWidth(url: string, width: number): string {
  const next = new URL(url, window.location.origin);
  next.searchParams.set("width", String(width));
  return next.pathname + next.search;
}

function toWorkspacePermissions(source: Record<string, boolean> | WorkspacePermissionsPayload): WorkspacePermissionsPayload {
  return Object.fromEntries(
    workspacePermissionFields.map((item) => [item.key, Boolean(source[item.key])])
  ) as WorkspacePermissionsPayload;
}

type PermissionEditorProps = {
  value: WorkspacePermissionsPayload;
  onChange: (value: WorkspacePermissionsPayload) => void;
  disabled?: boolean;
};

function PermissionEditor({ value, onChange, disabled = false }: PermissionEditorProps) {
  return (
    <div className="workspace-permissions">
      {workspacePermissionFields.map((item) => (
        <label key={item.key} className="workspace-permission">
          <input
            type="checkbox"
            checked={Boolean(value[item.key])}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, [item.key]: event.target.checked })}
          />
          <span>{item.label}</span>
        </label>
      ))}
    </div>
  );
}

type WorkspacePanelProps = {
  session: AuthSession;
  onSessionChange: (session: AuthSession) => void;
  onClose: () => void;
};

function WorkspacePanel({ session, onSessionChange, onClose }: WorkspacePanelProps) {
  const [workspaceName, setWorkspaceName] = useState("");
  const [inviteUsername, setInviteUsername] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [invitePermissions, setInvitePermissions] = useState<WorkspacePermissionsPayload>({ ...emptyWorkspacePermissions });
  const [newUserPermissions, setNewUserPermissions] = useState<WorkspacePermissionsPayload>({ ...emptyWorkspacePermissions });
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invitations, setInvitations] = useState<WorkspaceInvitation[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isSharedOwner = session.workspace.kind === "shared" && session.workspace.role === "owner";

  const reloadSession = async () => {
    const next = await getCurrentSession();
    onSessionChange(next);
  };

  const reloadPanel = async () => {
    const [nextInvitations, nextMembers] = await Promise.all([
      listWorkspaceInvitations(),
      isSharedOwner ? listWorkspaceMembers(session.workspace.id) : Promise.resolve([])
    ]);
    setInvitations(nextInvitations);
    setMembers(nextMembers);
  };

  useEffect(() => {
    void reloadPanel().catch((error) => setMessage(error instanceof Error ? error.message : "加载工作区信息失败"));
  }, [session.workspace.id, isSharedOwner]);

  const run = async (action: () => Promise<void>, success: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage(success);
      await reloadPanel();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="export-modal workspace-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-heading">
          <p className="eyebrow">Workspace</p>
          <h2>内容空间</h2>
        </div>
        {message && <p className="inline-error">{message}</p>}
        <div className="workspace-section">
          <h3>我的空间</h3>
          <div className="workspace-list">
            {session.workspaces.map((workspace) => (
              <button
                key={workspace.id}
                type="button"
                className={workspace.id === session.workspace.id ? "workspace-row active" : "workspace-row"}
                onClick={async () => {
                  setSelectedWorkspaceId(workspace.id);
                  await reloadSession();
                }}
              >
                <span>{workspace.name}</span>
                <small>{workspace.kind === "private" ? "私人" : workspace.role === "owner" ? "共享 owner" : "共享成员"}</small>
              </button>
            ))}
          </div>
          <div className="workspace-inline-form">
            <input value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} placeholder="新共享空间名称" />
            <button
              disabled={busy || !workspaceName.trim()}
              onClick={() => run(async () => {
                const workspace = await createWorkspace(workspaceName.trim());
                setSelectedWorkspaceId(workspace.id);
                setWorkspaceName("");
                await reloadSession();
              }, "已创建共享空间")}
            >
              新建共享空间
            </button>
            {session.workspace.can_leave && (
              <button
                disabled={busy}
                onClick={() => run(async () => {
                  await leaveWorkspace(session.workspace.id);
                  clearSelectedWorkspaceId();
                  await reloadSession();
                }, "已退出共享空间")}
              >
                退出当前空间
              </button>
            )}
          </div>
        </div>
        <div className="workspace-section">
          <h3>收到的邀请</h3>
          {invitations.length === 0 ? (
            <p className="muted-text">暂无邀请</p>
          ) : invitations.map((invitation) => (
            <div key={invitation.id} className="workspace-member-row">
              <div>
                <strong>{invitation.workspace_name}</strong>
                <small>来自 {invitation.inviter_username}</small>
              </div>
              <div className="micro-row">
                <button disabled={busy} onClick={() => run(async () => {
                  const workspace = await acceptWorkspaceInvitation(invitation.id);
                  setSelectedWorkspaceId(workspace.id);
                  await reloadSession();
                }, "已加入内容空间")}>接受</button>
                <button disabled={busy} onClick={() => run(async () => {
                  await declineWorkspaceInvitation(invitation.id);
                  await reloadSession();
                }, "已拒绝邀请")}>拒绝</button>
              </div>
            </div>
          ))}
        </div>
        {isSharedOwner && (
          <>
            <div className="workspace-section">
              <h3>邀请现有账号</h3>
              <div className="workspace-inline-form">
                <input value={inviteUsername} onChange={(event) => setInviteUsername(event.target.value)} placeholder="用户名" />
                <button disabled={busy || !inviteUsername.trim()} onClick={() => run(async () => {
                  await inviteWorkspaceMember(session.workspace.id, inviteUsername.trim(), invitePermissions);
                  setInviteUsername("");
                }, "已发送邀请")}>发送邀请</button>
              </div>
              <PermissionEditor value={invitePermissions} onChange={setInvitePermissions} />
            </div>
            <div className="workspace-section">
              <h3>创建成员账号</h3>
              <div className="workspace-inline-form">
                <input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} placeholder="用户名" />
                <input value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} placeholder="显示名" />
                <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="初始密码" />
                <button disabled={busy || !newUsername.trim() || newPassword.length < 8} onClick={() => run(async () => {
                  await createWorkspaceUser(session.workspace.id, {
                    username: newUsername.trim(),
                    password: newPassword,
                    display_name: newDisplayName.trim() || null,
                    ...newUserPermissions
                  });
                  setNewUsername("");
                  setNewDisplayName("");
                  setNewPassword("");
                }, "已创建账号并加入当前空间")}>创建并加入</button>
              </div>
              <PermissionEditor value={newUserPermissions} onChange={setNewUserPermissions} />
            </div>
            <div className="workspace-section">
              <h3>成员权限</h3>
              {members.map((member) => (
                <div key={member.id} className="workspace-member-row">
                  <div>
                    <strong>{member.user.display_name || member.user.username}</strong>
                    <small>{member.role === "owner" ? "owner" : member.user.username}</small>
                  </div>
                  <PermissionEditor
                    value={toWorkspacePermissions(member.permissions)}
                    disabled={member.role === "owner" || busy}
                    onChange={(permissions) => {
                      void run(async () => {
                        await updateWorkspaceMember(session.workspace.id, member.id, permissions);
                      }, "已更新成员权限");
                    }}
                  />
                  {member.role !== "owner" && (
                    <button disabled={busy} onClick={() => run(async () => {
                      await removeWorkspaceMember(session.workspace.id, member.id);
                    }, "已移除成员")}>移除</button>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
        <div className="modal-actions">
          <button type="button" onClick={onClose}>关闭</button>
        </div>
      </section>
    </div>
  );
}

type MainAppProps = {
  authSession: AuthSession;
  onLogout: () => void;
  onSessionChange: (session: AuthSession) => void;
};

function MainApp({ authSession, onLogout, onSessionChange }: MainAppProps) {
  const [page, setPageState] = useState<PageKey>(() => routeFromHash());
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
  const [playVideoId, setPlayVideoId] = useState<string | null>(null);
  const [isVideoUploadModalOpen, setIsVideoUploadModalOpen] = useState(false);
  const [persons, setPersons] = useState<Person[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [galleryPhotos, setGalleryPhotos] = useState<GalleryPhotoListItem[]>([]);
  const [galleryTotal, setGalleryTotal] = useState(0);
  const [galleryOffset, setGalleryOffset] = useState(0);
  const [gallerySelectionMode, setGallerySelectionMode] = useState(false);
  const [selectedGalleryPhotoIds, setSelectedGalleryPhotoIds] = useState<number[]>([]);
  const [galleryExportModalOpen, setGalleryExportModalOpen] = useState(false);
  const [galleryExportScope, setGalleryExportScope] = useState<GalleryExportScope>("filtered");
  const [galleryExportPersonIds, setGalleryExportPersonIds] = useState<number[]>([]);
  const [galleryExportTagIds, setGalleryExportTagIds] = useState<number[]>([]);
  const [lightboxPhotoId, setLightboxPhotoId] = useState<number | null>(null);
  const [selectedPersonIds, setSelectedPersonIds] = useState<number[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [excludePersonIds, setExcludePersonIds] = useState<number[]>([]);
  const [excludeTagIds, setExcludeTagIds] = useState<number[]>([]);
  const [personSearch, setPersonSearch] = useState("");
  const [tagSearch, setTagSearch] = useState("");
  const [showUnknownPersons, setShowUnknownPersons] = useState(false);
  const [showExcludePersons, setShowExcludePersons] = useState(false);
  const [showExcludeTags, setShowExcludeTags] = useState(false);
  const [selectedPhoto, setSelectedPhoto] = useState<GalleryPhotoDetail | null>(null);
  const [manualPersonId, setManualPersonId] = useState("");
  const [manualTagId, setManualTagId] = useState("");
  const [manualTagName, setManualTagName] = useState("");
  const [richTextDraft, setRichTextDraft] = useState("");
  const [lightboxRichTextDraft, setLightboxRichTextDraft] = useState("");
  const [lightboxEditMode, setLightboxEditMode] = useState(false);
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [peopleSearch, setPeopleSearch] = useState("");
  const [peopleBatchDeleteMode, setPeopleBatchDeleteMode] = useState(false);
  const [selectedPersonDeleteIds, setSelectedPersonDeleteIds] = useState<number[]>([]);
  const [samples, setSamples] = useState<SamplePhoto[]>([]);
  const [personTags, setPersonTags] = useState<Tag[]>([]);
  const [personTagSelectId, setPersonTagSelectId] = useState("");
  const [personTagName, setPersonTagName] = useState("");
  const [newPersonName, setNewPersonName] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [pendingSampleUploads, setPendingSampleUploads] = useState<PendingSampleUpload[]>([]);
  const [pendingGalleryUploads, setPendingGalleryUploads] = useState<PendingGalleryUpload[]>([]);
  const [batchApplyPersonNames, setBatchApplyPersonNames] = useState("");
  const [batchApplyTagNames, setBatchApplyTagNames] = useState("");
  const [uploadMode, setUploadMode] = useState<UploadMode>("normal");
  const [galleryUploadBusy, setGalleryUploadBusy] = useState(false);
  const [importTask, setImportTask] = useState<Task | null>(null);
  const [galleryImportTask, setGalleryImportTask] = useState<Task | null>(null);
  const [videoItems, setVideoItems] = useState<VideoItem[]>([]);
  const [videoTotal, setVideoTotal] = useState(0);
  const [videoOffset, setVideoOffset] = useState(0);
  const [videoCategoryTags, setVideoCategoryTags] = useState<VideoCategoryTag[]>([]);
  const [videoPeople, setVideoPeople] = useState<VideoPerson[]>([]);
  const [selectedVideoCategoryIds, setSelectedVideoCategoryIds] = useState<number[]>([]);
  const [selectedVideoPersonIds, setSelectedVideoPersonIds] = useState<number[]>([]);
  const [videoSearch, setVideoSearch] = useState("");
  const [selectedVideo, setSelectedVideo] = useState<VideoDetail | null>(null);
  const selectedVideoCodecRepairVideoId = useRef<number | null>(null);
  const selectedVideoCodecRepairPolls = useRef(0);
  const [videoPlayerUrl, setVideoPlayerUrl] = useState("");
  const [videoPlaybackDiagnostics, setVideoPlaybackDiagnostics] = useState<VideoPlaybackDiagnostics | null>(null);
  const [videoPlaybackDiagnosticsLoading, setVideoPlaybackDiagnosticsLoading] = useState(false);
  const [videoFiles, setVideoFiles] = useState<File[]>([]);
  const [videoTitle, setVideoTitle] = useState("");
  const [videoDescription, setVideoDescription] = useState("");
  const [videoUploadCategoryIds, setVideoUploadCategoryIds] = useState<number[]>([]);
  const [videoUploadPersonIds, setVideoUploadPersonIds] = useState<number[]>([]);
  const [videoUploadNewCategories, setVideoUploadNewCategories] = useState("");
  const [videoUploadGenerateSubtitles, setVideoUploadGenerateSubtitles] = useState(false);
  const [videoUploadProgress, setVideoUploadProgress] = useState(0);
  const [videoUploadSession, setVideoUploadSession] = useState<VideoUploadSession | null>(null);
  const [videoUploadCurrentIndex, setVideoUploadCurrentIndex] = useState(0);
  const [videoUploadTotalCount, setVideoUploadTotalCount] = useState(0);
  const [videoUploadBusy, setVideoUploadBusy] = useState(false);
  const [videoUploadQueue, setVideoUploadQueue] = useState<VideoUploadQueueItem[]>(() => loadStoredVideoUploadQueue());
  const videoUploadQueueRef = useRef<VideoUploadQueueItem[]>(videoUploadQueue);
  const previousPageRef = useRef<PageKey>(page);
  const [subtitleServiceStatus, setSubtitleServiceStatus] = useState<SubtitleServiceStatus | null>(null);
  const [subtitleServiceLogs, setSubtitleServiceLogs] = useState<SubtitleServiceLogs | null>(null);
  const [subtitleJobs, setSubtitleJobs] = useState<SubtitleJob[]>([]);
  const [subtitleJobsLoaded, setSubtitleJobsLoaded] = useState(false);
  const [subtitleServiceBusy, setSubtitleServiceBusy] = useState(false);
  const [subtitleServiceNotice, setSubtitleServiceNotice] = useState<string | null>(null);
  const [subtitleLogsOpen, setSubtitleLogsOpen] = useState(false);
  const [newVideoCategoryName, setNewVideoCategoryName] = useState("");
  const [newVideoPersonName, setNewVideoPersonName] = useState("");
  const [newVideoPersonNote, setNewVideoPersonNote] = useState("");
  const [newVideoPersonAvatar, setNewVideoPersonAvatar] = useState<File | null>(null);
  const [isVideoEditModalOpen, setIsVideoEditModalOpen] = useState(false);
  const [editVideoTitle, setEditVideoTitle] = useState("");
  const [editVideoDescription, setEditVideoDescription] = useState("");
  const [editVideoCategoryIds, setEditVideoCategoryIds] = useState<number[]>([]);
  const [editVideoPersonIds, setEditVideoPersonIds] = useState<number[]>([]);
  const [isCategoryManageModalOpen, setIsCategoryManageModalOpen] = useState(false);
  const [isVideoPersonManageModalOpen, setIsVideoPersonManageModalOpen] = useState(false);
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryName, setEditingCategoryName] = useState("");
  const [newManageCategoryName, setNewManageCategoryName] = useState("");
  const [editingPersonId, setEditingPersonId] = useState<number | null>(null);
  const [editingPersonName, setEditingPersonName] = useState("");
  const [editingPersonNote, setEditingPersonNote] = useState("");
  const [editingPersonAvatar, setEditingPersonAvatar] = useState<File | null>(null);
  const [newManagePersonName, setNewManagePersonName] = useState("");
  const [newManagePersonNote, setNewManagePersonNote] = useState("");
  const [newManagePersonAvatar, setNewManagePersonAvatar] = useState<File | null>(null);
  const importFileRef = useRef<HTMLInputElement | null>(null);
  const galleryImportFileRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jumpPageInput, setJumpPageInput] = useState("");
  const peopleMainRef = useRef<HTMLElement | null>(null);
  const galleryDetailRef = useRef<HTMLElement | null>(null);

  const richTag = useMemo(() => tags.find((tag) => tag.name === "图文") ?? null, [tags]);
  const normalTags = useMemo(() => sortByPinyinName(tags.filter((tag) => !tag.is_system)), [tags]);
  const selectedPersonIsSystemUnknown = isSystemUnknownPerson(selectedPerson);

  const filteredPersons = useMemo(() => {
    const keyword = personSearch.trim().toLowerCase();
    if (!keyword) {
      return persons;
    }
    return persons.filter((person) => person.display_name.toLowerCase().includes(keyword));
  }, [personSearch, persons]);

  const selectedFilterPersons = useMemo(
    () => persons.filter((person) => selectedPersonIds.includes(person.id)),
    [persons, selectedPersonIds]
  );

  const knownFilterPersons = useMemo(
    () => filteredPersons.filter((person) => !person.is_unknown && !selectedPersonIds.includes(person.id)),
    [filteredPersons, selectedPersonIds]
  );

  const unknownFilterPersons = useMemo(
    () => filteredPersons.filter((person) => person.is_unknown && !selectedPersonIds.includes(person.id)),
    [filteredPersons, selectedPersonIds]
  );

  const allFilteredUnknownPersons = useMemo(
    () => filteredPersons.filter((person) => person.is_unknown),
    [filteredPersons]
  );

  const personSearchActive = personSearch.trim().length > 0;
  const visibleUnknownFilterPersons = showUnknownPersons || personSearchActive ? unknownFilterPersons : [];
  const selectedUnknownPersonCount = selectedFilterPersons.filter((person) => person.is_unknown).length;
  const allFilteredUnknownSelected =
    allFilteredUnknownPersons.length > 0 &&
    allFilteredUnknownPersons.every((person) => selectedPersonIds.includes(person.id));

  const filteredTags = useMemo(() => {
    const keyword = tagSearch.trim().toLowerCase();
    if (!keyword) {
      return sortByPinyinName(tags);
    }
    return sortByPinyinName(tags.filter((tag) => tag.name.toLowerCase().includes(keyword)));
  }, [tagSearch, tags]);

  const excludedFilterPersons = useMemo(
    () => persons.filter((person) => excludePersonIds.includes(person.id)),
    [persons, excludePersonIds]
  );

  const excludedFilterTags = useMemo(
    () => tags.filter((tag) => excludeTagIds.includes(tag.id)),
    [tags, excludeTagIds]
  );

  const availableExcludePersons = useMemo(
    () => persons.filter((person) => !selectedPersonIds.includes(person.id) && !excludePersonIds.includes(person.id)),
    [persons, selectedPersonIds, excludePersonIds]
  );

  const availableExcludeKnownPersons = useMemo(
    () => availableExcludePersons.filter((person) => !person.is_unknown),
    [availableExcludePersons]
  );

  const availableExcludeUnknownPersons = useMemo(
    () => availableExcludePersons.filter((person) => person.is_unknown),
    [availableExcludePersons]
  );

  const availableExcludeTags = useMemo(
    () => sortByPinyinName(tags.filter((tag) => !selectedTagIds.includes(tag.id) && !excludeTagIds.includes(tag.id))),
    [tags, selectedTagIds, excludeTagIds]
  );

  const filteredPeopleInLibrary = useMemo(() => {
    const keyword = peopleSearch.trim().toLowerCase();
    if (!keyword) {
      return persons;
    }
    return persons.filter((person) => person.display_name.toLowerCase().includes(keyword));
  }, [peopleSearch, persons]);

  const unknownPersonCount = useMemo(() => persons.filter((person) => person.is_unknown).length, [persons]);
  const selectedPersonDeleteCount = useMemo(
    () => selectedPersonDeleteIds.filter((id) => !isSystemUnknownPerson(persons.find((person) => person.id === id))).length,
    [persons, selectedPersonDeleteIds]
  );

  const filteredVideoCategoryTags = useMemo(() => sortByPinyinName(videoCategoryTags), [videoCategoryTags]);
  const filteredVideoPeople = useMemo(() => sortByPinyinName(videoPeople), [videoPeople]);
  const selectedVideoCategories = useMemo(
    () => videoCategoryTags.filter((tag) => selectedVideoCategoryIds.includes(tag.id)),
    [selectedVideoCategoryIds, videoCategoryTags]
  );
  const selectedVideoPeople = useMemo(
    () => videoPeople.filter((person) => selectedVideoPersonIds.includes(person.id)),
    [selectedVideoPersonIds, videoPeople]
  );
  const videoTotalPages = Math.max(1, Math.ceil(videoTotal / videoPageSize));
  const videoCurrentPage = Math.floor(videoOffset / videoPageSize) + 1;
  const selectedVideoSubtitlePollingKey =
    selectedVideo?.subtitle_tracks.map((track) => `${track.id}:${track.status}`).join("|") ?? "";
  const activeSubtitleJobs = useMemo(
    () => subtitleJobs.filter((job) => ["pending", "running"].includes(job.track.status)),
    [subtitleJobs]
  );
  const activeSubtitleJobCount = activeSubtitleJobs.length;
  const visibleSubtitleJobs = useMemo(() => subtitleJobs.slice(0, 8), [subtitleJobs]);

  async function refreshPeople() {
    const nextPersons = await listPersons();
    setPersons(nextPersons);
    setSelectedPersonDeleteIds((current) => current.filter((id) => nextPersons.some((person) => person.id === id)));
    setSelectedPerson((current) => {
      if (!current) {
        return nextPersons[0] ?? null;
      }
      return nextPersons.find((person) => person.id === current.id) ?? nextPersons[0] ?? null;
    });
  }

  async function refreshTags() {
    setTags(sortByPinyinName(await listTags()));
  }

  async function refreshGallery(
    nextOffset = galleryOffset,
    personIds = selectedPersonIds,
    tagIds = selectedTagIds,
    nextExcludePersonIds?: number[],
    nextExcludeTagIds?: number[],
  ) {
    const epIds = nextExcludePersonIds ?? excludePersonIds;
    const etIds = nextExcludeTagIds ?? excludeTagIds;
    const response = await listGalleryPhotos(personIds, tagIds, epIds, etIds, nextOffset, galleryPageSize);
    setGalleryPhotos(response.items);
    setGalleryTotal(response.total);
    setGalleryOffset(response.offset);
    setSelectedGalleryPhotoIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
  }

  async function refreshVideoTaxonomy() {
    const [categories, people] = await Promise.all([listVideoCategoryTags(), listVideoPeople()]);
    setVideoCategoryTags(sortByPinyinName(categories));
    setVideoPeople(sortByPinyinName(people));
  }

  async function refreshVideos(
    nextOffset = videoOffset,
    categoryIds = selectedVideoCategoryIds,
    personIds = selectedVideoPersonIds,
    query = videoSearch,
  ) {
    const response = await listVideos(categoryIds, personIds, query, nextOffset, videoPageSize);
    setVideoItems(response.items);
    setVideoTotal(response.total);
    setVideoOffset(response.offset);
    setSelectedVideo((current) => {
      if (!current) {
        return current;
      }
      const listed = response.items.find((item) => item.id === current.id);
      return listed ? { ...current, ...listed } : current;
    });
  }

  async function refreshSubtitleJobs() {
    const jobs = await listSubtitleJobs();
    setSubtitleJobs(jobs);
    setSubtitleJobsLoaded(true);
  }

  async function refreshSubtitleServicePanel() {
    const operations: Promise<unknown>[] = [
      getSubtitleServiceStatus().then((status) => setSubtitleServiceStatus(status)),
      refreshSubtitleJobs()
    ];
    if (subtitleLogsOpen) {
      operations.push(getSubtitleServiceLogs(200).then((logs) => setSubtitleServiceLogs(logs)));
    }
    const results = await Promise.allSettled(operations);
    const failed = results.find((result) => result.status === "rejected");
    if (failed?.status === "rejected") {
      throw failed.reason instanceof Error ? failed.reason : new Error("字幕服务状态刷新失败。");
    }
  }

  async function refreshSamples(personId: number | null) {
    if (!personId) {
      setSamples([]);
      return;
    }
    setSamples(await listPersonSamples(personId));
  }

  async function refreshPersonTags(personId: number | null) {
    if (!personId) {
      setPersonTags([]);
      return;
    }
    setPersonTags(sortByPinyinName(await listPersonTags(personId)));
  }

  function handleTogglePersonFilter(personId: number) {
    const active = selectedPersonIds.includes(personId);
    const next = active ? selectedPersonIds.filter((id) => id !== personId) : [...selectedPersonIds, personId];
    setSelectedPersonIds(next);
    let nextExclude = excludePersonIds;
    if (!active && excludePersonIds.includes(personId)) {
      nextExclude = excludePersonIds.filter((id) => id !== personId);
      setExcludePersonIds(nextExclude);
    }
    void refreshGallery(0, next, selectedTagIds, nextExclude, excludeTagIds);
  }

  function handleToggleUnknownPersonFilters() {
    const targetIds = allFilteredUnknownPersons.map((person) => person.id);
    if (targetIds.length === 0) {
      return;
    }
    const targetIdSet = new Set(targetIds);
    const next = allFilteredUnknownSelected
      ? selectedPersonIds.filter((id) => !targetIdSet.has(id))
      : Array.from(new Set([...selectedPersonIds, ...targetIds]));
    setSelectedPersonIds(next);
    setShowUnknownPersons(true);
    let nextExclude = excludePersonIds;
    if (!allFilteredUnknownSelected) {
      nextExclude = excludePersonIds.filter((id) => !targetIdSet.has(id));
      setExcludePersonIds(nextExclude);
    }
    void refreshGallery(0, next, selectedTagIds, nextExclude, excludeTagIds);
  }

  function handleToggleExcludePerson(personId: number) {
    const active = excludePersonIds.includes(personId);
    let nextExclude: number[];
    let nextInclude = selectedPersonIds;
    if (active) {
      nextExclude = excludePersonIds.filter((id) => id !== personId);
    } else {
      nextExclude = [...excludePersonIds, personId];
      if (selectedPersonIds.includes(personId)) {
        nextInclude = selectedPersonIds.filter((id) => id !== personId);
        setSelectedPersonIds(nextInclude);
      }
    }
    setExcludePersonIds(nextExclude);
    void refreshGallery(0, nextInclude, selectedTagIds, nextExclude, excludeTagIds);
  }

  function handleToggleExcludeTag(tagId: number) {
    const active = excludeTagIds.includes(tagId);
    let nextExclude: number[];
    let nextInclude = selectedTagIds;
    if (active) {
      nextExclude = excludeTagIds.filter((id) => id !== tagId);
    } else {
      nextExclude = [...excludeTagIds, tagId];
      if (selectedTagIds.includes(tagId)) {
        nextInclude = selectedTagIds.filter((id) => id !== tagId);
        setSelectedTagIds(nextInclude);
      }
    }
    setExcludeTagIds(nextExclude);
    void refreshGallery(0, selectedPersonIds, nextInclude, excludePersonIds, nextExclude);
  }

  useEffect(() => {
    const onHashChange = () => {
      const newPage = routeFromHash();
      setPageState(newPage);
      if (newPage === "video-play") {
        const hash = window.location.hash.replace(/^#\/?/, "");
        const id = hash.split("/")[1];
        if (id) {
          const numId = parseInt(id, 10);
          setPlayVideoId(id);
          void openVideo(numId);
        }
      }
    };
    window.addEventListener("hashchange", onHashChange);
    // Initial check
    if (!window.location.hash) {
      setRoute("home");
    } else {
      // Call it once to handle deep links correctly (avoid multiple fires but ensure playVideoId is set)
      const initialPage = routeFromHash();
      if (initialPage === "video-play") {
        onHashChange();
      }
    }
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshPeople(), refreshTags(), refreshGallery(0, [], [])]);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "初始化数据失败。");
      }
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshVideoTaxonomy(), refreshVideos(0, [], [], "")]);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "视频数据初始化失败。");
      }
    })();
  }, []);

  useEffect(() => {
    videoUploadQueueRef.current = videoUploadQueue;
    saveStoredVideoUploadQueue(videoUploadQueue);
  }, [videoUploadQueue]);

  useEffect(() => {
    if (!videoUploadBusy) {
      return undefined;
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [videoUploadBusy]);

  useEffect(() => {
    if (page === "videos" && previousPageRef.current !== "videos") {
      void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
    }
    previousPageRef.current = page;
  }, [page]);

  useEffect(() => {
    if (page !== "videos") {
      return undefined;
    }
    let canceled = false;
    const shouldKeepPolling = activeSubtitleJobCount > 0 || subtitleLogsOpen;
    const refresh = async () => {
      await Promise.allSettled([
        listSubtitleJobs()
          .then((jobs) => {
            if (!canceled) {
              setSubtitleJobs(jobs);
              setSubtitleJobsLoaded(true);
            }
          })
          .catch((cause) => {
            if (!canceled) {
              setError(cause instanceof Error ? cause.message : "字幕任务刷新失败。");
            }
          }),
        getSubtitleServiceStatus()
          .then((status) => {
            if (!canceled) {
              setSubtitleServiceStatus(status);
            }
          })
          .catch((cause) => {
            if (!canceled) {
              setSubtitleServiceNotice(`状态刷新失败：${cause instanceof Error ? cause.message : "字幕服务状态刷新失败。"}`);
            }
          }),
        subtitleLogsOpen
          ? getSubtitleServiceLogs(200)
              .then((logs) => {
                if (!canceled) {
                  setSubtitleServiceLogs(logs);
                }
              })
              .catch((cause) => {
                if (!canceled) {
                  setError(cause instanceof Error ? cause.message : "字幕日志刷新失败。");
                }
              })
          : Promise.resolve()
      ]);
    };
    void refresh();
    if (!shouldKeepPolling) {
      return () => {
        canceled = true;
      };
    }
    const timer = window.setInterval(refresh, 4000);
    return () => {
      canceled = true;
      window.clearInterval(timer);
    };
  }, [page, subtitleLogsOpen, activeSubtitleJobCount]);

  useEffect(() => {
    const hasPendingSubtitle = selectedVideo?.subtitle_tracks.some((track) => ["pending", "running"].includes(track.status));
    if (!selectedVideo || (!["uploaded", "processing"].includes(selectedVideo.status) && !hasPendingSubtitle)) {
      return undefined;
    }
    const videoId = selectedVideo.id;
    const timer = window.setInterval(async () => {
      try {
        const detail = await getVideo(videoId);
        setSelectedVideo(detail);
        setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "视频状态刷新失败。");
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedVideo?.id, selectedVideo?.status, selectedVideoSubtitlePollingKey]);

  useEffect(() => {
    if (!selectedVideo) {
      selectedVideoCodecRepairVideoId.current = null;
      selectedVideoCodecRepairPolls.current = 0;
      return undefined;
    }
    if (selectedVideoCodecRepairVideoId.current !== selectedVideo.id) {
      selectedVideoCodecRepairVideoId.current = selectedVideo.id;
      selectedVideoCodecRepairPolls.current = 0;
    }
    if (!isVideoMetadataRepairPending(selectedVideo) || selectedVideoCodecRepairPolls.current >= 5) {
      return undefined;
    }
    const videoId = selectedVideo.id;
    const timer = window.setTimeout(async () => {
      selectedVideoCodecRepairPolls.current += 1;
      try {
        const detail = await getVideo(videoId);
        setSelectedVideo(detail);
        setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "视频编码信息刷新失败。");
      }
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [
    selectedVideo?.id,
    selectedVideo?.status,
    selectedVideo?.original_video_codec,
    selectedVideo?.video_codec,
    selectedVideo?.processing_error
  ]);

  useEffect(() => {
    if (!selectedVideo) {
      setVideoPlayerUrl("");
      return;
    }
    setVideoPlayerUrl(selectedVideo.play_url || selectedVideo.stream_url);
  }, [selectedVideo?.id, selectedVideo?.play_url, selectedVideo?.stream_url]);

  useEffect(() => {
    setVideoPlaybackDiagnostics(null);
  }, [selectedVideo?.id]);


  useEffect(() => {
    void refreshSamples(selectedPerson?.id ?? null);
    void refreshPersonTags(selectedPerson?.id ?? null);
    if (selectedPerson) {
      setRenameValue(selectedPerson.display_name);
      setPersonTagSelectId("");
      setPersonTagName("");
    }
  }, [selectedPerson]);

  useEffect(() => {
    if (!task || task.status === "completed" || task.status === "failed" || task.status === "canceled") {
      return undefined;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(task.id);
        setTask(nextTask);
        if (nextTask.status === "completed") {
          await Promise.all([refreshPeople(), refreshTags(), refreshGallery(0, selectedPersonIds, selectedTagIds)]);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "任务轮询失败。");
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [selectedPersonIds, selectedTagIds, task]);

  useEffect(() => {
    if (!importTask || importTask.status === "completed" || importTask.status === "failed" || importTask.status === "canceled") {
      return undefined;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(importTask.id);
        setImportTask(nextTask);
        if (nextTask.status === "completed") {
          await refreshPeople();
          setBusy(false);
        }
        if (nextTask.status === "failed") {
          setBusy(false);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "导入轮询失败。");
        setBusy(false);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [importTask]);

  useEffect(() => {
    if (
      !galleryImportTask ||
      galleryImportTask.status === "completed" ||
      galleryImportTask.status === "failed" ||
      galleryImportTask.status === "canceled"
    ) {
      return undefined;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(galleryImportTask.id);
        setGalleryImportTask(nextTask);
        if (nextTask.status === "completed") {
          await Promise.all([refreshPeople(), refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
          setBusy(false);
        }
        if (nextTask.status === "failed") {
          setBusy(false);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "展示图 ZIP 导入轮询失败。");
        setBusy(false);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [galleryImportTask, galleryOffset, selectedPersonIds, selectedTagIds]);

  async function openGalleryPhoto(photoId: number) {
    setError(null);
    try {
      const detail = await getGalleryPhoto(photoId);
      setSelectedPhoto(detail);
      setRichTextDraft(detail.rich_text ?? "");
      setManualPersonId("");
      setManualTagId("");
      setManualTagName("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载图片详情失败。");
    }
  }

  function openGalleryLightbox(photoId: number) {
    setLightboxPhotoId(photoId);
  }

  function closeGalleryLightbox() {
    setLightboxPhotoId(null);
    setLightboxEditMode(false);
  }

  function scrollToPageTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function openLightboxPhotoDetail() {
    if (!lightboxPhoto) {
      return;
    }
    const photoId = lightboxPhoto.id;
    closeGalleryLightbox();
    await openGalleryPhoto(photoId);
    window.setTimeout(() => {
      galleryDetailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }

  async function handleCreatePerson() {
    if (!newPersonName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const person = await createPerson(newPersonName.trim());
      setNewPersonName("");
      await refreshPeople();
      setSelectedPerson(person);
      setPageState("people");
      setRoute("people");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleRenamePerson() {
    if (!selectedPerson || !renameValue.trim()) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能改名，请在图库详情中重新识别或改为已有正式人物。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await renamePerson(selectedPerson.id, renameValue.trim());
      await refreshPeople();
      setSelectedPerson(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "人物改名失败。");
    } finally {
      setBusy(false);
    }
  }

  function handlePickSampleFiles(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能上传样本图。");
      return;
    }
    setPendingSampleUploads((current) => [
      ...current,
      ...Array.from(files).map((file) => ({ file, previewUrl: URL.createObjectURL(file) }))
    ]);
  }

  async function handleConfirmSampleUpload() {
    if (!selectedPerson || pendingSampleUploads.length === 0) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能上传样本图。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await addPersonSamples(
        selectedPerson.id,
        pendingSampleUploads.map((item) => item.file)
      );
      pendingSampleUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      setPendingSampleUploads([]);
      await Promise.all([refreshPeople(), refreshSamples(selectedPerson.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "样本上传失败。");
    } finally {
      setBusy(false);
    }
  }

  function handleRemovePendingSample(index: number) {
    setPendingSampleUploads((current) => {
      const target = current[index];
      if (target) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return current.filter((_, i) => i !== index);
    });
  }

  async function handleDeleteSample(samplePhotoId: number) {
    if (!selectedPerson) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deletePersonSample(selectedPerson.id, samplePhotoId);
      await Promise.all([refreshPeople(), refreshSamples(selectedPerson.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除样本失败。");
    } finally {
      setBusy(false);
    }
  }

  function togglePeopleBatchDeleteMode() {
    setPeopleBatchDeleteMode((current) => {
      if (current) {
        setSelectedPersonDeleteIds([]);
      }
      return !current;
    });
  }

  async function handleDeleteSelectedPersons() {
    if (selectedPersonDeleteIds.length === 0) {
      return;
    }
    const deletableIds = selectedPersonDeleteIds.filter((id) => !isSystemUnknownPerson(persons.find((person) => person.id === id)));
    if (deletableIds.length === 0) {
      setError("系统未知人物不能删除。");
      return;
    }
    if (!window.confirm(`确认删除选中的 ${deletableIds.length} 个人物吗？这会删除其样本图、关联向量与对象存储文件。`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await batchDeletePersons(deletableIds);
      setSelectedPersonDeleteIds([]);
      setPeopleBatchDeleteMode(false);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量删除人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteCurrentPerson() {
    if (!selectedPerson) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能删除。");
      return;
    }
    if (!window.confirm(`确认删除人物「${selectedPerson.display_name}」吗？`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deletePerson(selectedPerson.id);
      setSelectedPersonDeleteIds((current) => current.filter((id) => id !== selectedPerson.id));
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleReRecognizeAllUnknownPhotos() {
    if (
      !window.confirm("确认重新识别所有带未知人物标签的图片吗？识别后的新人物标签会覆盖旧标签。")
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await reRecognizeUnknownGalleryPhotos();
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
      if (selectedPhoto) {
        const detail = await getGalleryPhoto(selectedPhoto.id);
        setSelectedPhoto(detail);
      }
      window.alert(`已完成重新识别：共 ${result.total} 张，成功 ${result.succeeded} 张，失败 ${result.failed} 张。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量重新识别未知人物失败。");
    } finally {
      setBusy(false);
    }
  }

  function handleExportPersons() {
    window.open(getPersonExportUrl(), "_blank");
  }

  function handlePickImportFile() {
    importFileRef.current?.click();
  }

  async function handleImportFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const task = await importPersonSamples(file);
      setImportTask(task);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导入失败。");
      setBusy(false);
    }
    if (event.target) {
      event.target.value = "";
    }
  }

  function handleExportGalleryPhotos() {
    const url = getGalleryExportUrl({
      scope: galleryExportScope,
      personIds: galleryExportPersonIds,
      tagIds: galleryExportTagIds
    });
    window.open(url, "_blank");
    setGalleryExportModalOpen(false);
  }

  function openGalleryExportModal() {
    setGalleryExportScope("filtered");
    setGalleryExportPersonIds(selectedPersonIds);
    setGalleryExportTagIds(selectedTagIds.filter((tagId) => tags.some((tag) => tag.id === tagId && !tag.is_system)));
    setGalleryExportModalOpen(true);
  }

  function handleToggleGalleryExportPerson(personId: number) {
    setGalleryExportScope("filtered");
    setGalleryExportPersonIds((current) =>
      current.includes(personId) ? current.filter((id) => id !== personId) : [...current, personId]
    );
  }

  function handleToggleGalleryExportTag(tagId: number) {
    setGalleryExportScope("filtered");
    setGalleryExportTagIds((current) =>
      current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId]
    );
  }

  function handlePickGalleryImportFile() {
    galleryImportFileRef.current?.click();
  }

  async function handleGalleryImportFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const task = await importGalleryExportZip(file);
      setGalleryImportTask(task);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "展示图 ZIP 导入失败。");
      setBusy(false);
    }
    if (event.target) {
      event.target.value = "";
    }
  }

  function handleSelectPerson(person: Person) {
    pendingSampleUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    setPendingSampleUploads([]);
    setSelectedPerson(person);
    if (window.matchMedia("(max-width: 1240px)").matches) {
      window.requestAnimationFrame(() => {
        peopleMainRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  async function handleBindPersonTag() {
    if (!selectedPerson || (!personTagSelectId && !personTagName.trim())) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能维护普通标签。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await bindPersonTag(
        selectedPerson.id,
        personTagSelectId ? { tagId: Number(personTagSelectId) } : { name: personTagName.trim() }
      );
      setPersonTags(sortByPinyinName(next));
      setPersonTagSelectId("");
      setPersonTagName("");
      await Promise.all([refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "人物标签绑定失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUnbindPersonTag(tagId: number) {
    if (!selectedPerson) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能维护普通标签。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await unbindPersonTag(selectedPerson.id, tagId);
      setPersonTags(sortByPinyinName(next));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "人物标签移除失败。");
    } finally {
      setBusy(false);
    }
  }

  function handlePickGalleryFiles(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    setPendingGalleryUploads((current) => [
      ...current,
      ...Array.from(files).map((file) => ({
        file,
        previewUrl: URL.createObjectURL(file),
        personNamesText: "",
        tagNamesText: "",
        richText: ""
      }))
    ]);
  }

  function handleUpdatePendingGallery(index: number, changes: Partial<PendingGalleryUpload>) {
    setPendingGalleryUploads((current) =>
      current.map((item, i) => {
        if (i !== index) {
          return item;
        }
        return { ...item, ...changes };
      })
    );
  }

  function handleApplyBatchMetadataToAll() {
    const personNames = splitCommaList(batchApplyPersonNames);
    const tagNames = splitCommaList(batchApplyTagNames);
    if (personNames.length === 0 && tagNames.length === 0) {
      return;
    }
    setPendingGalleryUploads((current) =>
      current.map((item) => {
        const mergedPersons = Array.from(new Set([...splitCommaList(item.personNamesText), ...personNames]));
        const mergedTags = Array.from(new Set([...splitCommaList(item.tagNamesText), ...tagNames]));
        return {
          ...item,
          personNamesText: mergedPersons.join(", "),
          tagNamesText: mergedTags.join(", ")
        };
      })
    );
  }

  function handleRemovePendingGallery(index: number) {
    setPendingGalleryUploads((current) => {
      const target = current[index];
      if (target) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return current.filter((_, i) => i !== index);
    });
  }

  async function handleConfirmGalleryUpload() {
    if (pendingGalleryUploads.length === 0) {
      return;
    }
    setGalleryUploadBusy(true);
    setError(null);
    try {
      const files = pendingGalleryUploads.map((item) => item.file);
      const metadata: GalleryUploadMetadata[] = pendingGalleryUploads.map((item) => ({
        person_names: splitCommaList(item.personNamesText),
        tag_names: splitCommaList(item.tagNamesText),
        rich_text: uploadMode === "rich" ? item.richText.trim() : undefined
      }));
      const nextTask =
        uploadMode === "rich" ? await importGalleryRichPhotos(files, metadata) : await importGalleryPhotos(files, metadata);
      setTask(nextTask);
      pendingGalleryUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      setPendingGalleryUploads([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "展示图上传失败。");
    } finally {
      setGalleryUploadBusy(false);
    }
  }

  function setVideoUploadQueueSynced(updater: (current: VideoUploadQueueItem[]) => VideoUploadQueueItem[]) {
    setVideoUploadQueue((current) => {
      const next = updater(current);
      videoUploadQueueRef.current = next;
      saveStoredVideoUploadQueue(next);
      return next;
    });
  }

  function updateVideoQueueItem(
    itemId: string,
    updater: Partial<VideoUploadQueueItem> | ((item: VideoUploadQueueItem) => VideoUploadQueueItem)
  ) {
    setVideoUploadQueueSynced((current) =>
      current.map((item) => {
        if (item.id !== itemId) {
          return item;
        }
        return typeof updater === "function" ? updater(item) : { ...item, ...updater };
      })
    );
  }

  function getVideoUploadOptionsForFile(file: File, totalCount: number) {
    return {
      title: totalCount === 1 ? videoTitle.trim() || file.name.replace(/\.[^.]+$/, "") : file.name.replace(/\.[^.]+$/, ""),
      description: videoDescription.trim(),
      categoryTagIds: videoUploadCategoryIds,
      categoryTagNames: splitCommaList(videoUploadNewCategories),
      personIds: videoUploadPersonIds,
      generateZhSubtitles: videoUploadGenerateSubtitles
    };
  }

  function handlePickVideoFile(files: FileList | null) {
    const picked = Array.from(files ?? []);
    const supportedPicked = picked.filter((file) => isSupportedVideoFile(file.name));
    setVideoFiles(supportedPicked);
    if (supportedPicked.length === 1 && !videoTitle.trim()) {
      setVideoTitle(supportedPicked[0].name.replace(/\.[^.]+$/, ""));
    } else if (supportedPicked.length > 1) {
      setVideoTitle("");
    }
    if (picked.length !== supportedPicked.length) {
      setError(`已忽略不支持的视频格式，仅支持 ${supportedVideoFormatLabel}。`);
    } else {
      setError(null);
    }
    const pickedIds = new Set(supportedPicked.map((file) => videoFileFingerprint(file)));
    const pickedById = new Map(supportedPicked.map((file) => [videoFileFingerprint(file), file]));
    setVideoUploadQueueSynced((current) => {
      const existingIds = new Set(current.map((item) => item.id));
      const next = current.map((item) => {
        if (!pickedIds.has(item.id) || item.status === "completed") {
          return item;
        }
        const file = pickedById.get(item.id);
        return {
          ...item,
          filename: file?.name ?? item.filename,
          size: file?.size ?? item.size,
          lastModified: file?.lastModified ?? item.lastModified,
          contentType: file?.type || item.contentType,
          status: "queued" as VideoUploadQueueStatus,
          error: null
        };
      });
      for (const file of supportedPicked) {
        const id = videoFileFingerprint(file);
        if (!existingIds.has(id)) {
          next.push(makeVideoQueueItem(file, getVideoUploadOptionsForFile(file, supportedPicked.length)));
        }
      }
      return next;
    });
    setVideoUploadProgress(0);
    setVideoUploadSession(null);
  }

  function handleToggleVideoFilterCategory(tagId: number) {
    const next = selectedVideoCategoryIds.includes(tagId)
      ? selectedVideoCategoryIds.filter((id) => id !== tagId)
      : [...selectedVideoCategoryIds, tagId];
    setSelectedVideoCategoryIds(next);
    void refreshVideos(0, next, selectedVideoPersonIds, videoSearch);
  }

  function handleToggleVideoFilterPerson(personId: number) {
    const next = selectedVideoPersonIds.includes(personId)
      ? selectedVideoPersonIds.filter((id) => id !== personId)
      : [...selectedVideoPersonIds, personId];
    setSelectedVideoPersonIds(next);
    void refreshVideos(0, selectedVideoCategoryIds, next, videoSearch);
  }

  function handleToggleVideoUploadCategory(tagId: number) {
    setVideoUploadCategoryIds((current) =>
      current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId]
    );
  }

  function handleToggleVideoUploadPerson(personId: number) {
    setVideoUploadPersonIds((current) =>
      current.includes(personId) ? current.filter((id) => id !== personId) : [...current, personId]
    );
  }

  async function handleCreateVideoCategory() {
    if (!newVideoCategoryName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const tag = await createVideoCategoryTag(newVideoCategoryName.trim());
      setNewVideoCategoryName("");
      await refreshVideoTaxonomy();
      setVideoUploadCategoryIds((current) => Array.from(new Set([...current, tag.id])));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建视频类别标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateVideoPerson() {
    if (!newVideoPersonName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const person = await createVideoPerson(newVideoPersonName.trim(), newVideoPersonNote.trim(), newVideoPersonAvatar);
      setNewVideoPersonName("");
      setNewVideoPersonNote("");
      setNewVideoPersonAvatar(null);
      await refreshVideoTaxonomy();
      setVideoUploadPersonIds((current) => Array.from(new Set([...current, person.id])));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建视频人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function openVideo(videoId: number) {
    setError(null);
    try {
      setSelectedVideo(await getVideo(videoId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载视频详情失败。");
    }
  }


  async function handleDeleteCurrentVideo() {
    if (!selectedVideo) {
      return;
    }
    if (!window.confirm(`确认删除视频「${selectedVideo.title}」吗？`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteVideo(selectedVideo.id);
      setSelectedVideo(null);
      setVideoPlayerUrl("");
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除视频失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleReplaceVideoCover(files: FileList | null) {
    if (!selectedVideo || !files?.[0]) {
      return;
    }
    const file = files[0];
    setBusy(true);
    setError(null);
    try {
      const detail = await replaceVideoCover(selectedVideo.id, file);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "替换视频封面失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleLoadVideoPlaybackDiagnostics() {
    if (!selectedVideo) {
      return;
    }
    setVideoPlaybackDiagnosticsLoading(true);
    setError(null);
    try {
      setVideoPlaybackDiagnostics(await getVideoPlaybackDiagnostics(selectedVideo.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取播放诊断失败。");
    } finally {
      setVideoPlaybackDiagnosticsLoading(false);
    }
  }

  async function handleOptimizeSelectedVideoPlayback() {
    if (!selectedVideo) {
      return;
    }
    if (!window.confirm("会覆盖当前 MinIO 中的视频对象，并重新编码为更适合拖动进度条的 MP4。继续吗？")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await optimizeVideoPlayback(selectedVideo.id);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      setVideoPlaybackDiagnostics(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "启动播放优化失败。");
    } finally {
      setBusy(false);
    }
  }

  function openVideoEditModal() {
    if (!selectedVideo) return;
    setEditVideoTitle(selectedVideo.title);
    setEditVideoDescription(selectedVideo.description || "");
    setEditVideoCategoryIds(selectedVideo.category_tags.map(t => t.id));
    setEditVideoPersonIds(selectedVideo.people.map(p => p.id));
    setIsVideoEditModalOpen(true);
  }

  async function handleSaveVideoEdit() {
    if (!selectedVideo) return;
    setBusy(true);
    setError(null);
    try {
      await updateVideo(selectedVideo.id, {
        title: editVideoTitle.trim() || selectedVideo.title,
        description: editVideoDescription.trim() || null
      });
      const oldCategoryIds = new Set(selectedVideo.category_tags.map(t => t.id));
      const newCategoryIds = new Set(editVideoCategoryIds);
      for (const tagId of editVideoCategoryIds) {
        if (!oldCategoryIds.has(tagId)) {
          await addVideoCategoryTag(selectedVideo.id, { tagId });
        }
      }
      for (const tagId of selectedVideo.category_tags.map(t => t.id)) {
        if (!newCategoryIds.has(tagId)) {
          await removeVideoCategoryTag(selectedVideo.id, tagId);
        }
      }
      const oldPersonIds = new Set(selectedVideo.people.map(p => p.id));
      const newPersonIds = new Set(editVideoPersonIds);
      for (const personId of editVideoPersonIds) {
        if (!oldPersonIds.has(personId)) {
          await addVideoPerson(selectedVideo.id, personId);
        }
      }
      for (const personId of selectedVideo.people.map(p => p.id)) {
        if (!newPersonIds.has(personId)) {
          await removeVideoPerson(selectedVideo.id, personId);
        }
      }
      const detail = await getVideo(selectedVideo.id);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      setIsVideoEditModalOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存视频信息失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateManageCategory() {
    if (!newManageCategoryName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createVideoCategoryTag(newManageCategoryName.trim());
      setNewManageCategoryName("");
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建分区失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateManageCategory(tagId: number) {
    if (!editingCategoryName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await updateVideoCategoryTag(tagId, editingCategoryName.trim());
      setEditingCategoryId(null);
      setEditingCategoryName("");
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "更新分区失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteManageCategory(tagId: number) {
    if (!window.confirm("确认删除此分区吗？")) return;
    setBusy(true);
    setError(null);
    try {
      await deleteVideoCategoryTag(tagId);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除分区失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateManagePerson() {
    if (!newManagePersonName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createVideoPerson(newManagePersonName.trim(), newManagePersonNote.trim(), newManagePersonAvatar);
      setNewManagePersonName("");
      setNewManagePersonNote("");
      setNewManagePersonAvatar(null);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建UP主失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateManagePerson(personId: number) {
    if (!editingPersonName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await updateVideoPerson(personId, editingPersonName.trim(), editingPersonNote.trim() || null, editingPersonAvatar);
      setEditingPersonId(null);
      setEditingPersonName("");
      setEditingPersonNote("");
      setEditingPersonAvatar(null);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "更新UP主失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteManagePerson(personId: number) {
    if (!window.confirm("确认删除此UP主吗？")) return;
    setBusy(true);
    setError(null);
    try {
      await deleteVideoPerson(personId);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除UP主失败。");
    } finally {
      setBusy(false);
    }
  }

  async function resolveVideoUploadSession(file: File, item: VideoUploadQueueItem): Promise<VideoUploadSession> {
    if (item.sessionId) {
      try {
        const existing = await getVideoUploadSession(item.sessionId);
        setVideoUploadSession(existing);
        updateVideoQueueItem(item.id, {
          partSize: existing.part_size,
          totalParts: existing.total_parts,
          uploadedParts: existing.uploaded_parts,
          progress: Math.round((existing.uploaded_parts.length / existing.total_parts) * 100)
        });
        return existing;
      } catch {
        updateVideoQueueItem(item.id, { sessionId: null, uploadedParts: [], progress: 0 });
      }
    }
    const session = await createVideoUploadSession({
      title: item.title.trim(),
      description: item.description.trim() || null,
      filename: file.name,
      content_type: file.type || item.contentType,
      size_bytes: file.size,
      part_size: item.partSize || videoPartSize
    });
    setVideoUploadSession(session);
    updateVideoQueueItem(item.id, {
      sessionId: session.id,
      partSize: session.part_size,
      totalParts: session.total_parts,
      uploadedParts: session.uploaded_parts,
      progress: Math.round((session.uploaded_parts.length / session.total_parts) * 100)
    });
    return session;
  }

  async function uploadVideoPartWithRetry(sessionId: string, partIndex: number, blob: Blob, filename: string): Promise<void> {
    let lastCause: unknown = null;
    for (let attempt = 1; attempt <= videoPartUploadMaxAttempts; attempt += 1) {
      try {
        await uploadVideoPart(sessionId, partIndex, blob, filename);
        return;
      } catch (cause) {
        lastCause = cause;
        if (attempt >= videoPartUploadMaxAttempts) {
          break;
        }
        await delay(videoPartUploadRetryDelayMs * attempt);
      }
    }
    throw lastCause instanceof Error ? lastCause : new Error("分片上传失败");
  }

  async function handleConfirmVideoUpload() {
    const selectedFilesById = new Map(videoFiles.map((file) => [videoFileFingerprint(file), file]));
    let preparedQueue = videoUploadQueueRef.current;
    if (videoFiles.length > 0) {
      const existingIds = new Set(preparedQueue.map((item) => item.id));
      preparedQueue = preparedQueue.map((item) => {
        const file = selectedFilesById.get(item.id);
        if (!file || item.status === "completed") {
          return item;
        }
        return {
          ...item,
          ...getVideoUploadOptionsForFile(file, videoFiles.length),
          filename: file.name,
          size: file.size,
          lastModified: file.lastModified,
          contentType: file.type || item.contentType,
          status: "queued" as VideoUploadQueueStatus,
          error: null
        };
      });
      const addedItems: VideoUploadQueueItem[] = [];
      for (const file of videoFiles) {
        const id = videoFileFingerprint(file);
        if (!existingIds.has(id)) {
          addedItems.push(makeVideoQueueItem(file, getVideoUploadOptionsForFile(file, videoFiles.length)));
        }
      }
      preparedQueue = [...preparedQueue, ...addedItems];
      setVideoUploadQueueSynced(() => preparedQueue);
    }
    const filesToUpload = preparedQueue
      .filter((item) => item.status !== "completed" && selectedFilesById.has(item.id))
      .map((item) => ({ item, file: selectedFilesById.get(item.id)! }));
    let workingQueue = preparedQueue;
    const syncWorkingQueueItem = (
      itemId: string,
      updater: Partial<VideoUploadQueueItem> | ((item: VideoUploadQueueItem) => VideoUploadQueueItem)
    ) => {
      workingQueue = workingQueue.map((queueItem) => {
        if (queueItem.id !== itemId) {
          return queueItem;
        }
        return typeof updater === "function" ? updater(queueItem) : { ...queueItem, ...updater };
      });
      setVideoUploadQueueSynced(() => workingQueue);
    };
    const totalCount = filesToUpload.length;
    if (totalCount === 0) {
      const hasInterrupted = preparedQueue.some((item) => item.status === "needs_file" || item.status === "failed");
      if (hasInterrupted) {
        setError("请重新选择队列里标记为“需重选文件”的原视频文件后继续上传。");
      }
      return;
    }
    if (videoFiles.length === 1 && !videoTitle.trim()) {
      return;
    }
    setVideoUploadBusy(true);
    setError(null);
    setVideoUploadTotalCount(totalCount);

    let completedCount = 0;
    let lastError: string | null = null;

    for (let fileIndex = 0; fileIndex < totalCount; fileIndex += 1) {
      const { item, file } = filesToUpload[fileIndex];
      console.log(`[批量上传] 第 ${fileIndex + 1}/${totalCount} 个: ${file.name} (${file.size} bytes)`);

      if (!isSupportedVideoFile(file.name)) {
        lastError = `"${file.name}" 不是支持的视频格式（${supportedVideoFormatLabel}），已跳过。`;
        syncWorkingQueueItem(item.id, { status: "failed", error: lastError });
        continue;
      }

      try {
        flushSync(() => {
          setVideoUploadCurrentIndex(fileIndex);
          setVideoUploadProgress(0);
          setVideoUploadSession(null);
        });

        syncWorkingQueueItem(item.id, { status: "uploading", error: null });
        let session = await resolveVideoUploadSession(file, item);
        const uploaded = new Set(session.uploaded_parts);
        setVideoUploadSession(session);
        syncWorkingQueueItem(item.id, {
          sessionId: session.id,
          partSize: session.part_size,
          totalParts: session.total_parts,
          uploadedParts: Array.from(uploaded).sort((left, right) => left - right),
          progress: Math.round((uploaded.size / session.total_parts) * 100)
        });
        for (let index = 0; index < session.total_parts; index += 1) {
          if (uploaded.has(index)) {
            const progress = Math.round((uploaded.size / session.total_parts) * 100);
            setVideoUploadProgress(progress);
            syncWorkingQueueItem(item.id, { progress });
            continue;
          }
          const start = index * session.part_size;
          const end = Math.min(start + session.part_size, file.size);
          await uploadVideoPartWithRetry(session.id, index, file.slice(start, end), file.name);
          uploaded.add(index);
          const uploadedParts = Array.from(uploaded).sort((left, right) => left - right);
          session = { ...session, uploaded_parts: uploadedParts };
          setVideoUploadSession(session);
          const progress = Math.round((uploadedParts.length / session.total_parts) * 100);
          setVideoUploadProgress(progress);
          syncWorkingQueueItem(item.id, { uploadedParts, progress });
        }
        session = await getVideoUploadSession(session.id);
        setVideoUploadSession(session);
        const detail = await completeVideoUpload(session.id, {
          category_tag_ids: item.categoryTagIds,
          category_tag_names: item.categoryTagNames,
          person_ids: item.personIds,
          generate_zh_subtitles: item.generateZhSubtitles
        });
        syncWorkingQueueItem(item.id, {
          sessionId: null,
          uploadedParts: session.uploaded_parts,
          progress: 100,
          status: "completed",
          error: null,
          completedVideoId: detail.id
        });
        completedCount += 1;
        console.log(`[批量上传] 第 ${fileIndex + 1}/${totalCount} 个完成: ${file.name}`);
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : "视频上传失败。";
        lastError = `"${file.name}" ${message}`;
        syncWorkingQueueItem(item.id, { status: "failed", error: message });
        console.error(`[批量上传] 第 ${fileIndex + 1}/${totalCount} 个失败: ${file.name}`, cause);
      }
    }

    if (completedCount > 0) {
      setVideoFiles([]);
      setVideoTitle("");
      setVideoDescription("");
      setVideoUploadCategoryIds([]);
      setVideoUploadPersonIds([]);
      setVideoUploadNewCategories("");
      void refreshVideoTaxonomy();
      void refreshVideos(0, [], [], "");
      if (videoUploadGenerateSubtitles) {
        void refreshSubtitleServicePanel().catch((cause) => {
          setSubtitleServiceNotice(`状态刷新失败：${cause instanceof Error ? cause.message : "字幕服务状态刷新失败。"}`);
        });
      }
    }

    setVideoUploadSession(null);
    setVideoUploadProgress(0);
    setVideoUploadCurrentIndex(0);
    setVideoUploadTotalCount(0);

    const remainingQueue = workingQueue.filter((item) => item.status !== "completed");
    if (lastError) {
      setError(`${lastError}（已完成 ${completedCount}/${totalCount} 个）`);
    } else if (remainingQueue.length > 0) {
      setError("还有未完成的视频，请重新选择对应原文件后继续上传。");
    } else {
      setVideoUploadQueueSynced(() => []);
      setIsVideoUploadModalOpen(false);
    }
    setVideoUploadBusy(false);
  }

  async function handleCancelVideoUpload() {
    const sessionsToCancel = videoUploadQueueRef.current
      .filter((item) => item.sessionId && item.status !== "completed")
      .map((item) => item.sessionId!);
    if (sessionsToCancel.length === 0 && !videoUploadSession) {
      window.localStorage.removeItem(legacyVideoResumeStorageKey);
      window.localStorage.removeItem(videoUploadQueueStorageKey);
      setVideoUploadProgress(0);
      setVideoUploadQueueSynced(() => []);
      setVideoFiles([]);
      return;
    }
    if (!window.confirm("确认清理当前视频上传队列和未完成的续传会话吗？")) {
      return;
    }
    setVideoUploadBusy(true);
    setError(null);
    try {
      await Promise.allSettled(sessionsToCancel.map((sessionId) => cancelVideoUpload(sessionId)));
      if (videoUploadSession && !sessionsToCancel.includes(videoUploadSession.id)) {
        await cancelVideoUpload(videoUploadSession.id);
      }
      window.localStorage.removeItem(legacyVideoResumeStorageKey);
      window.localStorage.removeItem(videoUploadQueueStorageKey);
      setVideoUploadSession(null);
      setVideoUploadProgress(0);
      setVideoUploadCurrentIndex(0);
      setVideoUploadTotalCount(0);
      setVideoUploadQueueSynced(() => []);
      setVideoFiles([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消视频上传失败。");
    } finally {
      setVideoUploadBusy(false);
    }
  }

  async function handleGenerateSelectedVideoSubtitles() {
    if (!selectedVideo) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await generateVideoSubtitles(selectedVideo.id);
      const detail = await getVideo(selectedVideo.id);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      await refreshSubtitleJobs();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提交字幕生成失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleStartSubtitleService() {
    setSubtitleServiceBusy(true);
    setError(null);
    setSubtitleServiceNotice(null);
    try {
      setSubtitleServiceStatus(await startSubtitleService());
      setSubtitleServiceLogs(await getSubtitleServiceLogs(200));
      await refreshSubtitleServicePanel();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "启动翻译服务失败。";
      setError(message);
      setSubtitleServiceNotice(`启动失败：${message}`);
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleStopSubtitleService() {
    const message =
      activeSubtitleJobs.length > 0
        ? `当前有 ${activeSubtitleJobs.length} 个字幕任务正在执行。关闭翻译服务会取消这些任务，确定继续吗？`
        : "确定关闭翻译服务吗？";
    if (!window.confirm(message)) {
      return;
    }
    setSubtitleServiceBusy(true);
    setError(null);
    setSubtitleServiceNotice(null);
    try {
      setSubtitleServiceStatus(await stopSubtitleService(true));
      await refreshSubtitleServicePanel();
      setSubtitleServiceNotice("翻译服务已关闭");
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
      if (selectedVideo) {
        const detail = await getVideo(selectedVideo.id);
        setSelectedVideo(detail);
      }
    } catch (cause) {
      const errorMessage = cause instanceof Error ? cause.message : "关闭翻译服务失败。";
      setError(errorMessage);
      setSubtitleServiceNotice(`关闭失败：${errorMessage}`);
      try {
        await refreshSubtitleServicePanel();
      } catch {
        // Keep the actionable shutdown error visible if the status refresh also fails.
      }
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleToggleSubtitleLogs() {
    const nextOpen = !subtitleLogsOpen;
    setSubtitleLogsOpen(nextOpen);
    if (!nextOpen) {
      return;
    }
    setSubtitleServiceBusy(true);
    setError(null);
    try {
      setSubtitleServiceLogs(await getSubtitleServiceLogs(200));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取翻译服务日志失败。");
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleCancelSubtitleJob(job: SubtitleJob) {
    if (!window.confirm(`确定取消《${job.video_title}》的中文字幕生成吗？`)) {
      return;
    }
    setSubtitleServiceBusy(true);
    setError(null);
    try {
      await cancelVideoSubtitles(job.video_id, job.track.id);
      await refreshSubtitleServicePanel();
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
      if (selectedVideo?.id === job.video_id) {
        setSelectedVideo(await getVideo(job.video_id));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消字幕任务失败。");
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleAddPhotoPerson() {
    if (!selectedPhoto || !manualPersonId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await addGalleryPhotoPerson(selectedPhoto.id, Number(manualPersonId));
      setSelectedPhoto(detail);
      setManualPersonId("");
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加人物标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeletePhotoPerson(personId: number) {
    if (!selectedPhoto) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await deleteGalleryPhotoPerson(selectedPhoto.id, personId);
      setSelectedPhoto(detail);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除人物标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddPhotoTag() {
    if (!selectedPhoto || (!manualTagId && !manualTagName.trim())) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await addGalleryPhotoTag(
        selectedPhoto.id,
        manualTagId ? { tagId: Number(manualTagId) } : { name: manualTagName.trim() }
      );
      setSelectedPhoto(detail);
      setManualTagId("");
      setManualTagName("");
      await Promise.all([refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeletePhotoTag(tagId: number) {
    if (!selectedPhoto) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await deleteGalleryPhotoTag(selectedPhoto.id, tagId);
      setSelectedPhoto(detail);
      await Promise.all([refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveRichText() {
    if (!selectedPhoto || !selectedPhoto.is_rich_text) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await updateGalleryPhotoRichText(selectedPhoto.id, richTextDraft);
      setSelectedPhoto(detail);
      await refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存图文文本失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveLightboxRichText() {
    if (!lightboxPhoto || !lightboxPhoto.is_rich_text) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await updateGalleryPhotoRichText(lightboxPhoto.id, lightboxRichTextDraft);
      setGalleryPhotos((current) =>
        current.map((photo) => (photo.id === detail.id ? { ...photo, rich_text: detail.rich_text } : photo))
      );
      if (selectedPhoto?.id === detail.id) {
        setSelectedPhoto(detail);
        setRichTextDraft(detail.rich_text || "");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存图文文本失败。");
    } finally {
      setBusy(false);
    }
  }

  function toggleGallerySelectionMode() {
    setGallerySelectionMode((current) => {
      if (current) {
        setSelectedGalleryPhotoIds([]);
      }
      return !current;
    });
  }

  async function handleDeleteSelectedGalleryPhotos() {
    if (selectedGalleryPhotoIds.length === 0) {
      return;
    }
    if (!window.confirm(`确认删除选中的 ${selectedGalleryPhotoIds.length} 张图库图片吗？这会删除图片文件、识别记录和向量数据。`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await batchDeleteGalleryPhotos(selectedGalleryPhotoIds);
      if (selectedPhoto && selectedGalleryPhotoIds.includes(selectedPhoto.id)) {
        setSelectedPhoto(null);
      }
      setSelectedGalleryPhotoIds([]);
      setGallerySelectionMode(false);
      await refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量删除图库图片失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteCurrentPhoto() {
    if (!selectedPhoto) {
      return;
    }
    if (!window.confirm(`确认删除当前图片（ID: ${selectedPhoto.id}）吗？`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteGalleryPhoto(selectedPhoto.id);
      setSelectedGalleryPhotoIds((current) => current.filter((id) => id !== selectedPhoto.id));
      setSelectedPhoto(null);
      await refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除图片失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleReRecognize() {
    if (!selectedPhoto) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await reRecognizeGalleryPhoto(selectedPhoto.id);
      setSelectedPhoto(detail);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "重新识别失败。");
    } finally {
      setBusy(false);
    }
  }

  const totalPages = Math.ceil(galleryTotal / galleryPageSize);
  const currentPage = Math.floor(galleryOffset / galleryPageSize) + 1;

  function handleJumpToPage() {
    const pageNum = parseInt(jumpPageInput, 10);
    if (isNaN(pageNum) || pageNum < 1 || pageNum > totalPages) {
      setError(`请输入 1-${totalPages} 之间的页码`);
      return;
    }
    const newOffset = (pageNum - 1) * galleryPageSize;
    void refreshGallery(newOffset, selectedPersonIds, selectedTagIds);
    setJumpPageInput("");
  }

  const availablePersonsForPhoto = selectedPhoto
    ? persons.filter((person) => !person.is_unknown && !selectedPhoto.persons.some((tag) => tag.person_id === person.id))
    : persons.filter((person) => !person.is_unknown);

  const selectedPhotoTags = selectedPhoto ? sortByPinyinName(selectedPhoto.tags) : [];

  const availableTagsForPhoto = selectedPhoto
    ? sortByPinyinName(tags.filter((tag) => !tag.is_system && !selectedPhoto.tags.some((item) => item.id === tag.id)))
    : sortByPinyinName(tags.filter((tag) => !tag.is_system));

  const lightboxIndex = lightboxPhotoId === null ? -1 : galleryPhotos.findIndex((photo) => photo.id === lightboxPhotoId);
  const lightboxPhoto = lightboxIndex >= 0 ? galleryPhotos[lightboxIndex] : null;

  useEffect(() => {
    if (lightboxPhoto && lightboxPhoto.is_rich_text) {
      setLightboxRichTextDraft(lightboxPhoto.rich_text || "");
    }
  }, [lightboxPhoto]);
  const isFirstOfPage = lightboxIndex === 0;
  const isLastOfPage = lightboxIndex === galleryPhotos.length - 1;
  const hasPrevPage = galleryOffset > 0;
  const hasNextPage = galleryOffset + galleryPageSize < galleryTotal;

  const canGoPrev = lightboxIndex > 0 || hasPrevPage;
  const canGoNext = lightboxIndex >= 0 && (!isLastOfPage || hasNextPage);

  async function goPrevLightbox() {
    if (lightboxIndex > 0) {
      setLightboxPhotoId(galleryPhotos[lightboxIndex - 1].id);
    } else if (hasPrevPage) {
      const newOffset = Math.max(0, galleryOffset - galleryPageSize);
      setBusy(true);
      try {
        const response = await listGalleryPhotos(selectedPersonIds, selectedTagIds, excludePersonIds, excludeTagIds, newOffset, galleryPageSize);
        setGalleryPhotos(response.items);
        setGalleryTotal(response.total);
        setGalleryOffset(response.offset);
        setSelectedGalleryPhotoIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
        if (response.items.length > 0) {
          setLightboxPhotoId(response.items[response.items.length - 1].id);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "翻页失败");
      } finally {
        setBusy(false);
      }
    }
  }

  async function goNextLightbox() {
    if (lightboxIndex >= 0 && lightboxIndex < galleryPhotos.length - 1) {
      setLightboxPhotoId(galleryPhotos[lightboxIndex + 1].id);
    } else if (hasNextPage) {
      const newOffset = galleryOffset + galleryPageSize;
      setBusy(true);
      try {
        const response = await listGalleryPhotos(selectedPersonIds, selectedTagIds, excludePersonIds, excludeTagIds, newOffset, galleryPageSize);
        setGalleryPhotos(response.items);
        setGalleryTotal(response.total);
        setGalleryOffset(response.offset);
        setSelectedGalleryPhotoIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
        if (response.items.length > 0) {
          setLightboxPhotoId(response.items[0].id);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "翻页失败");
      } finally {
        setBusy(false);
      }
    }
  }

  useEffect(() => {
    if (!lightboxPhoto) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (busy) return;
      if (lightboxEditMode) return;
      if (event.key === "Escape") {
        closeGalleryLightbox();
      } else if (event.key === "ArrowLeft") {
        void goPrevLightbox();
      } else if (event.key === "ArrowRight") {
        void goNextLightbox();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [lightboxPhoto, lightboxIndex, canGoPrev, canGoNext, hasPrevPage, hasNextPage, galleryOffset, busy, lightboxEditMode]);


  const GalleryPageComponent = () => {
    return (
        <main className="page-grid gallery-page">
          <section className="panel filter-panel">
            <div className="section-head">
              <div>
                <p className="eyebrow">筛选器</p>
                <h2>人物 + 自定义标签</h2>
              </div>
              <span>组内 OR，组间 AND</span>
            </div>

            <div className="filter-group">
              <label>按人物筛选</label>
              <input
                className="search-input subtle"
                value={personSearch}
                onChange={(event) => setPersonSearch(event.target.value)}
                placeholder="搜索人物名"
              />
              <div className="filter-stack">
                {selectedFilterPersons.length > 0 && (
                  <div className="filter-section selected-filter-section">
                    <div className="filter-section-head">
                      <strong>已选人物</strong>
                      <span>
                        {selectedFilterPersons.length} 个{selectedUnknownPersonCount > 0 ? ` · 未知 ${selectedUnknownPersonCount}` : ""}
                      </span>
                    </div>
                    <div className="chip-cloud compact scroll-cloud selected-cloud">
                      {selectedFilterPersons.map((person) => (
                        <button
                          key={person.id}
                          className={person.is_unknown ? "soft-chip active unknown-chip" : "soft-chip active"}
                          onClick={() => handleTogglePersonFilter(person.id)}
                        >
                          {person.display_name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="filter-section">
                  <div className="filter-section-head">
                    <strong>正式人物</strong>
                    <span>{knownFilterPersons.length} 个</span>
                  </div>
                  <div className="chip-cloud compact scroll-cloud known-person-cloud">
                    {knownFilterPersons.map((person) => (
                      <button
                        key={person.id}
                        className="soft-chip"
                        onClick={() => handleTogglePersonFilter(person.id)}
                      >
                        {person.display_name}
                      </button>
                    ))}
                    {knownFilterPersons.length === 0 && <span className="filter-empty">没有匹配的正式人物</span>}
                  </div>
                </div>

                <div className="filter-section">
                  <div className="filter-section-toolbar">
                    <button
                      className="filter-section-toggle"
                      onClick={() => setShowUnknownPersons((current) => !current)}
                      type="button"
                    >
                      <span>未知人物</span>
                      <small>
                        {personSearchActive ? `${allFilteredUnknownPersons.length} / ${unknownPersonCount}` : `${unknownPersonCount} 个`}
                      </small>
                      <b>{showUnknownPersons || personSearchActive ? "收起" : "展开"}</b>
                    </button>
                    <button
                      className="filter-bulk-action"
                      disabled={allFilteredUnknownPersons.length === 0}
                      onClick={handleToggleUnknownPersonFilters}
                      type="button"
                    >
                      {allFilteredUnknownSelected ? "全不选" : "全选"}
                    </button>
                  </div>
                  {(showUnknownPersons || personSearchActive) && (
                    <div className="chip-cloud compact scroll-cloud unknown-person-cloud">
                      {visibleUnknownFilterPersons.map((person) => (
                        <button
                          key={person.id}
                          className="soft-chip unknown-chip"
                          onClick={() => handleTogglePersonFilter(person.id)}
                        >
                          {person.display_name}
                        </button>
                      ))}
                      {visibleUnknownFilterPersons.length === 0 && <span className="filter-empty">没有匹配的未知人物</span>}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="filter-group">
              <label>按普通标签筛选</label>
              <input
                className="search-input subtle"
                value={tagSearch}
                onChange={(event) => setTagSearch(event.target.value)}
                placeholder="搜索标签"
              />
              <div className="chip-cloud compact scroll-cloud tag-filter-cloud">
                {filteredTags.map((tag) => {
                  const active = selectedTagIds.includes(tag.id);
                  const inExclude = excludeTagIds.includes(tag.id);
                  return (
                    <button
                      key={tag.id}
                      className={active ? "soft-chip active" : "soft-chip"}
                      onClick={() => {
                        const next = active ? selectedTagIds.filter((id) => id !== tag.id) : [...selectedTagIds, tag.id];
                        setSelectedTagIds(next);
                        let nextExclude = excludeTagIds;
                        if (!active && excludeTagIds.includes(tag.id)) {
                          nextExclude = excludeTagIds.filter((id) => id !== tag.id);
                          setExcludeTagIds(nextExclude);
                        }
                        void refreshGallery(0, selectedPersonIds, next, excludePersonIds, nextExclude);
                      }}
                    >
                      #{tag.name}
                    </button>
                  );
                })}
                {filteredTags.length === 0 && <span className="filter-empty">没有匹配的普通标签</span>}
              </div>
            </div>

            <div className="filter-group">
              <label>排除筛选 · 不含所选条件的图片</label>

              <div className="filter-section">
                <div className="filter-section-toolbar">
                  <button
                    className="filter-section-toggle"
                    onClick={() => setShowExcludePersons((current) => !current)}
                    type="button"
                  >
                    <span>排除的人物</span>
                    <small>{excludedFilterPersons.length > 0 ? `${excludedFilterPersons.length} 个已选` : `${availableExcludePersons.length} 个可选`}</small>
                    <b>{showExcludePersons ? "收起" : "展开"}</b>
                  </button>
                </div>
                {showExcludePersons && (
                  <>
                    {excludedFilterPersons.length > 0 && (
                      <div className="filter-section selected-filter-section">
                        <div className="filter-section-head">
                          <strong>已选排除</strong>
                          <span>{excludedFilterPersons.length} 个</span>
                        </div>
                        <div className="chip-cloud compact scroll-cloud selected-cloud">
                          {excludedFilterPersons.map((person) => (
                            <button
                              key={person.id}
                              className={person.is_unknown ? "soft-chip active unknown-chip" : "soft-chip active"}
                              onClick={() => handleToggleExcludePerson(person.id)}
                            >
                              {person.display_name} ✕
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="filter-section">
                      <div className="filter-section-head">
                        <strong>正式人物</strong>
                        <span>{availableExcludeKnownPersons.length} 个</span>
                      </div>
                      <div className="chip-cloud compact scroll-cloud known-person-cloud">
                        {availableExcludeKnownPersons.map((person) => (
                          <button
                            key={person.id}
                            className="soft-chip"
                            onClick={() => handleToggleExcludePerson(person.id)}
                          >
                            {person.display_name}
                          </button>
                        ))}
                        {availableExcludeKnownPersons.length === 0 && <span className="filter-empty">没有可选人物</span>}
                      </div>
                    </div>
                    <div className="filter-section">
                      <div className="filter-section-head">
                        <strong>未知人物</strong>
                        <span>{availableExcludeUnknownPersons.length} 个</span>
                      </div>
                      <div className="chip-cloud compact scroll-cloud unknown-person-cloud">
                        {availableExcludeUnknownPersons.map((person) => (
                          <button
                            key={person.id}
                            className="soft-chip"
                            onClick={() => handleToggleExcludePerson(person.id)}
                          >
                            {person.display_name}
                          </button>
                        ))}
                        {availableExcludeUnknownPersons.length === 0 && <span className="filter-empty">没有可选人物</span>}
                      </div>
                    </div>
                  </>
                )}
              </div>

              <div className="filter-section">
                <div className="filter-section-toolbar">
                  <button
                    className="filter-section-toggle"
                    onClick={() => setShowExcludeTags((current) => !current)}
                    type="button"
                  >
                    <span>排除的标签</span>
                    <small>{excludedFilterTags.length > 0 ? `${excludedFilterTags.length} 个已选` : `${availableExcludeTags.length} 个可选`}</small>
                    <b>{showExcludeTags ? "收起" : "展开"}</b>
                  </button>
                </div>
                {showExcludeTags && (
                  <>
                    {excludedFilterTags.length > 0 && (
                      <div className="filter-section selected-filter-section">
                        <div className="filter-section-head">
                          <strong>已选排除</strong>
                          <span>{excludedFilterTags.length} 个</span>
                        </div>
                        <div className="chip-cloud compact scroll-cloud selected-cloud">
                          {excludedFilterTags.map((tag) => (
                            <button
                              key={tag.id}
                              className="soft-chip active"
                              onClick={() => handleToggleExcludeTag(tag.id)}
                            >
                              #{tag.name}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="chip-cloud compact scroll-cloud tag-filter-cloud">
                      {availableExcludeTags.map((tag) => (
                        <button
                          key={tag.id}
                          className="soft-chip"
                          onClick={() => handleToggleExcludeTag(tag.id)}
                        >
                          #{tag.name}
                        </button>
                      ))}
                      {availableExcludeTags.length === 0 && <span className="filter-empty">没有可选标签</span>}
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>

          <section className="panel gallery-panel">
            <div className="section-head">
              <div>
                <p className="eyebrow">展示图库</p>
                <h2>按条件浏览图片</h2>
              </div>
              <div className="micro-row section-actions">
                <span>{galleryTotal} 张结果</span>
                <button disabled={busy} onClick={() => toggleGallerySelectionMode()}>
                  {gallerySelectionMode ? "取消选择" : "选择图片"}
                </button>
                <button disabled={busy} onClick={openGalleryExportModal}>
                  导出展示图
                </button>
                <button disabled={busy} onClick={handlePickGalleryImportFile}>
                  导入展示图
                </button>
                <button
                  disabled={busy || !gallerySelectionMode || selectedGalleryPhotoIds.length === 0}
                  onClick={() => void handleDeleteSelectedGalleryPhotos()}
                >
                  删除选中（{selectedGalleryPhotoIds.length}）
                </button>
                <input
                  ref={galleryImportFileRef}
                  type="file"
                  accept=".zip"
                  style={{ display: "none" }}
                  onChange={(event) => void handleGalleryImportFileChange(event)}
                />
                {galleryImportTask && galleryImportTask.status !== "completed" && galleryImportTask.status !== "failed" && (
                  <div className="task-bar gallery-task">
                    <progress value={galleryImportTask.progress} max={1}></progress>
                    <span>{galleryImportTask.message}</span>
                  </div>
                )}
                {galleryImportTask && galleryImportTask.status === "completed" && (
                  <div className="task-bar success gallery-task">
                    <span>{galleryImportTask.message}</span>
                  </div>
                )}
                {galleryImportTask && galleryImportTask.status === "failed" && (
                  <div className="task-bar error gallery-task">
                    <span>导入失败：{galleryImportTask.message}</span>
                  </div>
                )}
              </div>
            </div>

            <div className="gallery-grid">
              {galleryPhotos.map((photo) => {
                const isLandscape = photo.width && photo.height && photo.width / photo.height > 1.15;
                const wrapClass = photo.is_rich_text
                  ? "photo-card-wrap rich-card-wrap"
                  : `photo-card-wrap ${isLandscape ? "span-2" : ""}`;

                return (
                  <article key={photo.id} className={wrapClass}>
                    <button className={photo.is_rich_text ? "photo-card rich-card" : "photo-card"} onClick={() => openGalleryLightbox(photo.id)}>
                    {photo.is_rich_text ? (
                      <div className="rich-card-layout">
                        <img src={withImageWidth(photo.thumbnail_url, 720)} alt="图库预览" loading="lazy" />
                        <div className="rich-card-copy">
                          <p className="rich-snippet">{photo.rich_text || "未识别到文本，可在详情里手动补录。"}</p>
                          <div className="micro-row">
                            {photo.persons.map((person) => (
                              <small key={`${photo.id}-p-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                                {person.person_name}
                              </small>
                            ))}
                          </div>
                          <div className="micro-row">
                            {sortByPinyinName(photo.tags).map((tag) => (
                              <small key={`${photo.id}-t-${tag.id}`} className="pill muted">
                                #{tag.name}
                              </small>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <>
                        <img src={withImageWidth(photo.thumbnail_url, 720)} alt="图库预览" loading="lazy" />
                        <div className="photo-meta">
                          <div className="micro-row">
                            {photo.persons.map((person) => (
                              <small key={`${photo.id}-p-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                                {person.person_name}
                              </small>
                            ))}
                          </div>
                          <div className="micro-row">
                            {sortByPinyinName(photo.tags).map((tag) => (
                              <small key={`${photo.id}-t-${tag.id}`} className="pill muted">
                                #{tag.name}
                              </small>
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                  </button>
                  <button
                    className="photo-detail-trigger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void openGalleryPhoto(photo.id);
                    }}
                  >
                    详情
                  </button>
                  {gallerySelectionMode && (
                    <label className="corner-check">
                      <input
                        type="checkbox"
                        checked={selectedGalleryPhotoIds.includes(photo.id)}
                        onChange={(event) => {
                          setSelectedGalleryPhotoIds((current) =>
                            event.target.checked ? [...current, photo.id] : current.filter((id) => id !== photo.id)
                          );
                        }}
                      />
                    </label>
                  )}
                </article>
              );
            })}
              {galleryPhotos.length === 0 && <div className="empty-card">当前筛选条件下没有展示图。</div>}
            </div>

            <div className="pagination-row">
              <button disabled={galleryOffset === 0 || busy} onClick={() => void refreshGallery(Math.max(0, galleryOffset - galleryPageSize))}>
                上一页
              </button>
              <span>
                第 {currentPage} / {totalPages} 页 ({galleryTotal === 0 ? 0 : galleryOffset + 1} - {Math.min(galleryOffset + galleryPageSize, galleryTotal)} / {galleryTotal})
              </span>
              <button
                disabled={galleryOffset + galleryPageSize >= galleryTotal || busy}
                onClick={() => void refreshGallery(galleryOffset + galleryPageSize)}
              >
                下一页
              </button>
              <div className="jump-to-page">
                <input
                  type="number"
                  min={1}
                  max={totalPages}
                  value={jumpPageInput}
                  onChange={(e) => setJumpPageInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleJumpToPage();
                    }
                  }}
                  placeholder="页码"
                />
                <button disabled={busy || !jumpPageInput} onClick={() => handleJumpToPage()}>
                  跳转
                </button>
              </div>
            </div>
          </section>

          <aside ref={galleryDetailRef} className="panel detail-panel">
            <div className="section-head">
              <div>
                <p className="eyebrow">详情</p>
                <h2>单张图修正</h2>
              </div>
              <div className="micro-row">
                <span>{selectedPhoto ? `${selectedPhoto.faces.length} 张脸` : "未选中图片"}</span>
                <button disabled={busy || !selectedPhoto} onClick={() => void handleReRecognize()}>
                  重新识别
                </button>
                <button disabled={busy || !selectedPhoto} onClick={() => void handleDeleteCurrentPhoto()}>
                  删除当前图
                </button>
              </div>
            </div>
            {selectedPhoto ? (
              <>
                <a className="detail-image-wrap" href={selectedPhoto.original_url} target="_blank" rel="noreferrer">
                  <img className="detail-image" src={selectedPhoto.original_url} alt="原图预览" />
                </a>
                <div className="detail-copy">
                  <h3>图片详情</h3>
                  <p>{formatDate(selectedPhoto.taken_at || selectedPhoto.created_at)}</p>
                  <p>
                    {selectedPhoto.width} × {selectedPhoto.height}
                  </p>
                </div>

                <div className="editor-block">
                  <label>人物标签</label>
                  <div className="micro-row wrap">
                    {selectedPhoto.persons.map((person) => (
                      <button
                        key={person.person_id}
                        className={person.is_unknown ? "pill unknown action-pill" : "pill action-pill"}
                        onClick={() => void handleDeletePhotoPerson(person.person_id)}
                      >
                        {person.person_name}
                      </button>
                    ))}
                  </div>
                  <div className="inline-editor inline-editor-triple">
                    <select value={manualPersonId} onChange={(event) => setManualPersonId(event.target.value)}>
                      <option value="">选择人物添加到当前图片</option>
                      {availablePersonsForPhoto.map((person) => (
                        <option key={person.id} value={person.id}>
                          {person.display_name}
                        </option>
                      ))}
                    </select>
                    <button disabled={busy || !manualPersonId} onClick={() => void handleAddPhotoPerson()}>
                      添加人物
                    </button>
                  </div>
                  {selectedPhoto.faces.length !== 1 && <p className="tip">多人图只改展示标签，不自动写入人物向量库。</p>}
                </div>

                <div className="editor-block">
                  <label>普通标签</label>
                  <div className="micro-row wrap">
                    {selectedPhotoTags.map((tag) => (
                      tag.is_system ? (
                        <span key={tag.id} className="pill muted">
                          #{tag.name}
                        </span>
                      ) : (
                        <button key={tag.id} className="pill muted action-pill" onClick={() => void handleDeletePhotoTag(tag.id)}>
                          #{tag.name}
                        </button>
                      )
                    ))}
                  </div>
                  <div className="stack-editor">
                    <div className="inline-editor">
                      <select value={manualTagId} onChange={(event) => setManualTagId(event.target.value)}>
                        <option value="">选择已有标签</option>
                        {availableTagsForPhoto.map((tag) => (
                          <option key={tag.id} value={tag.id}>
                            #{tag.name}
                          </option>
                        ))}
                      </select>
                      <button disabled={busy || !manualTagId} onClick={() => void handleAddPhotoTag()}>
                        添加已有标签
                      </button>
                    </div>
                    <div className="inline-editor">
                      <input
                        value={manualTagName}
                        onChange={(event) => setManualTagName(event.target.value)}
                        placeholder="输入新标签名称"
                      />
                      <button disabled={busy || !manualTagName.trim()} onClick={() => void handleAddPhotoTag()}>
                        新建并添加
                      </button>
                    </div>
                  </div>
                </div>

                {selectedPhoto.is_rich_text && (
                  <div className="editor-block">
                    <label>图文文本（可手动编辑）</label>
                    <textarea
                      className="rich-text-editor"
                      value={richTextDraft}
                      onChange={(event) => setRichTextDraft(event.target.value)}
                      placeholder="输入或修正文案内容"
                    />
                    <div className="micro-row">
                      <span>OCR状态：{selectedPhoto.ocr_status ?? "unknown"}</span>
                      <button disabled={busy} onClick={() => void handleSaveRichText()}>
                        保存图文文本
                      </button>
                    </div>
                  </div>
                )}

                <div className="face-list">
                  {selectedPhoto.faces.map((face) => (
                    <article key={face.id}>
                      <strong>Face #{face.id}</strong>
                      <span>{face.needs_review ? "待人工确认" : "已确认"}</span>
                      <span>{face.match_score ? `score ${face.match_score.toFixed(3)}` : "无匹配分数"}</span>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-card">从左侧图库点击任意图片后，这里会显示识别结果和修正操作。</div>
            )}
          </aside>
        </main>
    );
  };

  const PeoplePageComponent = () => {
    return (
        <main className="page-grid people-page">
          <section className="panel people-sidebar">
            <div className="section-head">
              <div>
                <p className="eyebrow">人物库</p>
                <h2>创建与选择人物</h2>
              </div>
              <div className="people-count-badge">
                <span>{persons.length} 人</span>
              </div>
            </div>

            <div className="people-commandbar">
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy} onClick={() => togglePeopleBatchDeleteMode()}>
                  <Trash2 size={15} aria-hidden="true" />
                  {peopleBatchDeleteMode ? "取消批量" : "批量删除"}
                </button>
                <button
                  disabled={busy || !peopleBatchDeleteMode || selectedPersonDeleteCount === 0}
                  onClick={() => void handleDeleteSelectedPersons()}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  删除选中（{selectedPersonDeleteCount}）
                </button>
              </div>
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy || unknownPersonCount === 0} onClick={() => void handleReRecognizeAllUnknownPhotos()}>
                  <RotateCcw size={15} aria-hidden="true" />
                  一键重新识别所有未知人物
                </button>
              </div>
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy} onClick={handleExportPersons}>
                  <Download size={15} aria-hidden="true" />
                  导出样本库
                </button>
                <button disabled={busy} onClick={handlePickImportFile}>
                  <FileUp size={15} aria-hidden="true" />
                  导入样本库
                </button>
              </div>
                <input
                  ref={importFileRef}
                  type="file"
                  accept=".zip"
                  style={{ display: "none" }}
                  onChange={(event) => void handleImportFileChange(event)}
                />
                {importTask && importTask.status !== "completed" && importTask.status !== "failed" && (
                  <div className="task-bar">
                    <progress value={importTask.progress} max={1}></progress>
                    <span>{importTask.message}</span>
                  </div>
                )}
                {importTask && importTask.status === "completed" && (
                  <div className="task-bar success">
                    <span>{importTask.message}</span>
                  </div>
                )}
                {importTask && importTask.status === "failed" && (
                  <div className="task-bar error">
                    <span>导入失败：{importTask.message}</span>
                  </div>
                )}
            </div>

            <div className="inline-editor people-create-row">
              <input value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} placeholder="输入新人物名称" />
              <button disabled={busy || !newPersonName.trim()} onClick={() => void handleCreatePerson()}>
                <UserPlus size={15} aria-hidden="true" />
                创建人物
              </button>
            </div>

            <label className="people-search">
              <Search size={16} aria-hidden="true" />
              <input
                className="search-input subtle"
                value={peopleSearch}
                onChange={(event) => setPeopleSearch(event.target.value)}
                placeholder="搜索人物（样本库）"
              />
            </label>

            <div className="person-list">
              {filteredPeopleInLibrary.map((person) => (
                <article key={person.id} className="person-card-wrap">
                  <button
                    className={selectedPerson?.id === person.id ? "person-card active" : "person-card"}
                    onClick={() => handleSelectPerson(person)}
                  >
                    <span className={person.is_unknown ? "person-avatar-marker unknown" : "person-avatar-marker"}>
                      {person.display_name.slice(0, 1)}
                    </span>
                    <div className="person-card-main">
                      <strong>{person.display_name}</strong>
                      <span>{person.is_unknown ? "未知人物" : "正式人物"}</span>
                    </div>
                    <small className="person-card-stats">
                      <b>{person.sample_count}</b>
                      <span>样本</span>
                      <b>{person.gallery_photo_count}</b>
                      <span>图库</span>
                    </small>
                  </button>
                  {peopleBatchDeleteMode && (
                    <label className="row-check">
                      <input
                        type="checkbox"
                        disabled={isSystemUnknownPerson(person)}
                        checked={selectedPersonDeleteIds.includes(person.id)}
                        onChange={(event) => {
                          if (isSystemUnknownPerson(person)) {
                            return;
                          }
                          setSelectedPersonDeleteIds((current) =>
                            event.target.checked ? [...current, person.id] : current.filter((id) => id !== person.id)
                          );
                        }}
                      />
                      <span>选中删除</span>
                    </label>
                  )}
                </article>
              ))}
              {filteredPeopleInLibrary.length === 0 && <div className="empty-card">没有匹配的人物。</div>}
            </div>
          </section>

          <section ref={peopleMainRef} className="panel people-main">
            {selectedPerson ? (
              <>
                <div className="section-head">
                  <div>
                    <p className="eyebrow">人物详情</p>
                    <h2>{selectedPerson.display_name}</h2>
                  </div>
                  <div className="micro-row">
                    <span>{selectedPersonIsSystemUnknown ? "图库未知标签" : selectedPerson.is_unknown ? "未知人物" : "样本库维护"}</span>
                    <button disabled={busy || selectedPersonIsSystemUnknown} onClick={() => void handleDeleteCurrentPerson()}>
                      删除当前人物
                    </button>
                  </div>
                </div>

                {!selectedPersonIsSystemUnknown && (
                  <>
                    <div className="rename-strip">
                      <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} placeholder="输入新名字" />
                      <button disabled={busy || !renameValue.trim()} onClick={() => void handleRenamePerson()}>
                        {selectedPerson.is_unknown ? "转正并改名" : "更新名称"}
                      </button>
                    </div>

                    <div className="editor-block">
                      <label>人物普通标签（自动继承到该人物相关图库图片）</label>
                      <div className="micro-row wrap">
                        {personTags.map((tag) => (
                          <button key={tag.id} className="pill muted action-pill" onClick={() => void handleUnbindPersonTag(tag.id)}>
                            #{tag.name}
                          </button>
                        ))}
                        {personTags.length === 0 && <span className="tip">还没有人物级普通标签。</span>}
                      </div>
                      <div className="stack-editor">
                        <div className="inline-editor">
                          <select value={personTagSelectId} onChange={(event) => setPersonTagSelectId(event.target.value)}>
                            <option value="">从已有标签添加</option>
                            {sortByPinyinName(tags.filter((tag) => !personTags.some((item) => item.id === tag.id))).map((tag) => (
                              <option key={tag.id} value={tag.id}>
                                #{tag.name}
                              </option>
                            ))}
                          </select>
                          <button disabled={busy || !personTagSelectId} onClick={() => void handleBindPersonTag()}>
                            添加已有标签
                          </button>
                        </div>
                        <div className="inline-editor">
                          <input
                            value={personTagName}
                            onChange={(event) => setPersonTagName(event.target.value)}
                            placeholder="输入新标签名称"
                          />
                          <button disabled={busy || !personTagName.trim()} onClick={() => void handleBindPersonTag()}>
                            新建并添加
                          </button>
                        </div>
                      </div>
                    </div>

                    <label className="upload-box">
                      <input type="file" multiple accept="image/*" onChange={(event) => handlePickSampleFiles(event.target.files)} />
                      <strong>上传人物样本图</strong>
                      <span>先预览样本，再点击确认上传；仅接受单张照片恰好一张脸的样本进入向量库。</span>
                    </label>
                  </>
                )}

                {!selectedPersonIsSystemUnknown && pendingSampleUploads.length > 0 && (
                  <div className="editor-block">
                    <label>待上传样本预览（{pendingSampleUploads.length}）</label>
                    <div className="pending-grid">
                      {pendingSampleUploads.map((item, index) => (
                        <article key={`${item.file.name}-${index}`} className="pending-card">
                          <img src={item.previewUrl} alt="样本预览" />
                          <div>
                            <strong>待上传样本 {index + 1}</strong>
                            <span>{Math.round(item.file.size / 1024)} KB</span>
                          </div>
                          <button className="ghost-button" onClick={() => handleRemovePendingSample(index)}>
                            移除
                          </button>
                        </article>
                      ))}
                    </div>
                    <button disabled={busy} onClick={() => void handleConfirmSampleUpload()}>
                      确认上传样本
                    </button>
                  </div>
                )}

                <div className="sample-grid">
                  {samples.map((sample) => {
                    const isLandscape = sample.width && sample.height && sample.width / sample.height > 1.15;
                    const cardClass = `sample-card ${isLandscape ? "span-2" : ""}`;

                    return (
                      <article key={sample.id} className={cardClass}>
                        <a href={sample.original_url} target="_blank" rel="noreferrer">
                          <img src={withImageWidth(sample.thumbnail_url, 480)} alt="样本缩略图" />
                        </a>
                        <div className="sample-copy">
                          <strong>样本记录 #{sample.id}</strong>
                          <span>{formatDate(sample.taken_at || sample.created_at)}</span>
                          <small className={`status-pill status-${sample.status}`}>{sample.status}</small>
                          {sample.error_message && <p>{sample.error_message}</p>}
                        </div>
                        {!selectedPersonIsSystemUnknown && (
                          <button className="ghost-button" onClick={() => void handleDeleteSample(sample.id)}>
                            删除样本
                          </button>
                        )}
                      </article>
                    );
                  })}
                  {samples.length === 0 && <div className="empty-card">当前人物还没有样本图片。</div>}
                </div>
              </>
            ) : (
              <div className="empty-card">左侧选择一个人物后，在这里维护样本图。</div>
            )}
          </section>
        </main>
    );
  };

  const renderUploadPage = () => {
    const queueTotal = videoUploadQueue.length;
    const queueCompleted = videoUploadQueue.filter((item) => item.status === "completed").length;
    const queueFailed = videoUploadQueue.filter((item) => item.status === "failed").length;
    const queueNeedsFile = videoUploadQueue.filter((item) => item.status === "needs_file").length;
    const queueUploading = videoUploadQueue.find((item) => item.status === "uploading");
    const queueProgress =
      queueTotal > 0
        ? Math.round(videoUploadQueue.reduce((sum, item) => sum + item.progress, 0) / queueTotal)
        : videoUploadProgress;
    let videoUploadState = "待选择";
    if (queueTotal > 0) {
      videoUploadState =
        videoUploadBusy && videoUploadTotalCount > 0
          ? `上传中 ${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / ${videoUploadTotalCount}`
          : `队列 ${queueTotal} 个，完成 ${queueCompleted} 个`;
    } else if (videoUploadTotalCount > 0) {
      videoUploadState = `上传中 ${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / ${videoUploadTotalCount}`;
    } else if (videoFiles.length > 0) {
      videoUploadState = `已选择 ${videoFiles.length} 个视频`;
    }
    let videoUploadNote = "支持长视频分片上传，上传后自动转为网页可播放格式。";
    if (queueNeedsFile > 0) {
      videoUploadNote = `${queueNeedsFile} 个视频需要重新选择原文件后继续上传。`;
    } else if (queueFailed > 0) {
      videoUploadNote = `${queueFailed} 个视频上传失败，可重新选择原文件后继续。`;
    } else if (queueUploading) {
      videoUploadNote = queueUploading.filename;
    } else if (videoUploadQueue.length > 0) {
      videoUploadNote = videoUploadQueue.map((item) => item.filename).join("、");
    } else if (videoFiles.length > 0) {
      videoUploadNote = videoFiles.map((file) => file.name).join("、");
    }

    return (
        <main className="page-grid upload-page">
          <section className="panel upload-main">
            <div className="section-head">
              <div>
                <p className="eyebrow">素材上传</p>
                <h2>图片与视频统一入库</h2>
              </div>
              <span>批量导入工作台</span>
            </div>

            <div className="upload-channel-grid">
              <article className="upload-channel-card upload-channel-card-image">
                <div className="upload-channel-head">
                  <span className="upload-channel-icon">
                    <ImagePlus size={22} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="eyebrow">图片入库</p>
                    <h3>展示图识别</h3>
                  </div>
                </div>
                <div className="upload-mode-switch">
                  <button
                    className={uploadMode === "normal" ? "soft-chip active" : "soft-chip"}
                    onClick={() => setUploadMode("normal")}
                  >
                    普通图片
                  </button>
                  <button className={uploadMode === "rich" ? "soft-chip active" : "soft-chip"} onClick={() => setUploadMode("rich")}>
                    图文图片
                  </button>
                </div>
                <label className="upload-box large upload-box-image">
                  <input type="file" multiple accept="image/*" onChange={(event) => handlePickGalleryFiles(event.target.files)} />
                  <strong>{uploadMode === "rich" ? "选择图文图片" : "选择展示图片"}</strong>
                  <span>
                    {uploadMode === "rich"
                      ? "可补录文本或留空走 OCR，并自动执行人脸识别。"
                      : "预览后填写人物和标签，再统一提交到识别队列。"}
                  </span>
                </label>
                <small className="upload-channel-note">
                  {uploadMode === "rich"
                    ? `将自动打 #图文 标签${richTag ? "" : "（系统会自动创建）"}`
                    : "沿用普通图片流程：人脸识别 + 人物标签 + 普通标签"}
                </small>
              </article>

              <article className="upload-channel-card upload-channel-card-video">
                <div className="upload-channel-head">
                  <span className="upload-channel-icon">
                    <Clapperboard size={22} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="eyebrow">视频入库</p>
                    <h3>分片上传</h3>
                  </div>
                </div>
                <div className="upload-channel-status">
                  <strong>{videoUploadState}</strong>
                  <span>{videoUploadNote}</span>
                </div>
                <div className="upload-channel-progress">
                  <div className="meter">
                    <span style={{ width: `${queueProgress}%` }} />
                  </div>
                  <small>{queueProgress}%</small>
                </div>
                <button className="primary upload-video-entry" onClick={() => setIsVideoUploadModalOpen(true)}>
                  <UploadCloud size={16} aria-hidden="true" />
                  上传视频
                </button>
              </article>
            </div>

            {pendingGalleryUploads.length > 0 && (
              <div className="editor-block">
                <div className="stack-editor">
                  <label>批量套用到全部待上传图片</label>
                  <div className="inline-editor">
                    <input
                      value={batchApplyPersonNames}
                      onChange={(event) => setBatchApplyPersonNames(event.target.value)}
                      placeholder="人物名字（逗号分隔）"
                    />
                    <input
                      value={batchApplyTagNames}
                      onChange={(event) => setBatchApplyTagNames(event.target.value)}
                      placeholder="普通标签（逗号分隔）"
                    />
                    <button disabled={galleryUploadBusy} onClick={() => handleApplyBatchMetadataToAll()}>
                      批量套用
                    </button>
                  </div>
                </div>
                <label>待上传图片（{pendingGalleryUploads.length}）</label>
                <div className="pending-grid pending-grid-gallery">
                  {pendingGalleryUploads.map((item, index) => (
                    <article key={`${item.file.name}-${index}`} className="pending-card pending-card-gallery">
                      <img src={item.previewUrl} alt="待上传预览" />
                      <div className="pending-card-copy">
                        <strong>待上传图片 {index + 1}</strong>
                        <span>{Math.round(item.file.size / 1024)} KB</span>
                        <input
                          value={item.personNamesText}
                          onChange={(event) => handleUpdatePendingGallery(index, { personNamesText: event.target.value })}
                          placeholder="人物名字（逗号分隔，可留空）"
                        />
                        <input
                          value={item.tagNamesText}
                          onChange={(event) => handleUpdatePendingGallery(index, { tagNamesText: event.target.value })}
                          placeholder="普通标签（逗号分隔，可留空）"
                        />
                        {uploadMode === "rich" && (
                          <textarea
                            className="rich-text-editor compact"
                            value={item.richText}
                            onChange={(event) => handleUpdatePendingGallery(index, { richText: event.target.value })}
                            placeholder="图文文本（可留空，后端自动OCR）"
                          />
                        )}
                      </div>
                      <button className="ghost-button" onClick={() => handleRemovePendingGallery(index)}>
                        移除
                      </button>
                    </article>
                  ))}
                </div>
                <button disabled={galleryUploadBusy} onClick={() => void handleConfirmGalleryUpload()}>
                  确认上传（批量）
                </button>
              </div>
            )}
          </section>

          <aside className="panel upload-side">
            <div className="section-head">
              <div>
                <p className="eyebrow">任务状态</p>
                <h2>识别进度</h2>
              </div>
            </div>

            <div className="task-box">
              <strong>{task ? task.status : "idle"}</strong>
              <p>{task?.message ?? "上传后会在这里看到导入进度和识别摘要。"}</p>
              <div className="meter">
                <span style={{ width: `${Math.round((task?.progress ?? 0) * 100)}%` }} />
              </div>
            </div>

            <div className="info-list">
              <article>
                <strong>已知人物</strong>
                <span>命中阈值后会直接写入展示图人物标签。</span>
              </article>
              <article>
                <strong>未知人物</strong>
                <span>未命中样本库时统一标记为“未知人物”，可在图库详情中重新识别或改为正式人物。</span>
              </article>
              <article>
                <strong>普通标签</strong>
                <span>支持选已有，也支持上传时现场新增，供展示图库组合检索。</span>
              </article>
            </div>

            <div className="info-list upload-video-info">
              <article>
                <strong>视频状态</strong>
                <span>{videoUploadState}</span>
              </article>
              <article>
                <strong>字幕处理</strong>
                <span>{videoUploadGenerateSubtitles ? "上传完成后自动提交中文字幕生成。" : "可在视频上传弹窗中开启中文字幕生成。"}</span>
              </article>
            </div>
          </aside>
        </main>
    );
  };

  const renderVideoUploadModal = () => {
    const selectedVideoFileIds = new Set(videoFiles.map((file) => videoFileFingerprint(file)));
    const uploadableQueueCount = videoUploadQueue.filter((item) => item.status !== "completed" && selectedVideoFileIds.has(item.id)).length;
    const queueNeedsFileCount = videoUploadQueue.filter((item) => item.status === "needs_file").length;
    const queueFailedCount = videoUploadQueue.filter((item) => item.status === "failed").length;
    const canStartVideoUpload = uploadableQueueCount > 0 && !(videoFiles.length === 1 && !videoTitle.trim());
    const videoModalProgress =
      videoUploadQueue.length > 0
        ? Math.round(videoUploadQueue.reduce((sum, item) => sum + item.progress, 0) / videoUploadQueue.length)
        : videoUploadProgress;

    return (
    <div className="modal-backdrop">
      <aside className="panel video-upload-panel bili-modal-content">
        <div className="section-head">
          <div>
            <p className="eyebrow">上传视频</p>
            <h2>分片入库</h2>
          </div>
          <button className="close-modal" onClick={() => setIsVideoUploadModalOpen(false)}>关闭</button>
        </div>

        <label className="upload-box video-upload-box">
          <input type="file" accept={supportedVideoAccept} multiple onChange={(event) => handlePickVideoFile(event.target.files)} />
          <strong>{videoFiles.length === 1 ? videoFiles[0].name : videoFiles.length > 1 ? `已选 ${videoFiles.length} 个视频` : `选择视频（${supportedVideoFormatLabel}，可多选）`}</strong>
          <span>{videoFiles.length >= 1 ? videoFiles.map((f) => formatBytes(f.size)).join("、") : "支持长视频分片上传，上传后会自动转为网页可播放格式。"}</span>
        </label>

        {videoUploadQueue.length > 0 && (
          <div className="editor-block">
            <label>
              上传队列（{videoUploadQueue.length}）
              {queueNeedsFileCount > 0 && ` · ${queueNeedsFileCount} 个需重选文件`}
              {queueFailedCount > 0 && ` · ${queueFailedCount} 个失败`}
            </label>
            <div className="video-upload-queue">
              {videoUploadQueue.map((item) => (
                <article key={item.id} className="video-upload-queue-item">
                  <div className="pending-card-copy">
                    <strong>{item.title || item.filename}</strong>
                    <span>{item.filename} · {formatBytes(item.size)}</span>
                    <span>{videoQueueStatusLabel(item.status)} · {item.progress}%</span>
                    <div className="meter">
                      <span style={{ width: `${item.progress}%` }} />
                    </div>
                    {item.error && <small>{item.error}</small>}
                  </div>
                </article>
              ))}
            </div>
          </div>
        )}

        <div className="stack-editor">
          <input value={videoTitle} onChange={(event) => setVideoTitle(event.target.value)} placeholder="单个视频时可自定义标题" disabled={videoFiles.length > 1} />
          <textarea
            className="rich-text-editor compact"
            value={videoDescription}
            onChange={(event) => setVideoDescription(event.target.value)}
            placeholder="视频简介（批量上传时所有文件共用此简介）"
          />
        </div>

        <div className="editor-block">
          <label>上传时绑定类别</label>
          <div className="chip-cloud compact">
            {videoCategoryTags.map((tag) => (
              <button
                key={tag.id}
                className={videoUploadCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                onClick={() => handleToggleVideoUploadCategory(tag.id)}
              >
                #{tag.name}
              </button>
            ))}
          </div>
          <input
            value={videoUploadNewCategories}
            onChange={(event) => setVideoUploadNewCategories(event.target.value)}
            placeholder="新类别标签，逗号分隔"
          />
        </div>

        <div className="editor-block">
          <label>上传时绑定人物</label>
          <div className="video-person-cloud compact">
            {videoPeople.map((person) => (
              <button
                key={person.id}
                className={videoUploadPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                onClick={() => handleToggleVideoUploadPerson(person.id)}
              >
                {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                <b>{person.name}</b>
              </button>
            ))}
          </div>
        </div>

        <label className="toggle-row subtitle-upload-toggle">
          <input
            type="checkbox"
            checked={videoUploadGenerateSubtitles}
            onChange={(event) => setVideoUploadGenerateSubtitles(event.target.checked)}
          />
          <span>自动生成中文字幕</span>
        </label>

        {error && <div className="error-banner modal-inline-error">{error}</div>}

        <div className="video-progress">
          <strong>{videoModalProgress}%</strong>
          <div className="meter"><span style={{ width: `${videoModalProgress}%` }} /></div>
          {videoUploadTotalCount > 0 && (
            <small>文件 {Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / {videoUploadTotalCount}</small>
          )}
          {videoUploadSession && <small>{videoUploadSession.uploaded_parts.length} / {videoUploadSession.total_parts} 分片</small>}
        </div>

        <div className="micro-row wrap">
          <button disabled={videoUploadBusy || !canStartVideoUpload} onClick={() => void handleConfirmVideoUpload()}>
            {videoUploadTotalCount > 0
              ? `上传中 (${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)}/${videoUploadTotalCount})`
              : videoUploadQueue.some((item) => item.status === "needs_file" || item.status === "failed")
                ? "继续上传"
                : "开始上传"}
          </button>
          <button className="ghost-button" disabled={videoUploadBusy} onClick={() => void handleCancelVideoUpload()}>
            清理续传会话
          </button>
        </div>
      </aside>
    </div>
  );
  };

  const renderVideosPage = () => {
    return (
        <main className="bili-videos-page">
          <div className="bili-top-bar">
            <div className="bili-search-box">
              <input
                className="search-input"
                value={videoSearch}
                onChange={(event) => setVideoSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
                  }
                }}
                placeholder="搜索视频名、简介或文件名"
              />
              <button disabled={busy} onClick={() => void refreshVideos(0)}>
                搜索
              </button>
            </div>
            <div className="micro-row wrap compact-actions">
              <button className="compact-button" onClick={() => setIsCategoryManageModalOpen(true)}>管理分区</button>
              <button className="compact-button" onClick={() => setIsVideoPersonManageModalOpen(true)}>管理UP主</button>
            </div>
          </div>

          <section className="subtitle-service-panel">
            <div className="subtitle-service-head">
              <div>
                <p className="eyebrow">中文字幕</p>
                <h2>本地翻译服务</h2>
              </div>
              <div className="subtitle-service-actions">
                <span className={`subtitle-service-badge subtitle-service-badge-${subtitleServiceStatus?.status ?? "unknown"}`}>
                  {subtitleServiceStatus ? subtitleServiceStatusLabel(subtitleServiceStatus.status) : "检测中"}
                </span>
                <button disabled={subtitleServiceBusy} onClick={() => void handleStartSubtitleService()}>
                  启动服务
                </button>
                <button disabled={subtitleServiceBusy} onClick={() => void handleStopSubtitleService()}>
                  关闭服务
                </button>
                <button disabled={subtitleServiceBusy} onClick={() => void handleToggleSubtitleLogs()}>
                  {subtitleLogsOpen ? "收起日志" : "查看日志"}
                </button>
              </div>
            </div>

            <div className="subtitle-service-meta">
              <span>端点：{subtitleServiceStatus?.endpoint ?? "未检测"}</span>
              <span>PID：{subtitleServiceStatus?.pid ?? "无"}</span>
              <span>模型：{subtitleServiceStatus?.model ?? "Hy-MT2"}</span>
              <span>{subtitleServiceStatus?.managed ? "由 PictureShow 启动" : "外部或未启动"}</span>
            </div>

            <div className="subtitle-service-meta subtitle-service-asr-meta">
              <span>ASR：{subtitleServiceStatus?.asr ? subtitleAsrStatusLabel(subtitleServiceStatus.asr.status) : "检测中"}</span>
              <span>设备：{subtitleServiceStatus?.asr ? `${subtitleServiceStatus.asr.device}/${subtitleServiceStatus.asr.compute_type}` : "未检测"}</span>
              <span>模型：faster-whisper</span>
              {subtitleServiceStatus?.asr?.last_duration_seconds != null && (
                <span>上次耗时：{subtitleServiceStatus.asr.last_duration_seconds.toFixed(1)} 秒</span>
              )}
              {subtitleServiceStatus?.asr?.last_segment_count != null && (
                <span>上次片段：{subtitleServiceStatus.asr.last_segment_count}</span>
              )}
            </div>

            {(subtitleServiceNotice || subtitleServiceStatus?.message) && (
              <div
                className={
                  subtitleServiceNotice?.includes("失败") || subtitleServiceStatus?.status === "unhealthy"
                    ? "subtitle-service-message subtitle-service-message-error"
                    : "subtitle-service-message"
                }
              >
                {subtitleServiceNotice || subtitleServiceStatus?.message}
              </div>
            )}

            {subtitleServiceStatus?.asr?.message && (
              <div
                className={
                  subtitleServiceStatus.asr.status === "error"
                    ? "subtitle-service-message subtitle-service-message-error"
                    : "subtitle-service-message"
                }
              >
                语音识别：{subtitleServiceStatus.asr.message}
                {subtitleServiceStatus.asr.last_error ? `：${subtitleServiceStatus.asr.last_error}` : ""}
              </div>
            )}

            {visibleSubtitleJobs.length > 0 ? (
              <div className="subtitle-job-list">
                {visibleSubtitleJobs.map((job) => {
                  const progress = Math.round(Math.min(Math.max(job.task?.progress ?? 0, 0), 1) * 100);
                  const isActive = ["pending", "running"].includes(job.track.status);
                  return (
                    <div className={`subtitle-job-row subtitle-job-row-${job.track.status}`} key={`${job.video_id}-${job.track.id}`}>
                      <div className="subtitle-job-main">
                        <strong>{job.video_title}</strong>
                        <span>{subtitleTrackStatusLabel(job.track.status)} · {job.task?.message ?? job.video_filename}</span>
                        {job.track.error_message && <small>{job.track.error_message}</small>}
                      </div>
                      <div className="subtitle-job-progress">
                        <progress value={progress} max={100}></progress>
                        <span>{progress}%</span>
                      </div>
                      <button
                        className="ghost-button compact"
                        disabled={subtitleServiceBusy || !isActive}
                        onClick={() => void handleCancelSubtitleJob(job)}
                      >
                        取消
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : !subtitleJobsLoaded ? (
              <p className="subtitle-service-empty">正在读取字幕任务...</p>
            ) : (
              <p className="subtitle-service-empty">当前没有字幕生成任务。</p>
            )}

            {subtitleLogsOpen && (
              <div className="subtitle-log-panel">
                <div className="subtitle-log-path">{subtitleServiceLogs?.log_path ?? "未配置日志文件"}</div>
                <pre>{subtitleServiceLogs?.content || "暂无日志"}</pre>
              </div>
            )}
          </section>

          <div className="bili-filters-bar">
            <div className="bili-filter-row">
              <span className="bili-filter-label">分区</span>
              <div className="bili-chip-cloud">
                <button
                  className={selectedVideoCategoryIds.length === 0 ? "soft-chip active" : "soft-chip"}
                  onClick={() => {
                    setSelectedVideoCategoryIds([]);
                    void refreshVideos(0, [], selectedVideoPersonIds, videoSearch);
                  }}
                >
                  全部
                </button>
                {filteredVideoCategoryTags.map((tag) => (
                  <button
                    key={tag.id}
                    className={selectedVideoCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                    onClick={() => handleToggleVideoFilterCategory(tag.id)}
                  >
                    {tag.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="bili-filter-row">
              <span className="bili-filter-label">UP主</span>
              <div className="bili-chip-cloud">
                <button
                  className={selectedVideoPersonIds.length === 0 ? "video-person-chip active" : "video-person-chip"}
                  onClick={() => {
                    setSelectedVideoPersonIds([]);
                    void refreshVideos(0, selectedVideoCategoryIds, [], videoSearch);
                  }}
                >
                  <b>全部</b>
                </button>
                {filteredVideoPeople.map((person) => (
                  <button
                    key={person.id}
                    className={selectedVideoPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                    onClick={() => handleToggleVideoFilterPerson(person.id)}
                  >
                    {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                    <b>{person.name}</b>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="bili-video-grid">
            {videoItems.map((video) => (
              <article
                key={video.id}
                className="bili-video-card"
                onClick={() => window.open("#video-play/" + video.id, "_blank")}
              >
                <div className="bili-video-cover">
                  {video.cover_url ? (
                    <img src={video.cover_url} alt={video.title} loading="lazy" />
                  ) : (
                    <span className="placeholder">{getVideoFormatLabel(video.filename)}</span>
                  )}
                  <span className={`bili-video-status status-${video.status}`}>{videoStatusLabel(video.status)}</span>
                  <span className="bili-video-duration">
                    {video.duration_seconds ? formatDurationSeconds(video.duration_seconds) : formatBytes(video.size_bytes)}
                  </span>
                </div>
                <div className="bili-video-info">
                  <h3 className="bili-video-title" title={video.title}>{video.title}</h3>
                  <div className="bili-up-list">
                    {video.people.map((person) => (
                      <div className="bili-up-item" key={person.id} title={person.name}>
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <span>{person.name}</span>
                      </div>
                    ))}
                    {video.people.length === 0 && <span className="muted small-muted">无UP主</span>}
                  </div>
                  <div className="bili-video-meta">
                    <span>{formatDate(video.created_at)}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>

          {videoTotal > 0 && (
            <div className="pagination-row pagination-row-bottom">
              <button disabled={videoOffset === 0 || busy} onClick={() => void refreshVideos(Math.max(0, videoOffset - videoPageSize))}>
                上一页
              </button>
              <span>
                {videoOffset + 1} - {Math.min(videoOffset + videoPageSize, videoTotal)} / 共 {videoTotal}
              </span>
              <button disabled={videoOffset + videoPageSize >= videoTotal || busy} onClick={() => void refreshVideos(videoOffset + videoPageSize)}>
                下一页
              </button>
            </div>
          )}

        </main>
    );
  };

  const navItems = [
    { key: "home", label: "首页", Icon: HomeIcon },
    { key: "gallery", label: "展示图库", Icon: GalleryHorizontalEnd },
    { key: "people", label: "人物样本", Icon: UsersRound },
    { key: "upload", label: "上传", Icon: UploadCloud },
    { key: "videos", label: "视频库", Icon: Clapperboard },
    { key: "statistics", label: "统计", Icon: BarChart3 }
  ] as const;

  return (
    <div className="app-shell">
      <div className="sunwash sunwash-a" />
      <div className="sunwash sunwash-b" />

      <header className="topbar">
        <div>
          <p className="eyebrow">Local Face Archive</p>
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
              onClick={() => {
                setPageState(key as PageKey);
                setRoute(key as PageKey);
              }}
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

      {page === "videos" && renderVideosPage()}

      {page === "video-play" && (
        <main className="video-play-page">
          <section className="video-play-main">
            {selectedVideo ? (
              <div className="panel video-player-panel">
                {(() => {
                  const subtitleTracks = selectedVideo.subtitle_tracks
                    .filter((track) => track.status === "ready" && track.vtt_url)
                    .map((track) => ({
                      src: track.vtt_url as string,
                      label: track.label,
                      srclang: track.language
                    }));
                  return (
                    <BiliVideoPlayer
                      src={videoPlayerUrl}
                      poster={selectedVideo.cover_url ?? undefined}
                      subtitles={subtitleTracks}
                    />
                  );
                })()}
              </div>
            ) : (
              <div className="panel video-loading-panel">
                <p>加载中...</p>
              </div>
            )}
          </section>

          <aside className="video-play-sidebar panel">
            {selectedVideo && (
              <div className="detail-copy">
                <div className="video-play-info">
                  <h1>{selectedVideo.title}</h1>
                  <div className="micro-row wrap compact-actions video-detail-actions">
                    <button className="compact-button" onClick={() => openVideoEditModal()}>
                      <Edit3 size={14} aria-hidden="true" />
                      编辑信息
                    </button>
                  </div>
                  
                  <div className="bili-up-list">
                    {selectedVideo.people.map((person) => (
                      <div className="bili-up-item" key={person.id}>
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <span>{person.name}</span>
                      </div>
                    ))}
                  </div>

                  <div className="micro-row wrap video-tag-row">
                    {selectedVideo.category_tags.map((tag) => (
                      <span key={tag.id} className="pill muted">#{tag.name}</span>
                    ))}
                  </div>

                  <div className="video-meta-grid">
                    <span>{formatDate(selectedVideo.created_at)}</span>
                    <span>{videoStatusLabel(selectedVideo.status)}</span>
                    <span>{formatDurationSeconds(selectedVideo.duration_seconds)}</span>
                    <span>{formatResolution(selectedVideo.width, selectedVideo.height)}</span>
                  </div>

                  <div className="description-box">
                    {selectedVideo.description || "无简介"}
                  </div>

                  <div className="subtitle-panel">
                    <div className="section-head compact-head">
                      <div>
                        <p className="eyebrow">字幕</p>
                        <h2>中文字幕</h2>
                      </div>
                    </div>
                    {selectedVideo.subtitle_tracks.length > 0 ? (
                      selectedVideo.subtitle_tracks.map((track) => (
                        <div className={`subtitle-status subtitle-status-${track.status}`} key={track.id}>
                          <strong>{track.label}</strong>
                          <span>{subtitleTrackStatusLabel(track.status)}</span>
                          {track.error_message && <small>{track.error_message}</small>}
                          {track.status === "ready" && track.srt_url && (
                            <a className="compact-button subtitle-download-link" href={track.srt_url}>
                              <Download size={14} aria-hidden="true" />
                              下载 SRT
                            </a>
                          )}
                        </div>
                      ))
                    ) : (
                      <p className="subtitle-empty">当前视频还没有字幕。</p>
                    )}
                    <button
                      className="ghost-button"
                      disabled={busy || selectedVideo.subtitle_tracks.some((track) => ["pending", "running"].includes(track.status))}
                      onClick={() => void handleGenerateSelectedVideoSubtitles()}
                    >
                      生成中文字幕
                    </button>
                  </div>
                </div>

                <div className="section-head compact-head video-management-head">
                  <div>
                    <p className="eyebrow">视频管理</p>
                    <h2>封面与文件</h2>
                  </div>
                </div>

                <div className="video-cover-manager">
                  {selectedVideo.cover_url ? (
                    <img src={selectedVideo.cover_url} alt="视频封面" />
                  ) : (
                    <div className="video-cover-empty">暂无封面</div>
                  )}
                  <label className="cover-upload-button">
                    <input
                      type="file"
                      accept="image/*"
                      disabled={busy}
                      onChange={(event) => {
                        void handleReplaceVideoCover(event.target.files);
                        event.currentTarget.value = "";
                      }}
                    />
                    替换封面
                  </label>
                </div>
                
                <p><strong>文件:</strong> {selectedVideo.filename}</p>
                <p><strong>原始格式:</strong> {formatCodecs(selectedVideo.original_video_codec, selectedVideo.original_audio_codec, selectedVideo.status)}</p>
                <p><strong>播放格式:</strong> {formatCodecs(selectedVideo.video_codec, selectedVideo.audio_codec, selectedVideo.status)}</p>
                <p><strong>体积:</strong> {formatBytes(selectedVideo.size_bytes)}</p>
                <p>
                  {selectedVideo.faststart_applied ? "· 已完成 faststart 优化" : "· 未优化"}
                </p>
                <p>
                  {selectedVideo.seek_optimized
                    ? `· 已完成拖动优化${selectedVideo.seek_keyframe_interval_seconds ? `（关键帧约 ${selectedVideo.seek_keyframe_interval_seconds.toFixed(2)} 秒）` : ""}`
                    : "· 未完成拖动优化"}
                </p>
                {selectedVideo.processing_error && <p className="inline-error">优化错误：{selectedVideo.processing_error}</p>}

                <div className="video-playback-tools">
                  <button
                    className="ghost-button"
                    disabled={videoPlaybackDiagnosticsLoading || selectedVideo.status === "processing"}
                    onClick={() => void handleLoadVideoPlaybackDiagnostics()}
                  >
                    {videoPlaybackDiagnosticsLoading ? "诊断中..." : "读取播放诊断"}
                  </button>
                  <button
                    className="compact-button"
                    disabled={busy || selectedVideo.status === "processing"}
                    onClick={() => void handleOptimizeSelectedVideoPlayback()}
                  >
                    优化拖动流畅度
                  </button>
                </div>
                {videoPlaybackDiagnostics && (
                  <div className="video-playback-diagnostics">
                    <p><strong>播放链路:</strong> {videoPlaybackDiagnostics.expected_mode}</p>
                    <p><strong>MinIO:</strong> {videoPlaybackDiagnostics.presigned_url_host || videoPlaybackDiagnostics.minio_public_endpoint}</p>
                    <p><strong>对象:</strong> {formatBytes(videoPlaybackDiagnostics.object?.object_size_bytes ?? videoPlaybackDiagnostics.size_bytes)}</p>
                    <p><strong>码率:</strong> {videoPlaybackDiagnostics.object?.bitrate ? `${Math.round(videoPlaybackDiagnostics.object.bitrate / 1000)} kbps` : "未知"}</p>
                    <p><strong>Faststart:</strong> {videoPlaybackDiagnostics.object?.faststart === null || videoPlaybackDiagnostics.object?.faststart === undefined ? "未知" : videoPlaybackDiagnostics.object.faststart ? "是" : "否"}</p>
                    <p>
                      <strong>估算关键帧间隔:</strong>{" "}
                      {videoPlaybackDiagnostics.object?.estimated_keyframe_interval_seconds
                        ? `${videoPlaybackDiagnostics.object.estimated_keyframe_interval_seconds.toFixed(2)} 秒`
                        : "未知"}
                    </p>
                    {videoPlaybackDiagnostics.object_probe_error && <p className="inline-error">{videoPlaybackDiagnostics.object_probe_error}</p>}
                  </div>
                )}
                
                <button 
                  className="danger-button full-width-action" 
                  disabled={busy} 
                  onClick={() => {
                    if (confirm("确定要删除此视频吗？")) {
                      void handleDeleteCurrentVideo().then(() => {
                        window.close(); // Optional: close tab on delete
                      });
                    }
                  }}
                >
                  删除视频
                </button>
              </div>
            )}
          </aside>
        </main>
      )}

      {page === "home" && <Home />}

      {page === "gallery" && GalleryPageComponent()}

      {page === "people" && PeoplePageComponent()}

      {page === "upload" && renderUploadPage()}

      {(page === "gallery" || page === "videos") && (
        <button className="floating-top-button" type="button" onClick={scrollToPageTop} aria-label="回到顶部" title="回到顶部">
          <ArrowUp size={24} aria-hidden="true" />
        </button>
      )}

      {isVideoUploadModalOpen && renderVideoUploadModal()}

      {isVideoEditModalOpen && selectedVideo && (
        <div className="modal-backdrop" onClick={() => setIsVideoEditModalOpen(false)}>
          <div className="video-edit-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">编辑视频</p>
                <h2>修改信息</h2>
              </div>
              <button className="close-modal" onClick={() => setIsVideoEditModalOpen(false)}>关闭</button>
            </div>
            <div className="stack-editor">
              <input value={editVideoTitle} onChange={(event) => setEditVideoTitle(event.target.value)} placeholder="视频标题" />
              <textarea
                className="rich-text-editor compact"
                value={editVideoDescription}
                onChange={(event) => setEditVideoDescription(event.target.value)}
                placeholder="视频简介"
              />
            </div>
            <div className="editor-block">
              <label>分区</label>
              <div className="chip-cloud compact">
                {videoCategoryTags.map((tag) => (
                  <button
                    key={tag.id}
                    className={editVideoCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                    onClick={() => {
                      setEditVideoCategoryIds((current) =>
                        current.includes(tag.id) ? current.filter((id) => id !== tag.id) : [...current, tag.id]
                      );
                    }}
                  >
                    #{tag.name}
                  </button>
                ))}
              </div>
            </div>
            <div className="editor-block">
              <label>UP主</label>
              <div className="video-person-cloud compact">
                {videoPeople.map((person) => (
                  <button
                    key={person.id}
                    className={editVideoPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                    onClick={() => {
                      setEditVideoPersonIds((current) =>
                        current.includes(person.id) ? current.filter((id) => id !== person.id) : [...current, person.id]
                      );
                    }}
                  >
                    {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                    <b>{person.name}</b>
                  </button>
                ))}
              </div>
            </div>
            <div className="modal-actions">
              <button className="ghost-button" onClick={() => setIsVideoEditModalOpen(false)}>取消</button>
              <button disabled={busy} onClick={() => void handleSaveVideoEdit()}>保存</button>
            </div>
          </div>
        </div>
      )}

      {isCategoryManageModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsCategoryManageModalOpen(false)}>
          <div className="manage-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">管理分区</p>
                <h2>视频分类</h2>
              </div>
              <button className="close-modal" onClick={() => setIsCategoryManageModalOpen(false)}>关闭</button>
            </div>
            <div className="inline-editor flush-editor">
              <input value={newManageCategoryName} onChange={(event) => setNewManageCategoryName(event.target.value)} placeholder="新分区名称" />
              <button disabled={busy || !newManageCategoryName.trim()} onClick={() => void handleCreateManageCategory()}>创建</button>
            </div>
            <div className="manage-list">
              {videoCategoryTags.map((tag) => (
                <div key={tag.id} className="manage-item">
                  {editingCategoryId === tag.id ? (
                    <div className="inline-editor flush-editor flex-editor">
                      <input value={editingCategoryName} onChange={(event) => setEditingCategoryName(event.target.value)} placeholder="分区名称" />
                      <button disabled={busy || !editingCategoryName.trim()} onClick={() => void handleUpdateManageCategory(tag.id)}>保存</button>
                      <button className="ghost-button" onClick={() => { setEditingCategoryId(null); setEditingCategoryName(""); }}>取消</button>
                    </div>
                  ) : (
                    <>
                      <span>#{tag.name}</span>
                      <div className="micro-row wrap mini-actions">
                        <button className="mini-button" onClick={() => { setEditingCategoryId(tag.id); setEditingCategoryName(tag.name); }}>编辑</button>
                        <button className="mini-button danger-text" onClick={() => void handleDeleteManageCategory(tag.id)}>删除</button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {videoCategoryTags.length === 0 && <p className="tip">暂无分区</p>}
            </div>
          </div>
        </div>
      )}

      {isVideoPersonManageModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsVideoPersonManageModalOpen(false)}>
          <div className="manage-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">管理UP主</p>
                <h2>视频人物</h2>
              </div>
              <button className="close-modal" onClick={() => setIsVideoPersonManageModalOpen(false)}>关闭</button>
            </div>
            <div className="stack-editor modal-stack">
              <input value={newManagePersonName} onChange={(event) => setNewManagePersonName(event.target.value)} placeholder="UP主名称" />
              <input value={newManagePersonNote} onChange={(event) => setNewManagePersonNote(event.target.value)} placeholder="备注（可选）" />
              <div className="inline-editor flush-editor">
                <input type="file" accept="image/*" onChange={(event) => setNewManagePersonAvatar(event.target.files?.[0] ?? null)} />
                <button disabled={busy || !newManagePersonName.trim()} onClick={() => void handleCreateManagePerson()}>创建</button>
              </div>
            </div>
            <div className="manage-list">
              {videoPeople.map((person) => (
                <div key={person.id} className="manage-item">
                  {editingPersonId === person.id ? (
                    <div className="stack-editor flex-editor">
                      <input value={editingPersonName} onChange={(event) => setEditingPersonName(event.target.value)} placeholder="UP主名称" />
                      <input value={editingPersonNote} onChange={(event) => setEditingPersonNote(event.target.value)} placeholder="备注（可选）" />
                      <div className="inline-editor flush-editor">
                        <input type="file" accept="image/*" onChange={(event) => setEditingPersonAvatar(event.target.files?.[0] ?? null)} />
                        <button disabled={busy || !editingPersonName.trim()} onClick={() => void handleUpdateManagePerson(person.id)}>保存</button>
                        <button className="ghost-button" onClick={() => { setEditingPersonId(null); setEditingPersonName(""); setEditingPersonNote(""); setEditingPersonAvatar(null); }}>取消</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="manage-person-info">
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <div>
                          <strong>{person.name}</strong>
                          {person.note && <small>{person.note}</small>}
                        </div>
                      </div>
                      <div className="micro-row wrap mini-actions">
                        <button className="mini-button" onClick={() => { setEditingPersonId(person.id); setEditingPersonName(person.name); setEditingPersonNote(person.note || ""); setEditingPersonAvatar(null); }}>编辑</button>
                        <button className="mini-button danger-text" onClick={() => void handleDeleteManagePerson(person.id)}>删除</button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {videoPeople.length === 0 && <p className="tip">暂无UP主</p>}
            </div>
          </div>
        </div>
      )}

      {galleryExportModalOpen && (
        <div className="modal-backdrop" onClick={() => setGalleryExportModalOpen(false)}>
          <div className="export-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">导出展示图</p>
                <h2>选择导出范围</h2>
              </div>
              <button className="lightbox-close" onClick={() => setGalleryExportModalOpen(false)}>
                关闭
              </button>
            </div>

            <div className="export-choice-row">
              <button
                className={galleryExportScope === "filtered" ? "soft-chip active" : "soft-chip"}
                onClick={() => setGalleryExportScope("filtered")}
              >
                自定义范围
              </button>
              <button
                className={galleryExportScope === "all" ? "soft-chip active" : "soft-chip"}
                onClick={() => setGalleryExportScope("all")}
              >
                全部展示图
              </button>
              <span>
                {galleryExportScope === "all"
                  ? "将导出图库中的全部展示图"
                  : `按 ${galleryExportPersonIds.length} 个人物、${galleryExportTagIds.length} 个普通标签导出`}
              </span>
            </div>

            <div className={galleryExportScope === "all" ? "export-filter-grid disabled" : "export-filter-grid"}>
              <section className="export-filter-block">
                <div className="filter-section-head">
                  <strong>人物标签</strong>
                  <span>{galleryExportPersonIds.length} 已选</span>
                </div>
                <div className="export-chip-cloud">
                  {sortByPinyinName(persons).map((person) => (
                    <button
                      key={`export-person-${person.id}`}
                      className={galleryExportPersonIds.includes(person.id) ? "soft-chip active" : "soft-chip"}
                      disabled={galleryExportScope === "all"}
                      onClick={() => handleToggleGalleryExportPerson(person.id)}
                    >
                      {person.display_name}
                    </button>
                  ))}
                  {persons.length === 0 && <span className="filter-empty">没有人物标签</span>}
                </div>
              </section>

              <section className="export-filter-block">
                <div className="filter-section-head">
                  <strong>普通标签</strong>
                  <span>{galleryExportTagIds.length} 已选</span>
                </div>
                <div className="export-chip-cloud compact">
                  {normalTags.map((tag) => (
                    <button
                      key={`export-tag-${tag.id}`}
                      className={galleryExportTagIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                      disabled={galleryExportScope === "all"}
                      onClick={() => handleToggleGalleryExportTag(tag.id)}
                    >
                      #{tag.name}
                    </button>
                  ))}
                  {normalTags.length === 0 && <span className="filter-empty">没有普通标签</span>}
                </div>
              </section>
            </div>

            <div className="modal-actions">
              <button
                onClick={() => {
                  setGalleryExportScope("filtered");
                  setGalleryExportPersonIds([]);
                  setGalleryExportTagIds([]);
                }}
              >
                清空筛选
              </button>
              <button disabled={busy} onClick={handleExportGalleryPhotos}>
                导出 ZIP
              </button>
            </div>
          </div>
        </div>
      )}

      {lightboxPhoto && (
        <div className="lightbox-backdrop" onClick={() => closeGalleryLightbox()}>
          <div className={lightboxPhoto.is_rich_text ? "lightbox-shell rich-lightbox" : "lightbox-shell"} onClick={(event) => event.stopPropagation()}>
            <button className="lightbox-close" onClick={() => closeGalleryLightbox()}>
              关闭
            </button>
            <button className="lightbox-arrow left" disabled={!canGoPrev || busy} onClick={() => void goPrevLightbox()}>
              {isFirstOfPage && hasPrevPage ? (
                <>
                  ‹ <span>上一页</span>
                </>
              ) : (
                "‹"
              )}
            </button>
            {lightboxPhoto.is_rich_text ? (
              <div className="rich-lightbox-layout">
                <div className="rich-lightbox-image-wrap">
                  <img className="lightbox-image" src={lightboxPhoto.original_url} alt="图文大图预览" />
                </div>
                <aside className="rich-lightbox-copy">
                  <h3>图文内容</h3>
                  {lightboxEditMode ? (
                    <textarea
                      className="rich-text-editor lightbox-editor"
                      value={lightboxRichTextDraft}
                      onChange={(event) => setLightboxRichTextDraft(event.target.value)}
                      placeholder="可在此编辑图文文本"
                    />
                  ) : (
                    <p>{lightboxPhoto.rich_text || "未识别到文本，点击编辑按钮手动补录。"}</p>
                  )}
                  <div className="micro-row">
                    <span>OCR状态：{lightboxPhoto.ocr_status ?? "unknown"}</span>
                    {lightboxEditMode ? (
                      <button
                        disabled={busy}
                        onClick={() => {
                          void handleSaveLightboxRichText();
                          setLightboxEditMode(false);
                        }}
                      >
                        保存图文文本
                      </button>
                    ) : (
                      <button
                        disabled={busy}
                        onClick={() => {
                          setLightboxRichTextDraft(lightboxPhoto.rich_text || "");
                          setLightboxEditMode(true);
                        }}
                      >
                        编辑图文文本
                      </button>
                    )}
                  </div>
                  <div className="micro-row wrap">
                    {lightboxPhoto.persons.map((person) => (
                      <small key={`lb-p-${lightboxPhoto.id}-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                        {person.person_name}
                      </small>
                    ))}
                  </div>
                  <div className="micro-row wrap">
                    {sortByPinyinName(lightboxPhoto.tags).map((tag) => (
                      <small key={`lb-t-${lightboxPhoto.id}-${tag.id}`} className="pill muted">
                        #{tag.name}
                      </small>
                    ))}
                  </div>
                </aside>
              </div>
            ) : (
              <img className="lightbox-image" src={lightboxPhoto.original_url} alt="大图预览" />
            )}
            <button className="lightbox-arrow right" disabled={!canGoNext || busy} onClick={() => void goNextLightbox()}>
              {isLastOfPage && hasNextPage ? (
                <>
                  <span>下一页</span> ›
                </>
              ) : (
                "›"
              )}
            </button>
          </div>
          <aside className="lightbox-meta-rail" onClick={(event) => event.stopPropagation()}>
            <div className="lightbox-meta-head">
              <span>#{lightboxPhoto.id}</span>
              <strong>{lightboxIndex >= 0 ? `${galleryOffset + lightboxIndex + 1} / ${galleryTotal}` : "图片信息"}</strong>
            </div>
            <div className="lightbox-meta-section">
              <span>人物标签</span>
              <div className="lightbox-meta-chips">
                {lightboxPhoto.persons.length > 0 ? (
                  lightboxPhoto.persons.map((person) => (
                    <small key={`rail-p-${lightboxPhoto.id}-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                      {person.person_name}
                    </small>
                  ))
                ) : (
                  <small className="lightbox-meta-empty">无人物标签</small>
                )}
              </div>
            </div>
            <div className="lightbox-meta-section">
              <span>普通标签</span>
              <div className="lightbox-meta-chips">
                {lightboxPhoto.tags.length > 0 ? (
                  sortByPinyinName(lightboxPhoto.tags).map((tag) => (
                    <small key={`rail-t-${lightboxPhoto.id}-${tag.id}`} className="pill muted">
                      #{tag.name}
                    </small>
                  ))
                ) : (
                  <small className="lightbox-meta-empty">无普通标签</small>
                )}
              </div>
            </div>
            <button className="lightbox-detail-button" disabled={busy} onClick={() => void openLightboxPhotoDetail()}>
              <Info size={16} aria-hidden="true" />
              查看详情
            </button>
          </aside>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}
    </div>
  );
}

type AuthScreenProps = {
  bootstrapRequired: boolean;
  busy: boolean;
  error: string | null;
  onBootstrap: (payload: { username: string; password: string; display_name?: string | null; workspace_name?: string | null }) => Promise<void>;
  onLogin: (username: string, password: string) => Promise<void>;
  onRegister: (payload: { username: string; password: string; display_name?: string | null }) => Promise<void>;
};

function AuthScreen({ bootstrapRequired, busy, error, onBootstrap, onLogin, onRegister }: AuthScreenProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("我的内容空间");
  const [password, setPassword] = useState("");
  const isRegisterMode = !bootstrapRequired && mode === "register";
  const passwordMinLength = bootstrapRequired || isRegisterMode ? 8 : 1;

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <p className="eyebrow">PictureShow</p>
        <h1>{bootstrapRequired ? "初始化管理员" : isRegisterMode ? "注册账号" : "登录"}</h1>
        <p className="lead">
          {bootstrapRequired
            ? "首次使用需要创建管理员和默认内容空间。"
            : isRegisterMode
              ? "新账号会自动创建只能自己使用的私人内容空间。"
              : "登录后只会看到当前账号所属内容空间的数据。"}
        </p>
        {!bootstrapRequired && (
          <div className="auth-mode-tabs" role="tablist" aria-label="认证方式">
            <button className={mode === "login" ? "active" : ""} type="button" onClick={() => setMode("login")}>
              登录
            </button>
            <button className={mode === "register" ? "active" : ""} type="button" onClick={() => setMode("register")}>
              注册
            </button>
          </div>
        )}
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (bootstrapRequired) {
              void onBootstrap({
                username,
                password,
                display_name: displayName || null,
                workspace_name: workspaceName || null
              });
              return;
            }
            if (isRegisterMode) {
              void onRegister({
                username,
                password,
                display_name: displayName || null
              });
              return;
            }
            void onLogin(username, password);
          }}
        >
          <label>
            账号
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
          </label>
          {(bootstrapRequired || isRegisterMode) && (
            <label>
              显示名称
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" />
            </label>
          )}
          {bootstrapRequired && (
            <label>
              内容空间
              <input value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} required />
            </label>
          )}
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={bootstrapRequired || isRegisterMode ? "new-password" : "current-password"}
              minLength={passwordMinLength}
              required
            />
          </label>
          <button className="primary" type="submit" disabled={busy || !username.trim() || password.length < passwordMinLength}>
            {busy ? "处理中..." : bootstrapRequired ? "创建并进入" : isRegisterMode ? "注册并进入" : "进入"}
          </button>
        </form>
        {error && <div className="error-banner">{error}</div>}
      </section>
    </main>
  );
}

export default function App() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(null);
  const [bootstrapRequired, setBootstrapRequired] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadAuth() {
      try {
        const session = await getCurrentSession();
        if (!cancelled) {
          setSelectedWorkspaceId(session.workspace.id);
          setAuthSession(session);
          setBootstrapRequired(false);
        }
      } catch {
        clearAuthToken();
        try {
          const status = await getBootstrapStatus();
          if (!cancelled) {
            setBootstrapRequired(status.required);
          }
        } catch (error) {
          if (!cancelled) {
            setAuthError(error instanceof Error ? error.message : "无法连接服务");
          }
        }
      } finally {
        if (!cancelled) {
          setAuthReady(true);
        }
      }
    }
    void loadAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSession = (session: AuthSession) => {
    setAuthToken(session.access_token);
    setSelectedWorkspaceId(session.workspace.id);
    setAuthSession(session);
    setBootstrapRequired(false);
    setAuthError(null);
  };

  const handleBootstrap = async (payload: { username: string; password: string; display_name?: string | null; workspace_name?: string | null }) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      handleSession(await bootstrapAdmin(payload));
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "初始化失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogin = async (username: string, password: string) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      handleSession(await login(username, password));
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "登录失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleRegister = async (payload: { username: string; password: string; display_name?: string | null }) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      handleSession(await registerAccount(payload));
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "注册失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogout = () => {
    clearAuthToken();
    clearSelectedWorkspaceId();
    setAuthSession(null);
    setAuthError(null);
  };

  const handleSessionChange = (session: AuthSession) => {
    setAuthToken(session.access_token);
    setSelectedWorkspaceId(session.workspace.id);
    setAuthSession(session);
  };

  if (!authReady) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <p className="eyebrow">PictureShow</p>
          <h1>加载中</h1>
        </section>
      </main>
    );
  }

  if (!authSession) {
    return (
      <AuthScreen
        bootstrapRequired={bootstrapRequired}
        busy={authBusy}
        error={authError}
        onBootstrap={handleBootstrap}
        onLogin={handleLogin}
        onRegister={handleRegister}
      />
    );
  }

  return <MainApp authSession={authSession} onLogout={handleLogout} onSessionChange={handleSessionChange} />;
}
