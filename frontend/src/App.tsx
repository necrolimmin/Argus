import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { api, getToken, handleUnauthorized } from "./api/client";
import { Layout } from "./components/Layout";
import { isViewer, useAuth, useWall } from "./lib/store";
import { ApiPage } from "./pages/ApiPage";
import { CamerasPage } from "./pages/CamerasPage";
import { DevicesPage } from "./pages/DevicesPage";
import { EmbedPage } from "./pages/EmbedPage";
import { LoginPage } from "./pages/LoginPage";
import { OrgPage } from "./pages/OrgPage";
import { UsersPage } from "./pages/UsersPage";

// The component catalogue exists in development builds only: in production
// import.meta.env.DEV is false, so this import and the page are dropped.
const ComponentsPage = import.meta.env.DEV
  ? lazy(() => import("./pages/dev/ComponentsPage").then((m) => ({ default: m.ComponentsPage })))
  : null;

export function App() {
  // The player other sites put in a frame: no login, no menu.
  if (window.location.pathname.startsWith("/embed/")) return <EmbedPage />;
  return <Site />;
}

function Site() {
  const { user, setUser } = useAuth();
  const hydrateWall = useWall((s) => s.hydrate);
  const [checking, setChecking] = useState(() => !!getToken());

  useEffect(() => {
    handleUnauthorized(() => setUser(null));
    if (!getToken()) return;
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, [setUser]);

  useEffect(() => {
    if (user) hydrateWall(user.id);
  }, [user, hydrateWall]);

  if (checking) return null;
  if (!user) return <LoginPage />;

  if (isViewer(user)) {
    return (
      <Routes>
        <Route element={<Layout />}>
          <Route path="/cameras" element={<CamerasPage />} />
          <Route path="*" element={<Navigate to="/cameras" replace />} />
        </Route>
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/cameras" element={<CamerasPage />} />
        <Route path="/devices" element={<DevicesPage />} />
        <Route path="/org" element={<OrgPage />} />
        <Route path="/integrations" element={<ApiPage />} />
        <Route path="/users" element={<UsersPage />} />
        {ComponentsPage && (
          <Route
            path="/dev/components"
            element={
              <Suspense fallback={null}>
                <ComponentsPage />
              </Suspense>
            }
          />
        )}
        <Route path="*" element={<Navigate to="/cameras" replace />} />
      </Route>
    </Routes>
  );
}
