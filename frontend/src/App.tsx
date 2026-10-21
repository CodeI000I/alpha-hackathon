import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, isDemoMode } from "./api/client";
import AppShell from "./components/AppShell";
import { Button, StatePanel } from "./components/ui";
import CompanyPage from "./pages/CompanyPage";
import FeedDetailPage from "./pages/FeedDetailPage";
import FeedPage from "./pages/FeedPage";
import LandingPage from "./pages/LandingPage";
import OnboardingPage from "./pages/OnboardingPage";
import { localKey, useStoredState } from "./localState";
import { clearCurrentUserId, currentUserId } from "./session";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0 });
  }, [pathname]);
  return null;
}

function AuthenticatedLayout({ userId, onLogout }: { userId: number; onLogout: () => void }) {
  const [saved] = useStoredState<number[]>(localKey(userId, "saved"), []);
  const user = useQuery({ queryKey: ["user", userId], queryFn: () => api.user(userId) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const companyId = user.data?.companyId ?? null;
  const company = useQuery({
    queryKey: ["company", companyId],
    queryFn: () => api.company(companyId!),
    enabled: companyId !== null,
  });
  const roleLabel = user.data?.roles
    .map((code) => roles.data?.find((role) => role.code === code)?.name ?? code)
    .join(", ");

  if (user.isLoading) {
    return <div className="app-loading"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><p>Открываем Альфа Инсайты…</p></div>;
  }
  if (user.isError) {
    return (
      <div className="fatal-state">
        <StatePanel
          tone="error"
          title="Не удалось восстановить сессию"
          text={user.error.message}
          action={<Button onClick={onLogout}>Начать заново</Button>}
        />
      </div>
    );
  }

  return (
    <AppShell
      userName={user.data?.fullName}
      companyName={company.data?.name}
      rolesLabel={roleLabel}
      savedCount={saved.length}
      onLogout={onLogout}
      demoMode={isDemoMode}
    >
      <Outlet />
    </AppShell>
  );
}

export default function App() {
  const [userId, setUserId] = useState<number | null>(() => currentUserId());
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const logout = () => {
    clearCurrentUserId();
    queryClient.clear();
    setUserId(null);
    navigate("/", { replace: true });
  };

  return (
    <>
      <ScrollToTop />
      <Routes>
      <Route path="/" element={<LandingPage hasSession={userId !== null} />} />
      <Route
        path="/onboarding"
        element={
          userId ? (
            <Navigate to="/feed" replace />
          ) : (
            <OnboardingPage
              onComplete={(id) => {
                setUserId(id);
                navigate("/feed", { replace: true });
              }}
            />
          )
        }
      />
      <Route path="/login" element={<Navigate to={userId ? "/feed" : "/onboarding"} replace />} />

      {userId ? (
        <Route element={<AuthenticatedLayout userId={userId} onLogout={logout} />}>
          <Route path="/feed" element={<FeedPage userId={userId} />} />
          <Route path="/feed/:itemId" element={<FeedDetailPage userId={userId} />} />
          <Route path="/company" element={<CompanyPage userId={userId} />} />
        </Route>
      ) : (
        <>
          <Route path="/feed" element={<Navigate to="/onboarding" replace />} />
          <Route path="/feed/:itemId" element={<Navigate to="/onboarding" replace />} />
          <Route path="/company" element={<Navigate to="/onboarding" replace />} />
        </>
      )}

      <Route path="*" element={<Navigate to={userId ? "/feed" : "/"} replace />} />
      </Routes>
    </>
  );
}
