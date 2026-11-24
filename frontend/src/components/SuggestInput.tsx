// A text field that offers what was typed before in this company (V1-2i, #231), like a search box:
// matches that start with the text first, then the most used and the most recent. Choosing one
// only fills the field.
import { useEffect, useRef, useState } from "react";
import type { SuggestField, Suggestion } from "../api/entryHelpers";
import { useI18n } from "../i18n/I18n";
import { Combobox } from "./Combobox";

const DELAY_MS = 200;

interface Props {
  label: string;
  field: SuggestField;
  value: string;
  onChange: (value: string) => void;
  suggest?:
    | ((field: SuggestField, text: string) => Promise<Suggestion[]>)
    | undefined;
  required?: boolean | undefined;
  maxLength?: number | undefined;
  placeholder?: string | undefined;
  className?: string | undefined;
}

export function SuggestInput({
  label,
  field,
  value,
  onChange,
  suggest,
  required,
  maxLength,
  placeholder,
  className,
}: Props) {
  const { t } = useI18n();
  const [found, setFound] = useState<Suggestion[]>([]);
  const [asked, setAsked] = useState<string | null>(null);
  const latest = useRef(0);

  useEffect(() => {
    if (!suggest || asked === null) {
      return undefined;
    }
    const ticket = ++latest.current;
    const timer = window.setTimeout(() => {
      suggest(field, asked)
        .then((rows) => {
          if (ticket === latest.current) {
            setFound(rows);
          }
        })
        .catch(() => {
          // Suggestions are a help only: a failure leaves the field as it is.
        });
    }, DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [suggest, field, asked]);

  const options = found
    .filter((s) => s.value !== value)
    .map((s) => ({
      value: s.value,
      label: s.value,
      hint: `(${s.uses})`,
    }));
  return (
    <Combobox
      label={label}
      text={value}
      groups={[{ label: "", options }]}
      required={required}
      maxLength={maxLength}
      placeholder={placeholder}
      className={className}
      title={suggest ? t("sug.help") : undefined}
      onText={(next) => {
        onChange(next);
        setAsked(next);
      }}
      onOpen={() => setAsked(value)}
      onChoose={(o) => onChange(o.value)}
    />
  );
}
