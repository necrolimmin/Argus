import { ImageOff } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * In place of a picture that is missing or failed to load: a neutral block
 * with an icon and "No image", never a black rectangle. `compact` drops the
 * words for small slots (avatars, thumbnails); they stay in the tooltip.
 */
export function NoImage({ className = "", compact = false }: { className?: string; compact?: boolean }) {
  const { t } = useTranslation();
  const label = t("common.noImage");
  return (
    <span className={`no-image${compact ? " compact" : ""} ${className}`} role="img" aria-label={label} title={compact ? label : undefined}>
      <ImageOff size={compact ? 14 : 18} aria-hidden />
      {!compact && <span>{label}</span>}
    </span>
  );
}

interface ThumbProps {
  src?: string | null;
  className?: string;
  compact?: boolean;
  alt?: string;
}

/** An image that turns into NoImage when there is no source or it fails to load. */
export function Thumb({ src, className = "", compact = false, alt = "" }: ThumbProps) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) return <NoImage className={className} compact={compact} />;
  return <img className={className} src={src} alt={alt} loading="lazy" onError={() => setBroken(true)} />;
}
