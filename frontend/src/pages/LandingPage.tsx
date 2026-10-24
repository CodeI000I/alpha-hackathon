import { useNavigate } from 'react-router-dom';
import Landing from '../signal/Landing';
import { isDemoMode } from '../api/client';
export default function LandingPage({ hasSession }: { hasSession: boolean }) {
  const navigate = useNavigate();
  return <Landing hasSession={hasSession} goToRegister={() => navigate('/register')} goToDashboard={() => navigate('/dashboard')} productName="Сигнал" demoMode={isDemoMode} />;
}
