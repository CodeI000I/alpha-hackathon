import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { currentUserId } from "./session";
import FeedPage from "./pages/FeedPage";
import CompanyPage from "./pages/CompanyPage";
import OnboardingPage from "./pages/OnboardingPage";

export default function App() {
  const userId = currentUserId();
  return (
    <div className="layout">
      <header className="header">
        <span className="logo">Альфа Инсайты</span>
        {userId && (
          <nav>
            <NavLink to="/feed">Лента</NavLink>
            <NavLink to="/company">Профиль компании</NavLink>
          </nav>
        )}
      </header>
      <main className="content">
        <Routes>
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="/feed" element={userId ? <FeedPage userId={userId} /> : <Navigate to="/onboarding" />} />
          <Route path="/company" element={userId ? <CompanyPage userId={userId} /> : <Navigate to="/onboarding" />} />
          <Route path="*" element={<Navigate to={userId ? "/feed" : "/onboarding"} />} />
        </Routes>
      </main>
    </div>
  );
}
