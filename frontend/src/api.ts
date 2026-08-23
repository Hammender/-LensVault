import type {
  Task,
  VideoItem,
  WorkspaceInvitation,
  WorkspaceMember,
  WorkspaceRead
} from "./types";
import {
  authFetch,
  clearAuthToken,
  clearSelectedWorkspaceId,
  getAuthToken,
  getSelectedWorkspaceId,
  jsonHeaders,
  parseResponse as parse,
  setAuthToken,
  setSelectedWorkspaceId,
  withWorkspaceContext
} from "./apiClient";

export {
  clearAuthToken,
  clearSelectedWorkspaceId,
  getAuthToken,
  getSelectedWorkspaceId,
  setAuthToken,
  setSelectedWorkspaceId
} from "./apiClient";

const fetch = authFetch;

export {
  bootstrapAdmin,
  getBootstrapStatus,
  getCurrentSession,
  login,
  logout,
  registerAccount
} from "./api/auth";

export {
  acceptWorkspaceInvitation,
  createWorkspace,
  createWorkspaceUser,
  declineWorkspaceInvitation,
  inviteWorkspaceMember,
  leaveWorkspace,
  listWorkspaceInvitations,
  listWorkspaceMembers,
  removeWorkspaceMember,
  updateWorkspaceMember
} from "./api/workspace";
export type { WorkspacePermissionsPayload } from "./api/workspace";
export type { GalleryExportOptions, GalleryExportScope, GalleryUploadMetadata } from "./api/gallery";

export {
  addVideoCategoryTag, addVideoPerson, cancelVideoSubtitles, cancelVideoUpload,
  completeVideoUpload, createVideoCategoryTag, createVideoPerson, createVideoUploadSession,
  deleteVideo, deleteVideoCategoryTag, deleteVideoPerson, generateVideoSubtitles, getVideo,
  getVideoPlaybackDiagnostics, getVideoUploadSession, listVideoCategoryTags, listVideoPeople,
  listVideos, optimizeVideoPlayback, removeVideoCategoryTag, removeVideoPerson, replaceVideoCover,
  updateVideo, updateVideoCategoryTag, updateVideoPerson, uploadVideoPart
} from "./api/videos";

export {
  addGalleryPhotoPerson, addGalleryPhotoTag, autoDeleteExactMirrorGroups, batchDeleteGalleryPhotos, createGallerySimilarityScan,
  deleteGalleryPhoto, deleteGalleryPhotoPerson, deleteGalleryPhotoTag, downloadGalleryExport, getGalleryExportUrl,
  getGalleryPhoto, getGallerySimilarityGroup, getGallerySimilarityScanOverview, getLatestGallerySimilarityScan,
  getTask, importGalleryExportZip, importGalleryPhotos, importGalleryRichPhotos, listGalleryPhotos,
  listGallerySimilarityGroups, previewNormalNearDuplicateAutoDelete, promoteGalleryPhotoPersonSample, reRecognizeGalleryPhoto,
  reRecognizeUnknownGalleryPhotos, undoGalleryPhotoPersonSample, updateGalleryPhotoRichText,
  updateGallerySimilarityGroup
} from "./api/gallery";

export {
  addPersonSamples,
  batchDeletePersons,
  bindPersonTag,
  createPerson,
  createTag,
  deletePerson,
  deletePersonSample,
  getPersonExportUrl,
  importPersonSamples,
  listPersonSamples,
  listPersonTags,
  listPersons,
  listTags,
  renamePerson,
  unbindPersonTag
} from "./api/people";

export {
  getSubtitleServiceLogs,
  getSubtitleServiceStatus,
  listSubtitleJobs,
  startSubtitleService,
  stopSubtitleService
} from "./api/subtitles";

export {
  getPersonStatistics,
  getTagStatistics,
  getUploadHistory,
  getUploadSummary
} from "./api/statistics";
