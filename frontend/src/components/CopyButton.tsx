import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

/** Copies a value and says so for a moment. */
export function CopyButton({ text, label }: { text: string; label?: string }) {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  const title = done ? t("common.copied") : (label ?? t("common.copy"));
  return (
    <button
      type="button"
      className="icon-btn sm copy-button"
      title={title}
      aria-label={label ?? t("common.copy")}
      onClick={() => {
        navigator.clipboard?.writeText(text).catch(() => {});
        setDone(true);
        window.setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

/** A line to copy as it is: an address, a key, a command. */
export function CopyLine({ text }: { text: string }) {
  return (
    <div className="copy-line">
      <code>{text}</code>
      <CopyButton text={text} />
    </div>
  );
}
