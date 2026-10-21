import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { Icon } from "./Icon";
import { DemoBadge } from "./ui";

export interface AppShellProps {
  children: ReactNode;
  userName?: string;
  companyName?: string;
  rolesLabel?: string;
  savedCount?: number;
  onLogout: () => void;
  demoMode?: boolean;
}

function initials(value: string, fallback: string) {
  const letters = value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toLocaleUpperCase("ru-RU");
  return letters || fallback;
}

function todayLabel() {
  const value = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    weekday: "long",
  }).format(new Date());
  return value.replace(" г.", "").replace(/^./, (letter) => letter.toLocaleUpperCase("ru-RU"));
}

export default function AppShell({
  children,
  userName = "Пользователь",
  companyName = "Компания",
  rolesLabel = "Роль не указана",
  savedCount = 0,
  onLogout,
  demoMode = false,
}: AppShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const savedActive = location.pathname === "/feed" && new URLSearchParams(location.search).get("saved") === "1";

  useEffect(() => {
    if (!menuOpen) return undefined;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  const logout = () => {
    setMenuOpen(false);
    onLogout();
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        К основному содержимому
      </a>
      <header className="app-topbar">
        <Link to="/feed" className="product-brand" aria-label="Альфа Инсайты — обзор событий">
          <span className="product-brand__mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span>Альфа Инсайты</span>
        </Link>
        {demoMode && <DemoBadge className="app-topbar__demo" />}
        <time className="app-topbar__date">{todayLabel()}</time>
        <div className="profile-menu" ref={menuRef}>
          <button
            type="button"
            className="avatar avatar--button"
            aria-label="Открыть меню профиля"
            aria-expanded={menuOpen}
            aria-controls="profile-menu-popover"
            onClick={() => setMenuOpen((open) => !open)}
          >
            {initials(userName, "П")}
          </button>
          {menuOpen && (
            <div className="profile-menu__popover" id="profile-menu-popover">
              <strong>{userName}</strong>
              <span>{rolesLabel}</span>
              <NavLink to="/company" onClick={() => setMenuOpen(false)}>
                Личный кабинет
              </NavLink>
              <button type="button" onClick={logout}>
                <Icon name="logout" size={18} />
                Выйти
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="app-shell__body">
        <aside className="app-sidebar">
          <div className="company-lockup">
            <span className="avatar">{initials(companyName, "АИ")}</span>
            <div>
              <strong>{companyName}</strong>
              <span>{rolesLabel}</span>
            </div>
          </div>
          <nav className="app-nav" aria-label="Основная навигация">
            <NavLink
              to="/feed"
              end
              className={({ isActive }) => `app-nav__link${isActive && !savedActive ? " active" : ""}`}
            >
              <Icon name="home" />
              <span>Обзор событий</span>
            </NavLink>
            <Link to="/feed?saved=1" className={`app-nav__link${savedActive ? " active" : ""}`}>
              <Icon name="bookmark" />
              <span>Сохранённые</span>
              <span className="app-nav__count" aria-label={`${savedCount} сохранённых`}>
                {savedCount}
              </span>
            </Link>
            <NavLink to="/company" className={({ isActive }) => `app-nav__link${isActive ? " active" : ""}`}>
              <Icon name="user" />
              <span>Личный кабинет</span>
            </NavLink>
          </nav>
          <div className="app-sidebar__footer">
            <span>Ваш ракурс</span>
            <strong>{rolesLabel}</strong>
            <NavLink to="/company?tab=roles">Изменить роли</NavLink>
          </div>
        </aside>

        <main id="main-content" className="app-main" tabIndex={-1}>
          {children}
        </main>
      </div>

      <nav className="mobile-nav" aria-label="Мобильная навигация">
        <NavLink
          to="/feed"
          end
          className={({ isActive }) => (isActive && !savedActive ? "active" : "")}
          aria-label="Обзор событий"
        >
          <Icon name="home" />
          <span>События</span>
        </NavLink>
        <Link to="/feed?saved=1" className={savedActive ? "active" : ""} aria-label={`Сохранённые, ${savedCount}`}>
          <span className="mobile-nav__icon">
            <Icon name="bookmark" />
            {savedCount > 0 && <b>{savedCount > 9 ? "9+" : savedCount}</b>}
          </span>
          <span>Сохранённые</span>
        </Link>
        <NavLink to="/company" className={({ isActive }) => (isActive ? "active" : "")} aria-label="Личный кабинет">
          <Icon name="user" />
          <span>Кабинет</span>
        </NavLink>
      </nav>
    </div>
  );
}
