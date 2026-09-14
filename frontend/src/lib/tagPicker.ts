export type SelectableTag = {
  id: number;
  name: string;
  is_system: boolean;
};

export function filterTagMatches(tags: SelectableTag[], query: string): SelectableTag[] {
  const keyword = query.trim().toLocaleLowerCase();
  if (!keyword) return tags;
  return tags.filter((tag) => tag.name.toLocaleLowerCase().includes(keyword));
}

export function resolveExistingTag(
  tags: SelectableTag[],
  query: string,
  selectedTagId: string
): SelectableTag | null {
  const selectedId = Number(selectedTagId);
  if (selectedTagId && Number.isInteger(selectedId)) {
    const selected = tags.find((tag) => tag.id === selectedId);
    if (selected) return selected;
  }
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return null;
  return tags.find((tag) => tag.name.toLocaleLowerCase() === normalized) ?? null;
}
