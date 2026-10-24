import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useWorkspace } from '../appContext';
import { Icon } from './Icon';
export default function AppShell({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
  const { user, company, roles, activeRole, setActiveRole } = useWorkspace(); const location = useLocation();
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
  const roleName = (code: string) => roles.find(role => role.code === code)?.name ?? 'Название роли недоступно';
  const currentRole = activeRole ? roleName(activeRole) : 'Роль не выбрана';
  const isDashboard = location.pathname === '/dashboard'; const saved = location.search.includes('saved=1');
  return <div className="w-app">
    <a className="skip-link" href="#main-content">Перейти к содержимому</a>
    <header className="w-topbar">
      <Link className="w-brand" to="/dashboard"><span className="w-alfa">A</span>Альфа-Бизнес</Link>
      <Link className="w-top-service" to="/dashboard">Сигнал</Link>
      <time className="w-header-date" dateTime={new Date().toISOString()}>{new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}</time>
      <div className="w-header-role" title={currentRole}>
        <span className="w-header-role-name">{currentRole}</span>
        {user.roles.length > 1 && <><Icon name="chevron-down" size={14} /><select aria-label="Ваша роль" value={activeRole} onChange={event => setActiveRole(event.target.value)}>{user.roles.map(code => <option key={code} value={code}>{roleName(code)}</option>)}</select></>}
      </div>
      <div className="w-user-menu" ref={menu}>
        <button ref={trigger} className="w-user" aria-label="Меню пользователя" aria-expanded={open} aria-controls="user-menu" onClick={() => setOpen(!open)}>{initials}</button>
        {open && <nav className="w-profile-menu" id="user-menu" aria-label="Профиль"><strong>{user.fullName || 'Пользователь'}</strong><span>{currentRole || 'Роль не выбрана'}</span><Link to="/profile?tab=roles" onClick={() => setOpen(false)}>Личный кабинет</Link>{[['roles', 'Моя роль'], ['company', 'Компания'], ['keywords', 'Ключевые слова'], ['documents', 'Документы']].map(([tab, label]) => <Link key={tab} to={'/profile?tab=' + tab} onClick={() => setOpen(false)}>{label}</Link>)}<button onClick={onLogout}>Выйти</button></nav>}
      </div>
    </header>
    <div className="w-layout">
      <aside className="w-sidebar">
        <div className="w-company"><span className="w-avatar"><Icon name="building" /></span><strong>{company?.name ?? (user.companyId === null ? 'Компания не указана' : 'Компания')}</strong><span>{company?.inn ? 'ИНН ' + company.inn : 'Профиль компании'}</span></div>
        <nav aria-label="Основная навигация">
          <Link className={'w-nav ' + (isDashboard && !saved ? 'active' : '')} to="/dashboard"><Icon name="home" />Обзор</Link>
          <Link className={'w-nav ' + (isDashboard && saved ? 'active' : '')} to="/dashboard?saved=1"><Icon name="bookmark" />Закладки</Link>
          <Link className={'w-nav ' + (location.pathname === '/profile' ? 'active' : '')} to="/profile?tab=roles"><Icon name="user" />Личный кабинет</Link>
        </nav>
        <div className="w-sidebar-bottom"><Link to="/landing">О сервисе</Link></div>
      </aside>
      <main id="main-content" tabIndex={-1} className={'w-main' + (location.pathname.startsWith('/news/') ? ' w-main-news' : '')}>{children}</main>
    </div>
  </div>;
}
