import { useCallback, useState } from "react";

import { listPersons, listTags } from "../api";
import { sortByPinyinName } from "../lib/sort";
import type { Person, Tag } from "../types";

export function useCatalog() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);

  const refreshPeople = useCallback(async () => {
    const nextPersons = await listPersons();
    setPersons(nextPersons);
    return nextPersons;
  }, []);

  const refreshTags = useCallback(async () => {
    const nextTags = sortByPinyinName(await listTags());
    setTags(nextTags);
    return nextTags;
  }, []);

  return {
    persons,
    tags,
    setPersons,
    setTags,
    refreshPeople,
    refreshTags
  };
}

export type CatalogModel = ReturnType<typeof useCatalog>;
