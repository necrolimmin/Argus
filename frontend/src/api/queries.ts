import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

export const keys = {
  units: ["units"] as const,
  // "all" and per-unit lists must not share a cache entry.
  cameras: (unitId: string | null) => (unitId ? (["cameras", "unit", unitId] as const) : (["cameras", "all"] as const)),
  allCameras: ["cameras"] as const,
  employees: ["employees"] as const,
  users: ["users"] as const,
  devices: ["devices"] as const,
  credentials: ["credentials"] as const,
};

export function useUnits() {
  return useQuery({ queryKey: keys.units, queryFn: api.units, staleTime: 30_000 });
}

export function useCameras(unitId: string | null, enabled = true) {
  return useQuery({
    queryKey: keys.cameras(unitId),
    queryFn: () => api.cameras({ org_unit_id: unitId }),
    enabled,
    staleTime: 30_000,
  });
}

export function useDevices() {
  return useQuery({ queryKey: keys.devices, queryFn: api.devices, refetchInterval: 30_000 });
}

export function useCredentials() {
  return useQuery({ queryKey: keys.credentials, queryFn: api.credentials, staleTime: 30_000 });
}
