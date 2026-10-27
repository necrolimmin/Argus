import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Direction } from "../api/types";

export function DirectionBadge({ direction, showNone = false }: { direction: Direction; showNone?: boolean }) {
  const { t } = useTranslation();
  if (direction === "none" && !showNone) return null;
  const Icon = direction === "exit" ? ArrowUpFromLine : ArrowDownToLine;
  return (
    <span className={`dir dir-${direction}`}>
      {direction !== "none" && <Icon size={13} strokeWidth={2.2} aria-hidden />}
      {t(`direction.${direction}`)}
    </span>
  );
}
