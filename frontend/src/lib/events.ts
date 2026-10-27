import { useCallback, useEffect, useRef, useState } from "react";

import { api, getToken } from "../api/client";
import type { EventKind, FaceEvent } from "../api/types";

const PAGE = 40;

function startOfToday(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

interface Feed {
  items: FaceEvent[];
  hasMore: boolean;
  loading: boolean;
}

const emptyFeed: Feed = { items: [], hasMore: false, loading: true };

/**
 * Today's events for the given cameras: loaded once over REST, then kept
 * current over a WebSocket that pushes each new event as it happens.
 */
export function useLiveEvents(cameraIds: string[]) {
  const key = [...cameraIds].sort().join(",");
  const [feeds, setFeeds] = useState<Record<EventKind, Feed>>({ recognized: emptyFeed, unknown: emptyFeed });
  const [connected, setConnected] = useState(false);
  const [freshIds, setFreshIds] = useState<Set<string>>(new Set());
  const idsRef = useRef(cameraIds);
  idsRef.current = cameraIds;

  // Initial page for each kind whenever the camera set changes.
  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    const since = startOfToday();
    (["recognized", "unknown"] as const).forEach(async (kind) => {
      setFeeds((f) => ({ ...f, [kind]: emptyFeed }));
      try {
        const items = await api.events({ camera_ids: idsRef.current, kind, since, limit: PAGE });
        if (!cancelled) setFeeds((f) => ({ ...f, [kind]: { items, hasMore: items.length === PAGE, loading: false } }));
      } catch {
        if (!cancelled) setFeeds((f) => ({ ...f, [kind]: { items: [], hasMore: false, loading: false } }));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  // One socket for the dock; resubscribes when the selection changes.
  const wsRef = useRef<WebSocket | null>(null);
  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const open = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/ws/events?token=${encodeURIComponent(getToken() ?? "")}`);
      wsRef.current = ws;
      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
        ws.send(JSON.stringify({ type: "subscribe", camera_ids: idsRef.current }));
      };
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type !== "event") return;
        const event = data.event as FaceEvent;
        setFeeds((f) => {
          const feed = f[event.kind];
          if (feed.items.some((e) => e.id === event.id)) return f;
          return { ...f, [event.kind]: { ...feed, items: [event, ...feed.items] } };
        });
        setFreshIds((s) => new Set(s).add(event.id));
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(open, Math.min(15_000, 1_000 * 2 ** attempt++));
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "subscribe", camera_ids: cameraIds }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const loadMore = useCallback(
    async (kind: EventKind) => {
      const feed = feeds[kind];
      const last = feed.items[feed.items.length - 1];
      if (!last) return;
      setFeeds((f) => ({ ...f, [kind]: { ...f[kind], loading: true } }));
      const items = await api
        .events({ camera_ids: idsRef.current, kind, since: startOfToday(), before: last.occurred_at, limit: PAGE })
        .catch(() => []);
      setFeeds((f) => ({
        ...f,
        [kind]: { items: [...f[kind].items, ...items], hasMore: items.length === PAGE, loading: false },
      }));
    },
    [feeds],
  );

  const markLinked = useCallback((eventId: string, name: string) => {
    setFeeds((f) => ({
      ...f,
      unknown: { ...f.unknown, items: f.unknown.items.map((e) => (e.id === eventId ? { ...e, linked_employee_name: name } : e)) },
    }));
  }, []);

  return { feeds, connected, freshIds, loadMore, markLinked };
}
