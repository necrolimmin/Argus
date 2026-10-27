import { useTranslation } from "react-i18next";

import { useCredentials } from "../api/queries";

export interface CredentialValue {
  credential_id: string | null;
  username: string;
  password: string;
}

interface Props {
  value: CredentialValue;
  onChange: (value: CredentialValue) => void;
  /** Editing an existing device: an empty password keeps the stored one. */
  keepHint?: boolean;
}

/** A saved profile, or a login and password typed in. */
export function CredentialPicker({ value, onChange, keepHint }: Props) {
  const { t } = useTranslation();
  const { data: profiles = [] } = useCredentials();
  return (
    <>
      {profiles.length > 0 && (
        <label className="field wide">
          <span>{t("devices.login")}</span>
          <select
            className="select"
            value={value.credential_id ?? ""}
            onChange={(e) => onChange({ ...value, credential_id: e.target.value || null })}
          >
            <option value="">{t("devices.manual")}</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.username})
              </option>
            ))}
          </select>
        </label>
      )}
      {!value.credential_id && (
        <>
          <label className="field">
            <span>{t("devices.username")}</span>
            <input
              className="input"
              value={value.username}
              onChange={(e) => onChange({ ...value, username: e.target.value })}
              autoComplete="off"
            />
          </label>
          <label className="field">
            <span>{t("devices.password")}</span>
            <input
              className="input"
              type="password"
              value={value.password}
              onChange={(e) => onChange({ ...value, password: e.target.value })}
              autoComplete="new-password"
              placeholder={keepHint ? "••••••" : ""}
            />
            {keepHint && <span className="hint">{t("devices.passwordKeep")}</span>}
          </label>
        </>
      )}
    </>
  );
}
