import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";

export type SearchableSelectOption = {
  value: string;
  label: string;
  meta?: string;
};

type SearchableSelectProps = {
  id: string;
  value: string;
  query: string;
  options: SearchableSelectOption[];
  placeholder: string;
  emptyText: string;
  disabled?: boolean;
  onQueryChange: (query: string) => void;
  onSelect: (option: SearchableSelectOption) => void;
  onOpen?: () => void;
  onCancel?: () => void;
  onEnter?: () => void;
  selectActiveOnEnter?: boolean;
  autoActivateFirstOption?: boolean;
};

export default function SearchableSelect({
  id,
  value,
  query,
  options,
  placeholder,
  emptyText,
  disabled = false,
  onQueryChange,
  onSelect,
  onOpen,
  onCancel,
  onEnter,
  selectActiveOnEnter = true,
  autoActivateFirstOption = true
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const blurTimer = useRef<number | null>(null);
  const pointerInsideTimer = useRef<number | null>(null);
  const pointerInside = useRef(false);
  const optionKey = options.map((option) => option.value).join("|");
  const listId = `${id}-options`;

  useEffect(() => {
    if (!open) {
      setActiveIndex(-1);
      return;
    }
    setActiveIndex(autoActivateFirstOption && options.length > 0 ? 0 : -1);
  }, [autoActivateFirstOption, open, optionKey, options.length]);

  useEffect(() => () => {
    if (blurTimer.current !== null) window.clearTimeout(blurTimer.current);
    if (pointerInsideTimer.current !== null) window.clearTimeout(pointerInsideTimer.current);
  }, []);

  function markPointerInside() {
    pointerInside.current = true;
    if (pointerInsideTimer.current !== null) window.clearTimeout(pointerInsideTimer.current);
    // Native scrollbar interaction can blur the input before the pointer is released.
    pointerInsideTimer.current = window.setTimeout(() => {
      pointerInside.current = false;
      pointerInsideTimer.current = null;
    }, 300);
  }

  function openPicker() {
    if (disabled) return;
    if (blurTimer.current !== null) window.clearTimeout(blurTimer.current);
    if (!open) onOpen?.();
    setOpen(true);
  }

  function closePicker(cancelled: boolean) {
    setOpen(false);
    setActiveIndex(-1);
    pointerInside.current = false;
    if (pointerInsideTimer.current !== null) {
      window.clearTimeout(pointerInsideTimer.current);
      pointerInsideTimer.current = null;
    }
    if (cancelled) onCancel?.();
  }

  function selectOption(option: SearchableSelectOption) {
    onSelect(option);
    closePicker(false);
  }

  return (
    <div className="searchable-picker" ref={pickerRef}>
      <Search size={16} aria-hidden="true" />
      <input
        id={id}
        value={query}
        disabled={disabled}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        autoComplete="off"
        placeholder={placeholder}
        onFocus={openPicker}
        onClick={openPicker}
        onBlur={(event) => {
          const relatedTarget = event.relatedTarget as Node | null;
          blurTimer.current = window.setTimeout(() => {
            const focusStayedInside = relatedTarget && pickerRef.current?.contains(relatedTarget);
            if (pointerInside.current || focusStayedInside) return;
            closePicker(true);
          }, 120);
        }}
        onChange={(event) => {
          onQueryChange(event.target.value);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            openPicker();
            setActiveIndex((current) => Math.min(options.length - 1, current + 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            openPicker();
            setActiveIndex((current) => Math.max(0, current <= 0 ? 0 : current - 1));
          } else if (event.key === "Enter") {
            event.preventDefault();
            if (selectActiveOnEnter && open && activeIndex >= 0 && options[activeIndex]) {
              selectOption(options[activeIndex]);
            } else {
              onEnter?.();
            }
          } else if (event.key === "Escape") {
            event.preventDefault();
            closePicker(true);
          }
        }}
      />
      {open && (
        <div className="searchable-picker-options" id={listId} role="listbox" onPointerDownCapture={markPointerInside}>
          {options.length > 0 ? options.map((option, index) => (
            <button
              id={`${listId}-${index}`}
              type="button"
              role="option"
              aria-selected={value === option.value}
              className={index === activeIndex ? "active" : ""}
              key={option.value}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectOption(option)}
            >
              <span>{option.label}</span>
              {option.meta && <small>{option.meta}</small>}
            </button>
          )) : (
            <span className="searchable-picker-empty">{emptyText}</span>
          )}
        </div>
      )}
    </div>
  );
}
