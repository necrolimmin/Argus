import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ProbeResult } from "../../api/types";
import { Thumb } from "../../components/NoImage";

/** What the device said about itself: picture, model, serial, codec, warnings. */
export function ProbeSummary({ result }: { result: ProbeResult }) {
  const { t } = useTranslation();
  const facts: [string, string][] = [
    [t("devices.colType"), t(`devices.kind.${result.kind}`)],
    [t("devices.model"), result.model],
    [t("devices.serial"), result.serial],
    [t("devices.firmware"), result.firmware],
    [t("devices.codec"), result.codec],
  ];
  if (result.kind === "recorder") facts.splice(1, 0, [t("devices.channels"), String(result.channels.length)]);

  return (
    <div className="probe">
      <Thumb className="probe-shot" src={result.snapshot} />
      <div className="probe-facts">
        <dl>
          {facts
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
        </dl>
        {result.duplicates.map((d) => (
          <p key={d.device_id} className="probe-warn">
            <Info size={15} />
            {t("devices.duplicate", { name: d.name })}
          </p>
        ))}
        {result.warnings.map((w) => (
          <p key={w} className="probe-warn">
            <Info size={15} />
            {t(`devices.warnings.${w}`, { defaultValue: w, port: result.rtsp_port })}
          </p>
        ))}
      </div>
    </div>
  );
}
