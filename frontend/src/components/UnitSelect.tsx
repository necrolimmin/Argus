import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { OrgUnit } from "../api/types";
import { buildTree, flatten } from "../lib/tree";

interface Props {
  units: OrgUnit[];
  value: string;
  onChange: (id: string) => void;
  id?: string;
  required?: boolean;
}

/** Native select with the hierarchy shown by indentation. */
export function UnitSelect({ units, value, onChange, id, required }: Props) {
  const { t } = useTranslation();
  const options = useMemo(() => flatten(buildTree(units)), [units]);
  return (
    <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)} required={required}>
      <option value="" disabled>
        —
      </option>
      {options.map((u) => (
        <option key={u.id} value={u.id}>
          {" ".repeat(u.depth)}
          {u.name} ({t(`levels.${u.level}`).toLowerCase()})
        </option>
      ))}
    </select>
  );
}
