import { useMemo, useState } from "react";

import type { GalleryExportScope } from "../api";
import { filterPersonMatches } from "../personPicker";
import { sortByPinyin, sortByPinyinName } from "../sort";
import type { GalleryPhotoListItem, Person, Tag } from "../types";

type UseGalleryControllerOptions = {
  persons: Person[];
  tags: Tag[];
};

export function useGalleryController({ persons, tags }: UseGalleryControllerOptions) {
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

  const richTag = useMemo(() => tags.find((tag) => tag.name === "图文") ?? null, [tags]);
  const normalTags = useMemo(() => sortByPinyinName(tags.filter((tag) => !tag.is_system)), [tags]);
  const filteredPersons = useMemo(
    () => filterPersonMatches(persons, personSearch),
    [personSearch, persons]
  );
  const selectedFilterPersons = useMemo(
    () => sortByPinyin(persons.filter((person) => selectedPersonIds.includes(person.id)), (person) => person.display_name),
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
    () => sortByPinyin(persons.filter((person) => excludePersonIds.includes(person.id)), (person) => person.display_name),
    [persons, excludePersonIds]
  );
  const excludedFilterTags = useMemo(
    () => tags.filter((tag) => excludeTagIds.includes(tag.id)),
    [tags, excludeTagIds]
  );
  const availableExcludePersons = useMemo(
    () =>
      sortByPinyin(
        persons.filter((person) => !selectedPersonIds.includes(person.id) && !excludePersonIds.includes(person.id)),
        (person) => person.display_name
      ),
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

  return {
    galleryPhotos,
    setGalleryPhotos,
    galleryTotal,
    setGalleryTotal,
    galleryOffset,
    setGalleryOffset,
    gallerySelectionMode,
    setGallerySelectionMode,
    selectedGalleryPhotoIds,
    setSelectedGalleryPhotoIds,
    galleryExportModalOpen,
    setGalleryExportModalOpen,
    galleryExportScope,
    setGalleryExportScope,
    galleryExportPersonIds,
    setGalleryExportPersonIds,
    galleryExportTagIds,
    setGalleryExportTagIds,
    lightboxPhotoId,
    setLightboxPhotoId,
    selectedPersonIds,
    setSelectedPersonIds,
    selectedTagIds,
    setSelectedTagIds,
    excludePersonIds,
    setExcludePersonIds,
    excludeTagIds,
    setExcludeTagIds,
    personSearch,
    setPersonSearch,
    tagSearch,
    setTagSearch,
    showUnknownPersons,
    setShowUnknownPersons,
    showExcludePersons,
    setShowExcludePersons,
    showExcludeTags,
    setShowExcludeTags,
    richTag,
    normalTags,
    filteredPersons,
    selectedFilterPersons,
    knownFilterPersons,
    unknownFilterPersons,
    allFilteredUnknownPersons,
    personSearchActive,
    visibleUnknownFilterPersons,
    selectedUnknownPersonCount,
    allFilteredUnknownSelected,
    filteredTags,
    excludedFilterPersons,
    excludedFilterTags,
    availableExcludePersons,
    availableExcludeKnownPersons,
    availableExcludeUnknownPersons,
    availableExcludeTags
  };
}
