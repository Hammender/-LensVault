import { X } from "lucide-react";

import SearchableSelect from "./SearchableSelect";
import {
  availableUploadPersons,
  filterPersonMatches,
  resolveExistingPerson
} from "../lib/personPicker";
import type { Person } from "../types";

type UploadPersonPickerProps = {
  id: string;
  persons: Person[];
  selectedIds: number[];
  query: string;
  notice: string | null;
  disabled?: boolean;
  onQueryChange: (query: string) => void;
  onNoticeChange: (notice: string | null) => void;
  onAdd: (personId: number) => void;
  onRemove: (personId: number) => void;
};

export default function UploadPersonPicker({
  id,
  persons,
  selectedIds,
  query,
  notice,
  disabled = false,
  onQueryChange,
  onNoticeChange,
  onAdd,
  onRemove
}: UploadPersonPickerProps) {
  const selectedPersons = selectedIds
    .map((personId) => persons.find((person) => person.id === personId))
    .filter((person): person is Person => person !== undefined);
  const availablePersons = availableUploadPersons(persons, selectedIds);
  const matches = filterPersonMatches(availablePersons, query);
  const options = matches.map((person) => ({
    value: String(person.id),
    label: person.display_name,
    meta: `样本 ${person.sample_count}`
  }));

  function selectPerson(personId: number) {
    onAdd(personId);
    onQueryChange("");
    onNoticeChange(null);
  }

  function confirmExactName() {
    if (!query.trim()) return;
    const person = resolveExistingPerson(availablePersons, query, "");
    if (person) {
      selectPerson(person.id);
      return;
    }
    onNoticeChange(
      matches.length > 0
        ? "请从匹配结果中选择一个具体人物。"
        : "所选人物不存在，请先在样本库创建人物后再上传。"
    );
  }

  return (
    <div className="upload-person-picker">
      {selectedPersons.length > 0 && (
        <div className="upload-person-chips" aria-label="已选人物">
          {selectedPersons.map((person) => (
            <button
              key={person.id}
              type="button"
              className="upload-person-chip"
              disabled={disabled}
              title={`移除${person.display_name}`}
              aria-label={`移除人物${person.display_name}`}
              onClick={() => onRemove(person.id)}
            >
              <span>{person.display_name}</span>
              <X size={13} aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
      <SearchableSelect
        id={id}
        value=""
        query={query}
        options={options}
        placeholder="搜索并选择人物（可多选）"
        emptyText={query.trim() ? "没有匹配人物" : "暂无可选人物"}
        disabled={disabled}
        autoActivateFirstOption={false}
        onQueryChange={(nextQuery) => {
          onQueryChange(nextQuery);
          onNoticeChange(null);
        }}
        onSelect={(option) => selectPerson(Number(option.value))}
        onEnter={confirmExactName}
      />
      {notice && <p className="searchable-picker-notice" role="alert">{notice}</p>}
    </div>
  );
}
