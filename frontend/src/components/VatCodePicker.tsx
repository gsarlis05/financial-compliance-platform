// The VAT code picker of an entry line (V1-2i, #231): type a code, a name or a rate to filter;
// favourites first, then the codes used most in this company, then every code by category. The
// star stars or unstars the chosen code for this user. The account's usual code is offered, never
// chosen for the user.
import Decimal from "decimal.js";
import { useState } from "react";
import type { VatCode } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { type ComboGroup, Combobox } from "./Combobox";

const MOST_USED = 5;

interface Props {
  index: number;
  codes: VatCode[];
  value: string;
  onChange: (vatCodeId: string) => void;
  required: boolean;
  favourites: string[];
  onFavourite?: ((vatCodeId: string, on: boolean) => void) | undefined;
  uses: Record<string, number>;
  /** The account's usual code, offered when the line has none. */
  usual?: string | undefined;
}

function percent(rate: string | null): string {
  if (rate === null) {
    return "";
  }
  const [whole = "0", fraction = ""] = new Decimal(rate)
    .times(100)
    .toFixed(2)
    .split(".");
  const trimmed = fraction.replace(/0+$/, "");
  return trimmed ? `${whole}.${trimmed}%` : `${whole}%`;
}

export function VatCodePicker({
  index,
  codes,
  value,
  onChange,
  required,
  favourites,
  onFavourite,
  uses,
  usual,
}: Props) {
  const { t, locale } = useI18n();
  const name = (v: VatCode) =>
    locale === "el" && v.name_el ? v.name_el : v.name;
  const labelOf = (v: VatCode) =>
    `${v.code} · ${name(v)}${v.verified ? "" : ` (${t("vat.unverified")})`}`;
  const byId = new Map(codes.map((v) => [v.id, v]));
  const chosen = byId.get(value);
  const [typed, setTyped] = useState<string | null>(null);
  const text = typed ?? (chosen ? labelOf(chosen) : "");
  const search = (typed ?? "").trim().toLowerCase();

  // A rate matches from its start ("9%" finds 9%, not 19%); codes and names anywhere.
  const matches = (v: VatCode) =>
    !search ||
    percent(v.rate).startsWith(search) ||
    [v.code, v.name, v.name_el, v.id].some((s) =>
      s.toLowerCase().includes(search),
    );
  const option = (v: VatCode) => ({
    value: v.id,
    label: labelOf(v),
    ...(uses[v.id] ? { hint: `(${uses[v.id]})` } : {}),
  });
  const starred = favourites
    .map((id) => byId.get(id))
    .filter((v): v is VatCode => !!v && matches(v));
  const used = codes
    .filter((v) => uses[v.id] && !favourites.includes(v.id) && matches(v))
    .sort((a, b) => (uses[b.id] ?? 0) - (uses[a.id] ?? 0))
    .slice(0, MOST_USED);
  const categories = [...new Set(codes.map((v) => v.category))];
  const groups: ComboGroup[] = [
    { label: t("vatp.favourites"), options: starred.map(option) },
    { label: t("vatp.mostUsed"), options: used.map(option) },
    ...categories.map((category) => ({
      label: category ? t(`vat.category.${category}` as MessageKey) : "",
      options: codes
        .filter((v) => v.category === category && matches(v))
        .map(option),
    })),
  ];

  function onText(next: string) {
    setTyped(next);
    const exact = next.trim().toLowerCase();
    if (!exact) {
      onChange("");
      return;
    }
    // A whole code (S19) or its id chooses it at once.
    const found = codes.find(
      (v) => v.code.toLowerCase() === exact || v.id.toLowerCase() === exact,
    );
    if (found) {
      onChange(found.id);
    }
  }

  const isFavourite = !!chosen && favourites.includes(chosen.id);
  const suggested = !value && usual ? byId.get(usual) : undefined;
  return (
    <>
      <div className="vat-pick">
        <Combobox
          label={`${t("je.vat")} ${index + 1}`}
          text={text}
          groups={groups}
          required={required}
          placeholder={t("vatp.search")}
          emptyText={t("vatp.none")}
          onText={onText}
          onChoose={(o) => {
            setTyped(null);
            onChange(o.value);
          }}
          onLeave={() => setTyped(null)}
        />
        {onFavourite ? (
          <button
            type="button"
            className="star"
            disabled={!chosen}
            aria-pressed={isFavourite}
            aria-label={
              chosen
                ? t(isFavourite ? "vatp.unstar" : "vatp.star").replace(
                    "{code}",
                    chosen.code,
                  )
                : t("vatp.starNone")
            }
            title={chosen ? undefined : t("vatp.starNone")}
            onClick={() => chosen && onFavourite(chosen.id, !isFavourite)}
          >
            {isFavourite ? "★" : "☆"}
          </button>
        ) : null}
      </div>
      {suggested ? (
        <button
          type="button"
          className="link-button"
          onClick={() => onChange(suggested.id)}
        >
          {t("vatp.useUsual").replace("{code}", suggested.code)}
        </button>
      ) : null}
    </>
  );
}
