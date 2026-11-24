// An accessible combobox with a list of options (WAI-ARIA 1.2 combobox pattern), used for the VAT
// code picker and for typing suggestions (V1-2i, #231). Arrow keys move, Enter chooses, Escape
// closes; the options can be grouped. Suggestions only fill the field: nothing is chosen for the
// user without a key press or a click.
import { type KeyboardEvent, useId, useState } from "react";
import { useI18n } from "../i18n/I18n";

export interface ComboOption {
  /** What is chosen: a VAT code id, or the text itself for suggestions. */
  value: string;
  label: string;
  /** Extra text for the option, such as how often it was used. */
  hint?: string;
}

export interface ComboGroup {
  label: string;
  options: ComboOption[];
}

interface Props {
  /** The input's accessible name. */
  label: string;
  text: string;
  groups: ComboGroup[];
  onText: (text: string) => void;
  onChoose: (option: ComboOption) => void;
  /** Called when the field loses focus, for example to tidy a half-typed value. */
  onLeave?: (() => void) | undefined;
  onOpen?: (() => void) | undefined;
  required?: boolean | undefined;
  maxLength?: number | undefined;
  placeholder?: string | undefined;
  className?: string | undefined;
  title?: string | undefined;
  emptyText?: string | undefined;
}

export function Combobox({
  label,
  text,
  groups,
  onText,
  onChoose,
  onLeave,
  onOpen,
  required,
  maxLength,
  placeholder,
  className,
  title,
  emptyText,
}: Props) {
  const { t } = useI18n();
  const id = useId();
  const listId = `${id}-list`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const shown = groups.filter((g) => g.options.length > 0);
  const flat = shown.flatMap((g) => g.options);
  const expanded = open && (flat.length > 0 || !!emptyText);
  const optionId = (index: number) => `${id}-o${index}`;

  function show() {
    if (!open) {
      setOpen(true);
      setActive(-1);
      onOpen?.();
    }
  }
  function choose(option: ComboOption) {
    onChoose(option);
    setOpen(false);
    setActive(-1);
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        show();
        return;
      }
      if (flat.length === 0) {
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((active + step + flat.length) % flat.length);
    } else if (event.key === "Enter" && expanded && active >= 0) {
      event.preventDefault();
      const chosen = flat[active];
      if (chosen) {
        choose(chosen);
      }
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  }

  let index = -1;
  return (
    <div className={`combobox ${className ?? ""}`}>
      <input
        role="combobox"
        aria-label={label}
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={
          expanded && active >= 0 ? optionId(active) : undefined
        }
        autoComplete="off"
        value={text}
        required={required}
        maxLength={maxLength}
        placeholder={placeholder}
        title={title}
        onChange={(e) => {
          onText(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={show}
        onClick={show}
        onKeyDown={onKeyDown}
        onBlur={() => {
          setOpen(false);
          setActive(-1);
          onLeave?.();
        }}
      />
      <ul
        id={listId}
        role="listbox"
        aria-label={t("combo.choices").replace("{label}", label)}
        className="combobox-list"
        hidden={!expanded}
      >
        {expanded && flat.length === 0 ? (
          <li className="muted combobox-empty">{emptyText}</li>
        ) : null}
        {expanded
          ? shown.map((group, g) => (
              <li key={`${group.label}-${g}`} role="presentation">
                {group.label ? (
                  <span
                    className="combobox-group"
                    id={`${id}-g${g}`}
                    aria-hidden="true"
                  >
                    {group.label}
                  </span>
                ) : null}
                <ul
                  role="group"
                  aria-label={group.label || undefined}
                  className="combobox-options"
                >
                  {group.options.map((option) => {
                    index += 1;
                    const mine = index;
                    return (
                      <li
                        key={`${option.value}-${mine}`}
                        id={optionId(mine)}
                        role="option"
                        aria-selected={mine === active}
                        className={mine === active ? "active" : undefined}
                        onMouseDown={(e) => {
                          // Keep the focus in the input until the option is chosen.
                          e.preventDefault();
                          choose(option);
                        }}
                        onMouseEnter={() => setActive(mine)}
                      >
                        {option.label}
                        {option.hint ? (
                          <span className="muted combobox-hint">
                            {" "}
                            {option.hint}
                          </span>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))
          : null}
      </ul>
    </div>
  );
}
