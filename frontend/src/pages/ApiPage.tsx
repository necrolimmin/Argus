import { Clock, FileBarChart, FileSpreadsheet } from "lucide-react";
import { useTranslation } from "react-i18next";

/*
 * Stage three is not built yet. The page says what the section is for and
 * lists what will come, as inactive items: no buttons and no numbers that
 * would pretend it works.
 */
const UPCOMING = [
  { icon: Clock, title: "api.timesheet", text: "api.timesheetText" },
  { icon: FileBarChart, title: "api.reports", text: "api.reportsText" },
  { icon: FileSpreadsheet, title: "api.excel", text: "api.excelText" },
] as const;

export function ApiPage() {
  const { t } = useTranslation();
  return (
    <div className="page">
      <div className="page-head page-head-lead">
        <h1>{t("api.title")}</h1>
        <p className="lead">{t("api.lead")}</p>
      </div>
      <section className="card upcoming" aria-labelledby="upcoming-title">
        <h2 id="upcoming-title" className="upcoming-title">
          {t("api.upcoming")}
        </h2>
        <ul className="upcoming-list">
          {UPCOMING.map(({ icon: Icon, title, text }) => (
            <li key={title} className="upcoming-item" aria-disabled="true">
              <Icon size={18} aria-hidden className="upcoming-icon" />
              <div className="upcoming-text">
                <span className="upcoming-name">{t(title)}</span>
                <span className="upcoming-desc">{t(text)}</span>
              </div>
              <span className="badge">{t("api.inProgress")}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
