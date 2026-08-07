import { match } from "pinyin-pro";

import { sortByPinyin } from "./sort";

export type SelectablePerson = {
  id: number;
  display_name: string;
  is_unknown: boolean;
};

type AssignedPerson = {
  person_id: number;
};

export function matchesPersonSearch(name: string, query: string): boolean {
  const keyword = query.trim();
  if (!keyword) return true;
  if (name.toLocaleLowerCase().includes(keyword.toLocaleLowerCase())) return true;
  return match(name, keyword, {
    continuous: true,
    insensitive: true,
    precision: "start",
    lastPrecision: "start",
    space: "ignore",
    v: true
  }) !== null;
}

export function filterPersonMatches<T extends SelectablePerson>(persons: T[], query: string): T[] {
  return sortByPinyin(
    persons.filter((person) => matchesPersonSearch(person.display_name, query)),
    (person) => person.display_name
  );
}

export function resolveExistingPerson<T extends SelectablePerson>(
  persons: T[],
  query: string,
  selectedPersonId: string
): T | null {
  const selectedId = Number(selectedPersonId);
  if (selectedPersonId && Number.isInteger(selectedId)) {
    const selected = persons.find((person) => person.id === selectedId);
    if (selected) return selected;
  }
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return null;
  return persons.find((person) => person.display_name.toLocaleLowerCase() === normalized) ?? null;
}

export function availablePhotoPersons<T extends SelectablePerson>(persons: T[], assigned: AssignedPerson[]): T[] {
  const assignedIds = new Set(assigned.map((person) => person.person_id));
  return sortByPinyin(
    persons.filter((person) => !person.is_unknown && !assignedIds.has(person.id)),
    (person) => person.display_name
  );
}

export function availableUploadPersons<T extends SelectablePerson>(persons: T[], selectedPersonIds: number[]): T[] {
  const selectedIds = new Set(selectedPersonIds);
  return sortByPinyin(
    persons.filter((person) => !person.is_unknown && !selectedIds.has(person.id)),
    (person) => person.display_name
  );
}

export function mergePersonIds(current: number[], additions: number[]): number[] {
  return Array.from(new Set([...current, ...additions]));
}
