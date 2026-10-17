import type { Person } from "../types";
import { filterPersonMatches } from "./personPicker";

export function filterPeopleByTag(persons: Person[], query: string, tagId: string): Person[] {
  return filterPersonMatches(
    tagId ? persons.filter((person) => person.tag_ids?.includes(Number(tagId))) : persons,
    query
  );
}
