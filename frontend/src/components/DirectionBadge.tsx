import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Direction } from "../api/types";

interface Props {
  direction: Direction;
  showNone?: boolean;
  /** Icon only, the word in the tooltip: for narrow lists. */
  iconOnly?: boolean;
}

export function DirectionBadge({ direction, showNone = false, iconOnly = false }: Props) {
  const { t } = useTranslation();
  if (direction === "none" && !showNone) return null;
  const Icon = direction === "exit" ? ArrowUpFromLine : ArrowDownToLine;
  const word = t(`direction.${direction}`);
  return (
    <span className={`dir dir-${direction}`} title={iconOnly ? word : undefined} aria-label={iconOnly ? word : undefined}>
      {direction !== "none" && <Icon size={13} strokeWidth={2.2} aria-hidden />}
      {!iconOnly && word}
    </span>
  );
}
