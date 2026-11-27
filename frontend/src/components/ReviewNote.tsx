// The projection engine's review status, as a note on the projection screens (brief 27, #254).
// It reads the record: pending, checked by the owner (never called a professional validation),
// or validated by a professional.
import { useReviews } from "../api/reviews";
import { useI18n } from "../i18n/I18n";

/** 2026-11-27 as 27/11/2026, as in Cyprus in either language. */
export function dayMonthYear(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

export function EngineReviewNote() {
  const { t } = useI18n();
  const data = useReviews().data;
  // Older test doubles answer every request with one object: read only a list.
  const found = Array.isArray(data)
    ? data.find((r) => r.subject === "PROJECTION_ENGINE")
    : undefined;
  let text = t("pj.pendingReview");
  if (found?.status === "OWNER_CHECKED" && found.on) {
    text = t("pj.ownerChecked").replace("{on}", dayMonthYear(found.on));
  } else if (found?.status === "PROFESSIONALLY_VERIFIED" && found.on) {
    text = t("pj.professionallyValidated")
      .replace("{by}", found.by)
      .replace("{on}", dayMonthYear(found.on));
  }
  return (
    <p className="notice" role="note">
      {text}
    </p>
  );
}
