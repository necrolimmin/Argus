import { PlugZap } from "lucide-react";
import { useTranslation } from "react-i18next";

export function ApiPage() {
  const { t } = useTranslation();
  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("api.title")}</h1>
      </div>
      <div className="empty">
        <PlugZap size={36} strokeWidth={1.4} />
        <span>{t("api.body")}</span>
      </div>
    </div>
  );
}
