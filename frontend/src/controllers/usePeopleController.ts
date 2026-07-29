import { useMemo, useState } from "react";

import { filterPersonMatches } from "../personPicker";
import type { Person, SamplePhoto, Tag, Task } from "../types";

type UsePeopleControllerOptions = {
  persons: Person[];
};

export function usePeopleController({ persons }: UsePeopleControllerOptions) {
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
  const [recognitionNotice, setRecognitionNotice] = useState<{ id: number; message: string } | null>(null);

  const filteredPeopleInLibrary = useMemo(
    () => filterPersonMatches(persons, peopleSearch),
    [peopleSearch, persons]
  );
  const unknownPersonCount = useMemo(() => persons.filter((person) => person.is_unknown).length, [persons]);

  return {
    selectedPerson,
    setSelectedPerson,
    peopleSearch,
    setPeopleSearch,
    peopleBatchDeleteMode,
    setPeopleBatchDeleteMode,
    selectedPersonDeleteIds,
    setSelectedPersonDeleteIds,
    samples,
    setSamples,
    personTags,
    setPersonTags,
    personTagSelectId,
    setPersonTagSelectId,
    personTagName,
    setPersonTagName,
    newPersonName,
    setNewPersonName,
    renameValue,
    setRenameValue,
    task,
    setTask,
    recognitionNotice,
    setRecognitionNotice,
    filteredPeopleInLibrary,
    unknownPersonCount
  };
}
