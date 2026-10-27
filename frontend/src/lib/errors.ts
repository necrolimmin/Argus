import type { TFunction } from "i18next";

import { ApiError } from "../api/client";

export function errorText(t: TFunction, err: unknown): string {
  return codeText(t, err instanceof ApiError ? err.code : "unknown");
}

/** Message for a machine-readable code, e.g. one returned inside a result. */
export function codeText(t: TFunction, code: string): string {
  const text = t(`errors.${code}`, { defaultValue: "" });
  return text || t("errors.unknown", { code });
}
