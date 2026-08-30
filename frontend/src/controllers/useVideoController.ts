import { useMemo, useRef, useState } from "react";

import { sortByPinyinName } from "../sort";
import type {
  VideoCategoryTag,
  VideoDetail,
  VideoItem,
  VideoPerson,
  VideoPlaybackDiagnostics,
  VideoUploadSession
} from "../types";
import { loadStoredVideoUploadQueue, type VideoUploadQueueItem } from "../videoUploadQueue";

export function useVideoController() {
  const [videoItems, setVideoItems] = useState<VideoItem[]>([]);
  const [videoTotal, setVideoTotal] = useState(0);
  const [videoOffset, setVideoOffset] = useState(0);
  const [videoCategoryTags, setVideoCategoryTags] = useState<VideoCategoryTag[]>([]);
  const [videoPeople, setVideoPeople] = useState<VideoPerson[]>([]);
  const [selectedVideoCategoryIds, setSelectedVideoCategoryIds] = useState<number[]>([]);
  const [selectedVideoPersonIds, setSelectedVideoPersonIds] = useState<number[]>([]);
  const [videoTypeFilter, setVideoTypeFilter] = useState<"all" | "short" | "long">("all");
  const [videoSearch, setVideoSearch] = useState("");
  const [activeLightboxIndex, setActiveLightboxIndex] = useState<number | null>(null);
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
  const [videoUploadTypeMode, setVideoUploadTypeMode] = useState<"auto" | "short" | "long">("auto");
  const [videoUploadNewCategories, setVideoUploadNewCategories] = useState("");
  const [videoUploadGenerateSubtitles, setVideoUploadGenerateSubtitles] = useState(false);
  const [videoUploadProgress, setVideoUploadProgress] = useState(0);
  const [videoUploadSession, setVideoUploadSession] = useState<VideoUploadSession | null>(null);
  const [videoUploadCurrentIndex, setVideoUploadCurrentIndex] = useState(0);
  const [videoUploadTotalCount, setVideoUploadTotalCount] = useState(0);
  const [videoUploadBusy, setVideoUploadBusy] = useState(false);
  const [videoListRefreshing, setVideoListRefreshing] = useState(false);
  const [videoUploadQueue, setVideoUploadQueue] = useState<VideoUploadQueueItem[]>(() => loadStoredVideoUploadQueue());
  const videoUploadQueueRef = useRef<VideoUploadQueueItem[]>(videoUploadQueue);
  const [newVideoCategoryName, setNewVideoCategoryName] = useState("");
  const [newVideoPersonName, setNewVideoPersonName] = useState("");
  const [newVideoPersonNote, setNewVideoPersonNote] = useState("");
  const [newVideoPersonAvatar, setNewVideoPersonAvatar] = useState<File | null>(null);
  const [isVideoEditModalOpen, setIsVideoEditModalOpen] = useState(false);
  const [editVideoTitle, setEditVideoTitle] = useState("");
  const [editVideoDescription, setEditVideoDescription] = useState("");
  const [editVideoType, setEditVideoType] = useState<"short" | "long">("short");
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

  return {
    videoItems, setVideoItems, videoTotal, setVideoTotal, videoOffset, setVideoOffset,
    videoCategoryTags, setVideoCategoryTags, videoPeople, setVideoPeople,
    selectedVideoCategoryIds, setSelectedVideoCategoryIds, selectedVideoPersonIds, setSelectedVideoPersonIds,
    videoTypeFilter, setVideoTypeFilter, activeLightboxIndex, setActiveLightboxIndex,
    videoSearch, setVideoSearch, selectedVideo, setSelectedVideo, selectedVideoCodecRepairVideoId,
    selectedVideoCodecRepairPolls, videoPlayerUrl, setVideoPlayerUrl, videoPlaybackDiagnostics,
    setVideoPlaybackDiagnostics, videoPlaybackDiagnosticsLoading, setVideoPlaybackDiagnosticsLoading,
    videoFiles, setVideoFiles, videoTitle, setVideoTitle, videoDescription, setVideoDescription,
    videoUploadCategoryIds, setVideoUploadCategoryIds, videoUploadPersonIds, setVideoUploadPersonIds,
    videoUploadTypeMode, setVideoUploadTypeMode,
    videoUploadNewCategories, setVideoUploadNewCategories, videoUploadGenerateSubtitles,
    setVideoUploadGenerateSubtitles, videoUploadProgress, setVideoUploadProgress, videoUploadSession,
    setVideoUploadSession, videoUploadCurrentIndex, setVideoUploadCurrentIndex, videoUploadTotalCount,
    setVideoUploadTotalCount, videoUploadBusy, setVideoUploadBusy, videoUploadQueue, setVideoUploadQueue,
    videoListRefreshing, setVideoListRefreshing,
    videoUploadQueueRef, newVideoCategoryName, setNewVideoCategoryName, newVideoPersonName,
    setNewVideoPersonName, newVideoPersonNote, setNewVideoPersonNote, newVideoPersonAvatar,
    setNewVideoPersonAvatar, isVideoEditModalOpen, setIsVideoEditModalOpen, editVideoTitle,
    setEditVideoTitle, editVideoDescription, setEditVideoDescription, editVideoType, setEditVideoType,
    editVideoCategoryIds, setEditVideoCategoryIds, editVideoPersonIds, setEditVideoPersonIds, isCategoryManageModalOpen,
    setIsCategoryManageModalOpen, isVideoPersonManageModalOpen, setIsVideoPersonManageModalOpen,
    editingCategoryId, setEditingCategoryId, editingCategoryName, setEditingCategoryName,
    newManageCategoryName, setNewManageCategoryName, editingPersonId, setEditingPersonId,
    editingPersonName, setEditingPersonName, editingPersonNote, setEditingPersonNote,
    editingPersonAvatar, setEditingPersonAvatar, newManagePersonName, setNewManagePersonName,
    newManagePersonNote, setNewManagePersonNote, newManagePersonAvatar, setNewManagePersonAvatar,
    filteredVideoCategoryTags, filteredVideoPeople, selectedVideoCategories, selectedVideoPeople
  };
}
