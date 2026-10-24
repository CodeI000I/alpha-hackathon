import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api, dataMode, isDemoMode } from './api/client';
import { Workspace } from './appContext';
import AppShell from './components/AppShell';
import { Button, StatePanel } from './components/ui';
import CompanyPage from './pages/CompanyPage';
import FeedDetailPage from './pages/FeedDetailPage';
import IssueDetailPage from './pages/IssueDetailPage';
import FeedPage from './pages/FeedPage';
import LandingPage from './pages/LandingPage';
import OnboardingPage from './pages/OnboardingPage';
import LoginPage from './pages/LoginPage';
import { localKey, useStoredState } from './localState';
import { clearCurrentUserId, currentUserId } from './session';
import { legacyTarget } from './legacyRoutes';
import { resolveActiveRole } from './roleSelection';

function LegacyRedirect() { const location = useLocation(); return <Navigate to={legacyTarget(location.pathname + location.search)} replace />; }
function LegacyHashRedirect({ target }: { target: string }) {
  useEffect(() => { if (target === '/bank.html') window.location.replace('/bank.html'); }, [target]);
  return target === '/bank.html' ? <p role="status">Открываем Альфа-Бизнес…</p> : <Navigate to={target} replace />;
}
function AuthenticatedLayout({ userId, onLogout, logoutError }: { userId: number; onLogout: () => void; logoutError: string | null }) {
  const user = useQuery({ queryKey: ['user', userId], queryFn: ({ signal }) => api.user(userId, signal) });
  const roles = useQuery({ queryKey: ['roles'], queryFn: api.roles });
  const companyId = user.data?.companyId ?? null;
  const company = useQuery({ queryKey: ['company', companyId], queryFn: ({ signal }) => api.company(companyId!, signal), enabled: companyId !== null });
  const [saved, setSaved] = useStoredState<number[]>(localKey(userId, 'saved', companyId), []);
  const [storedRole, setActiveRole] = useStoredState<string>(localKey(userId, 'activeRole', companyId), '');
  const activeRole = resolveActiveRole(user.data?.roles ?? [], storedRole);
  useEffect(() => { if (user.data && storedRole && !user.data.roles.includes(storedRole)) setActiveRole(activeRole); }, [user.data, storedRole, activeRole, setActiveRole]);
  if (user.isPending) return <div className="fatal-state" role="status">Открываем Сигнал…</div>;
  if (user.isError && !user.data) return <div className="fatal-state"><StatePanel tone="error" title="Не удалось восстановить сессию" text={user.error.message} action={<><Button onClick={() => user.refetch()}>Повторить</Button> <Button onClick={onLogout}>Начать заново</Button></>} /></div>;
  const toggleSaved = (id: number) => setSaved(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  return <Workspace.Provider value={{ user: user.data, company: company.data, roles: roles.data ?? [], activeRole, setActiveRole, saved, toggleSaved }}>
    <AppShell onLogout={onLogout}>
      {logoutError && <p className="integration-warning" role="alert">Не удалось завершить сеанс: {logoutError}</p>}
      {user.isRefetchError && <p className="integration-warning" role="alert">Не удалось обновить профиль. Показаны ранее полученные данные. <button onClick={() => user.refetch()}>Повторить</button></p>}
      {roles.isError && <p className="integration-warning" role="alert">Каталог ролей не загрузился: {roles.error.message} <button onClick={() => roles.refetch()}>Повторить</button></p>}
      {company.isError && <p className="integration-warning" role="alert">Данные компании не загрузились: {company.error.message} <button onClick={() => company.refetch()}>Повторить</button></p>}
      <Outlet />
    </AppShell>
  </Workspace.Provider>;
}
export default function App() {
  const [userId, setUserId] = useState<number | null>(() => isDemoMode ? currentUserId(dataMode) : null);
  const session = useQuery({ queryKey: ['auth', 'me'], queryFn: ({ signal }) => api.me(signal), enabled: !isDemoMode, retry: false });
  const [signedOut, setSignedOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const navigate = useNavigate(); const location = useLocation(); const queryClient = useQueryClient();
  useEffect(() => { window.scrollTo({ top: 0, left: 0 }); }, [location.pathname]);
  const activeUserId = isDemoMode ? userId : session.data?.id ?? userId;
  const complete = (id: number) => { queryClient.clear(); setSignedOut(false); setLogoutError(null); setUserId(id); navigate('/dashboard', { replace: true }); };
  const logout = async () => {
    setLogoutError(null);
    try {
      if (isDemoMode) clearCurrentUserId(dataMode);
      else await api.logout();
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : 'Попробуйте ещё раз.');
      return;
    }
    queryClient.clear(); setSignedOut(true); setUserId(null); navigate('/login', { replace: true });
  };
  if (location.hash.startsWith('#/')) return <LegacyHashRedirect target={legacyTarget(location.hash)} />;
  if (!isDemoMode && session.isPending && userId === null) return <div className="fatal-state" role="status">Проверяем сессию…</div>;
  return <Routes>
    <Route path="/" element={<Navigate to={activeUserId ? '/dashboard' : '/register'} replace />} />
    <Route path="/landing" element={<LandingPage hasSession={activeUserId !== null} />} />
    <Route path="/register" element={activeUserId ? <Navigate to="/dashboard" replace /> : <OnboardingPage onComplete={complete} />} />
    <Route path="/login" element={activeUserId ? <Navigate to="/dashboard" replace /> : <LoginPage onComplete={complete} />} />
    <Route element={activeUserId ? <AuthenticatedLayout userId={activeUserId} onLogout={logout} logoutError={logoutError} /> : <Navigate to={signedOut ? '/login' : '/register'} replace />}>
      <Route path="/dashboard" element={<FeedPage userId={activeUserId!} />} />
      <Route path="/news/:itemId" element={<FeedDetailPage userId={activeUserId!} />} />
      <Route path="/issues/:issueId" element={<IssueDetailPage />} />
      <Route path="/profile" element={<CompanyPage userId={activeUserId!} />} />
    </Route>
    {['/onboarding', '/feed', '/feed/:itemId', '/company', '/news'].map(path => <Route key={path} path={path} element={<LegacyRedirect />} />)}
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}
