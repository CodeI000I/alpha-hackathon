import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { isDemoMode } from '../api/client';
import { useWorkspace } from '../appContext';
import { Icon } from './Icon';
import { DemoBadge } from './ui';
export default function AppShell({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
  const { user, company, roles, activeRole } = useWorkspace(); const location = useLocation();
  const [open, setOpen] = useState(false); const menu = useRef<HTMLDivElement>(null); const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => { setOpen(false); }, [location.pathname, location.search]);
  useEffect(() => {
    if (!open) return;
    const pointer = (event: PointerEvent) => { if (!menu.current?.contains(event.target as Node)) setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('pointerdown', pointer); document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', pointer); document.removeEventListener('keydown', key); };
  }, [open]);
  const initials = (user.fullName || user.email).split(/\s/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
  const isDashboard = location.pathname === '/dashboard'; const saved = location.search.includes('saved=1');
  return <div className="w-app">
    <a className="skip-link" href="#main-content">Перейти к содержимому</a>
    <header className="w-topbar">
      <a className="w-brand" href="/bank.html"><span className="w-alfa">A</span>Альфа-Бизнес</a>
      <Link className="w-top-service" to="/dashboard">Сигнал</Link>{isDemoMode && <DemoBadge>Деморежим</DemoBadge>}
      <time className="w-header-date" dateTime={new Date().toISOString()}>{new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}</time>
      <div className="w-user-menu" ref={menu}>
        <button ref={trigger} className="w-user" aria-label="Меню пользователя" aria-expanded={open} aria-controls="user-menu" onClick={() => setOpen(!open)}>{initials}</button>
        {open && <div className="w-user-popover" id="user-menu"><strong>{user.fullName || 'Пользователь'}</strong><span>{user.email}</span><Link to="/profile?tab=roles">Личный кабинет</Link><button onClick={onLogout}><Icon name="logout" size={16} /> Выйти</button></div>}
      </div>
    </header>
    <div className="w-layout">
      <aside className="w-sidebar">
        <div className="w-company"><span className="w-avatar"><Icon name="building" /></span><strong>{company?.name ?? (user.companyId === null ? 'Компания не указана' : 'Компания')}</strong><span>{company?.inn ? 'ИНН ' + company.inn : 'Профиль компании'}</span></div>
        <nav aria-label="Основная навигация">
          <Link className={'w-nav ' + (isDashboard && !saved ? 'active' : '')} to="/dashboard"><Icon name="home" />Обзор</Link>
          <Link className={'w-nav ' + (isDashboard && saved ? 'active' : '')} to="/dashboard?saved=1"><Icon name="bookmark" />Закладки <small>Демо</small></Link>
          <Link className={'w-nav ' + (location.pathname === '/profile' ? 'active' : '')} to="/profile?tab=roles"><Icon name="user" />Личный кабинет</Link>
        </nav>
        <div className="w-sidebar-bottom"><span>Активный ракурс</span><strong>{roles.find(role => role.code === activeRole)?.name ?? 'Все назначенные роли'}</strong><Link className="action-link" to="/profile?tab=roles">Настроить роли</Link><Link to="/landing">О сервисе</Link></div>
      </aside>
      <main id="main-content" tabIndex={-1} className={'w-main' + (location.pathname.startsWith('/news/') ? ' w-main-news' : '')}>{children}</main>
    </div>
  </div>;
}
