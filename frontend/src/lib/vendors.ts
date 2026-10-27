import type { Vendor } from "../api/types";

export interface VendorMeta {
  id: Vendor;
  /** Connects by a full link instead of an address. */
  url?: boolean;
  /** Has a web interface Argus reads model and channels from. */
  web?: boolean;
  defaultPort: number;
  /** Channel list cannot be read; the user says how many there are. */
  askChannels?: boolean;
}

export const VENDORS: VendorMeta[] = [
  { id: "hikvision", web: true, defaultPort: 554 },
  { id: "dahua", web: true, defaultPort: 554 },
  { id: "uniview", web: true, defaultPort: 554 },
  { id: "axis", web: true, defaultPort: 554 },
  { id: "vigi", web: true, defaultPort: 554 },
  { id: "reolink", web: true, defaultPort: 554 },
  { id: "ezviz", defaultPort: 554 },
  { id: "dvrip", defaultPort: 34567, askChannels: true },
  { id: "onvif", web: true, defaultPort: 554 },
  { id: "rtsp", url: true, defaultPort: 554 },
  { id: "http", url: true, defaultPort: 80 },
];

export function vendorMeta(id: Vendor): VendorMeta {
  return VENDORS.find((v) => v.id === id) ?? { id, url: true, defaultPort: 554 };
}

/** Maps a discovery hint ("hikvision", "onvif", "") to a vendor Argus can add. */
export function vendorFromScan(hint: string): Vendor {
  return (VENDORS.find((v) => v.id === hint && !v.url)?.id ?? "onvif") as Vendor;
}
