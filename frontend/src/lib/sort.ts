import { pinyin } from "pinyin-pro";

const textCollator = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base"
});

const pinyinKeyCache = new Map<string, string>();

function getPinyinSortKey(value: string): string {
  const cached = pinyinKeyCache.get(value);
  if (cached) {
    return cached;
  }

  const normalized = value.normalize("NFKC").trim();
  const key = pinyin(normalized, {
    toneType: "none",
    type: "array",
    nonZh: "consecutive",
    v: true
  })
    .join(" ")
    .toLowerCase();

  pinyinKeyCache.set(value, key);
  return key;
}

export function compareByPinyin(left: string, right: string): number {
  return (
    textCollator.compare(getPinyinSortKey(left), getPinyinSortKey(right)) ||
    textCollator.compare(left, right)
  );
}

export function sortByPinyin<T extends { id: number }>(items: T[], getName: (item: T) => string): T[] {
  return [...items].sort((left, right) => compareByPinyin(getName(left), getName(right)) || left.id - right.id);
}

export function sortByPinyinName<T extends { id: number; name: string }>(items: T[]): T[] {
  return sortByPinyin(items, (item) => item.name);
}
