import { useEffect, useRef, useState } from 'react';
import { BankIcon, type BankIconName } from './BankIcons';
import { bankAppUrl, signalAppUrl } from './appLinks';
import alfaLogo from './assets/bank/alfa-logo.svg';
import './styles/bank-home.css';

const unavailable = 'Банковские операции недоступны в демоверсии';
const menuItems: { label: string; icon: BankIconName; group?: boolean }[] = [
  { label: 'Новый платёж', icon: 'plus' },
  { label: 'Лента операций', icon: 'wallet' },
  { label: 'Платежи в работе', icon: 'history' },
  { label: 'Импорт реестров', icon: 'documents' },
  { label: 'Выписка', icon: 'document' },
  { label: 'Счета', icon: 'card' },
  { label: 'Контрагенты', icon: 'people' },
  { label: 'ВЭД', icon: 'globe' },
  { label: 'Зарплатный проект', icon: 'salary' },
  { label: 'Интернет-эквайринг', icon: 'acquiring', group: true },
  { label: 'Кредитные продукты', icon: 'credit' },
  { label: 'Депозиты', icon: 'deposit' },
];
const workItems = [
  ['Оплатить', 0], ['Подписать', 2], ['Отправить', 0], ['Доработать', 0],
  ['Отклонённые', 1], ['Черновики', 3], ['В работе у банка', 1],
] as const;
// Synthetic examples only. No account identifiers, transactions or identity data are copied from the reference.
const operations = [
  { company: 'ООО «Меридиан»', detail: 'Оплата по договору поставки · № 128', date: '22.10.2026', status: 'ИСПОЛНЕНО', amount: '+ 480 000,00', incoming: true },
  { company: 'ООО «Вектор»', detail: 'Комплектующие для производства · № 127', date: '22.10.2026', status: 'ИСПОЛНЕНО', amount: '− 125 000,00', incoming: false },
  { company: 'ООО «Логистика»', detail: 'Услуги доставки · № 126', date: '21.10.2026', status: 'НА ОБРАБОТКЕ', amount: '− 32 500,00', incoming: false },
  { company: 'ООО «Промресурс»', detail: 'Оплата оборудования · № 125', date: '21.10.2026', status: 'ИСПОЛНЕНО', amount: '+ 267 000,00', incoming: true },
];

function SignalMark() {
  return <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M4 15V9m5 11V4m6 13V7m5 7v-4" /></svg>;
}

// Decorative local SVGs, not extracted bank artwork; see BANK_UI_SOURCES.txt.
function PromoArt({ kind }: { kind: 'deposit' | 'acquiring' | 'cashback' }) {
  const red = `bank-art-red-${kind}`, gold = `bank-art-gold-${kind}`, glass = `bank-art-glass-${kind}`;
  return <svg className="bank-promo-art" viewBox="0 0 144 132" fill="none" aria-hidden="true">
    <defs>
      <linearGradient id={red} x1="28" y1="20" x2="110" y2="120" gradientUnits="userSpaceOnUse"><stop stopColor="#ff7769" /><stop offset=".4" stopColor="#ff342a" /><stop offset="1" stopColor="#bc0c2a" /></linearGradient>
      <linearGradient id={gold} x1="52" y1="45" x2="115" y2="118" gradientUnits="userSpaceOnUse"><stop stopColor="#fff7b3" /><stop offset=".45" stopColor="#ffcf5b" /><stop offset="1" stopColor="#e69b24" /></linearGradient>
      <linearGradient id={glass} x1="20" y1="20" x2="104" y2="102" gradientUnits="userSpaceOnUse"><stop stopColor="#f5f4ff" /><stop offset=".5" stopColor="#a3c6fa" /><stop offset="1" stopColor="#72adc3" /></linearGradient>
    </defs>
    {kind === 'deposit' ? <>
      <ellipse cx="83" cy="115" rx="48" ry="8" fill="#5867a4" opacity=".16" />
      <path d="m39 30 16-8 64 14-15 9-65-15Z" fill="#ff9587" /><path d="m104 45 15-9v67l-15 11V45Z" fill="#ac1931" />
      <rect x="35" y="30" width="70" height="83" rx="7" fill={`url(#${red})`} /><rect x="42" y="37" width="55" height="68" rx="4" stroke="#ffaaa0" strokeWidth="2" />
      <circle cx="69" cy="69" r="19" fill="#c7d7e0" /><circle cx="69" cy="69" r="13" fill="#fc4140" stroke="white" strokeWidth="3" /><path d="M69 44v50M44 69h50" stroke="#dfebf2" strokeWidth="4" /><circle cx="69" cy="69" r="6" fill="#e8f1f5" />
      <path d="m98 89 20-24 20 24h-12v28h-16V89H98Z" fill="#8bdc51" stroke="#b8f487" strokeWidth="2" /><path d="m19 83 4 10 10 4-10 4-4 10-4-10-10-4 10-4 4-10Z" fill="#c0ff85" />
    </> : kind === 'acquiring' ? <>
      <ellipse cx="77" cy="116" rx="48" ry="7" fill="#6e8e38" opacity=".15" /><rect x="25" y="20" width="89" height="82" rx="11" fill={`url(#${glass})`} stroke="#eef6ff" strokeWidth="2" />
      <path d="M26 32a11 11 0 0 1 11-11h66a11 11 0 0 1 11 11v9H26V32Z" fill={`url(#${red})`} /><path d="M38 31h.1m11 0h.1m11 0h.1" stroke="#ffeebb" strokeWidth="5" strokeLinecap="round" />
      <circle cx="102" cy="94" r="26" fill={`url(#${gold})`} stroke="#fff2b3" strokeWidth="2" /><circle cx="102" cy="94" r="20" stroke="#e6a035" strokeWidth="2" />
      <rect x="29" y="58" width="49" height="49" rx="11" fill="#15cba9" stroke="#70f3d8" strokeWidth="2" /><path d="M43 82h22M54 71v22" stroke="#e2fff7" strokeWidth="7" />
    </> : <>
      <ellipse cx="78" cy="118" rx="49" ry="6" fill="#338fac" opacity=".16" /><rect x="73" y="26" width="57" height="67" rx="7" fill="#7846ed" stroke="#bc9bff" strokeWidth="2" />
      <path d="m81 74 11-11 10 5 18-26" stroke="#a1ffd2" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="24" y="40" width="56" height="76" rx="10" fill={`url(#${red})`} stroke="#ff9690" strokeWidth="2" /><rect x="32" y="48" width="40" height="20" rx="4" fill="#ffc2b7" />
      {[0,1,2].map(row => [0,1,2].map(col => <rect key={`${row}-${col}`} x={33+col*13} y={77+row*11} width="8" height="6" rx="2" fill="#ffe1da" />))}
      <circle cx="109" cy="103" r="20" fill={`url(#${gold})`} stroke="#fff4b7" strokeWidth="2" /><path d="M103 92v22m-3-18h9a5 5 0 0 1 0 10h-9m0 4h13" stroke="#ecaa32" strokeWidth="3" />
    </>}
  </svg>;
}

export function BankHome() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [toast, setToast] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const menuButton = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const skipLink = useRef<HTMLAnchorElement>(null);
  const brandLink = useRef<HTMLAnchorElement>(null);
  const topTools = useRef<HTMLDivElement>(null);
  const main = useRef<HTMLElement>(null);
  const helpButton = useRef<HTMLButtonElement>(null);
  const toastCloseButton = useRef<HTMLButtonElement>(null);

  useEffect(() => () => clearTimeout(toastTimer.current), []);
  useEffect(() => {
    const targets = [skipLink.current, brandLink.current, topTools.current, main.current, helpButton.current, toastCloseButton.current];
    targets.forEach(element => {
      if (element) (element as HTMLElement & { inert: boolean }).inert = menuOpen;
    });
  }, [menuOpen, toast]);
  useEffect(() => {
    if (!menuOpen) return;
    const narrowScreen = window.matchMedia('(max-width: 1000px)');
    if (!narrowScreen.matches) { setMenuOpen(false); return; }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    sidebar.current?.querySelector<HTMLElement>('button, a')?.focus();
    const keepFocusInMenu = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMenuOpen(false);
        menuButton.current?.focus();
      }
      if (event.key !== 'Tab') return;
      const controls = [menuButton.current, ...Array.from(sidebar.current?.querySelectorAll<HTMLElement>('button, a[href]') ?? [])].filter((item): item is HTMLElement => item !== null);
      const position = controls.indexOf(document.activeElement as HTMLElement);
      const nextPosition = event.shiftKey ? (position <= 0 ? controls.length - 1 : position - 1) : (position + 1) % controls.length;
      event.preventDefault();
      controls[nextPosition]?.focus();
    };
    const closeOnWideScreen = () => {
      if (!narrowScreen.matches) {
        setMenuOpen(false);
        if (document.activeElement === menuButton.current) sidebar.current?.querySelector<HTMLElement>('button, a')?.focus();
      }
    };
    window.addEventListener('keydown', keepFocusInMenu);
    narrowScreen.addEventListener('change', closeOnWideScreen);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', keepFocusInMenu);
      narrowScreen.removeEventListener('change', closeOnWideScreen);
    };
  }, [menuOpen]);

  function notify() {
    clearTimeout(toastTimer.current);
    setToast(true);
    toastTimer.current = setTimeout(() => setToast(false), 4500);
  }
  function closeMenu() { setMenuOpen(false); menuButton.current?.focus(); }

  return <div className="bank-app">
    <a className="bank-skip" href="#bank-main" ref={skipLink}>К содержимому</a>
    <header className="bank-topbar">
      <button className="bank-menu-toggle bank-icon-button" ref={menuButton} onClick={() => menuOpen ? closeMenu() : setMenuOpen(true)} aria-expanded={menuOpen} aria-controls="bank-navigation" aria-label={menuOpen ? 'Закрыть меню' : 'Открыть меню'}>
        {menuOpen ? <BankIcon name="close" /> : <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>}
      </button>
      <a className="bank-brand" href={bankAppUrl} aria-label="Альфа-Бизнес — главная" ref={brandLink}><img src={alfaLogo} width="40" height="40" alt="" /><span>Альфа-Бизнес</span></a>
      <div className="bank-top-tools" ref={topTools}>
        <button className="bank-icon-button bank-top-search" onClick={notify} aria-label="Поиск по банку"><BankIcon name="search" /></button>
        <button className="bank-rewards" onClick={notify} aria-label="Альфа-Выгодно"><span>₽</span></button>
        <button className="bank-icon-button bank-mail" onClick={notify} aria-label="Письма"><BankIcon name="mail" /></button>
        <button className="bank-icon-button bank-notification" onClick={notify} aria-label="Уведомления: 3"><BankIcon name="bell" /><span>3</span></button>
        <button className="bank-identity" onClick={notify} aria-label="Профиль демонстрационной компании"><span className="bank-avatar"><BankIcon name="user" /></span><span><strong>ООО «СЕВЕРНАЯ МАНУФАКТУРА»</strong><small>Морозов А. М.</small></span></button>
        <button className="bank-icon-button bank-logout" onClick={notify} aria-label="Выход из банка"><BankIcon name="logout" /></button>
      </div>
    </header>

    {menuOpen && <button className="bank-menu-shade" onClick={closeMenu} aria-label="Закрыть боковое меню" tabIndex={-1} />}
    <aside className={`bank-sidebar${menuOpen ? ' is-open' : ''}`} id="bank-navigation" ref={sidebar} aria-label="Меню Альфа-Бизнеса">
      <nav aria-label="Навигация Альфа-Бизнеса">
        <button className="bank-nav-item bank-all-services" onClick={notify}><BankIcon name="services" /><span>Все сервисы</span></button>
        <button className="bank-nav-item" onClick={notify}><span className="bank-benefit-icon"><BankIcon name="alfa" /></span><span>Альфа-Выгодно</span></button>
        <a className="bank-nav-item bank-signal-link" href={signalAppUrl} target="_blank" rel="noopener noreferrer" aria-label="Сигнал — откроется в новой вкладке"><SignalMark /><span>Сигнал</span><span className="bank-new-badge" aria-hidden="true">Новое</span></a>
        <div className="bank-nav-divider" />
        {menuItems.map(item => <div key={item.label}>{item.group && <div className="bank-nav-divider" />}<button className={`bank-nav-item${item.group ? ' bank-nav-service' : ''}`} onClick={notify}><BankIcon name={item.icon} /><span>{item.label}</span></button></div>)}
      </nav>
      <button className="bank-nav-item bank-menu-settings" onClick={notify}><BankIcon name="settings" /><span>Настроить меню</span></button>
    </aside>

    <main className="bank-main" id="bank-main" tabIndex={-1} ref={main}>
      <h1 className="bank-sr-only">Главная — Альфа-Бизнес</h1>
      <div className="bank-demo-label"><span />Демонстрационный прототип</div>
      <form className="bank-smart-search" onSubmit={event => { event.preventDefault(); notify(); }}>
        <span className="bank-search-orb" aria-hidden="true">✦</span>
        <input aria-label="Найти операцию" placeholder="Найти операцию или сервис" autoComplete="off" onFocus={notify} />
      </form>
      <div className="bank-quick-actions" aria-label="Быстрые действия">
        <button onClick={notify}><BankIcon name="transfer" />Пополнить счёт</button>
        <button onClick={notify}><BankIcon name="document" />Скачать выписку</button>
        <button onClick={notify}><BankIcon name="receipt" />Создать платёж</button>
        <button onClick={notify}><BankIcon name="documents" />Импорт платежей</button>
        <button className="bank-more" onClick={notify}>Ещё</button>
      </div>

      <div className="bank-dashboard-grid">
        <section className="bank-balance-card" aria-labelledby="bank-balance-title">
          <div className="bank-balance-body">
            <div className="bank-balances">
              <div><h2 id="bank-balance-title">Доступный остаток</h2><button className="bank-amount" onClick={notify}>2 450 000<span>,00 ₽</span></button></div>
              <button className="bank-deposit-pitch" onClick={notify}><span className="bank-pitch-label">ДОХОД ПО ДЕПОЗИТУ</span><strong>4 500 ₽</strong><span>Разместите 500 000 ₽<br />на 1 месяц</span></button>
            </div>
            <div className="bank-accounts">
              <button onClick={notify}><span className="bank-account-icon"><BankIcon name="document" /></span><span>Счета<small>2 счёта в рублях</small></span></button>
              <button onClick={notify}><span className="bank-card-icon"><span><BankIcon name="alfa" /></span></span><span>Business One<small>··0001</small></span></button>
            </div>
          </div>
          <div className="bank-balance-footer"><button onClick={notify}>Реквизиты</button><button onClick={notify}>Тарифы и подписки</button><button className="bank-bonus" onClick={notify}>120<span>А</span></button></div>
        </section>
        <section className="bank-work-card" aria-labelledby="bank-work-title"><h2 id="bank-work-title">Дела в работе</h2><div>{workItems.map(([label, count]) => <button key={label} onClick={notify} className={!count ? 'is-empty' : ''}><span>{label}</span><span className={count ? 'bank-work-count has-items' : 'bank-work-count'}>{count}</span></button>)}</div></section>
        <aside className="bank-promos" aria-label="Предложения банка — демонстрационные примеры">
          <button className="bank-promo bank-promo-deposit" onClick={notify}><span><strong>Депозит</strong><span>Ваши деньги работают круглосуточно</span></span><PromoArt kind="deposit" /></button>
          <button className="bank-promo bank-promo-acquiring" onClick={notify}><span><strong>Интернет-эквайринг</strong><span>Подключите для вашего бизнеса</span></span><PromoArt kind="acquiring" /></button>
          <button className="bank-promo bank-promo-cashback" onClick={notify}><span><strong>100% за ЖКУ</strong><span>Вернём до 100% за платёж</span></span><PromoArt kind="cashback" /></button>
        </aside>
      </div>

      <section className="bank-widgets" aria-label="Виджеты банка">
        <div className="bank-widget-heading"><div className="bank-widget-tabs"><button className="is-active" onClick={notify}>С чего начать</button><button onClick={notify}>Сводка</button><button onClick={notify}>Счета на главной</button></div><div className="bank-widget-tools"><button className="bank-icon-button" onClick={notify} aria-label="Видимость виджетов"><BankIcon name="eye" /></button><button className="bank-icon-button" onClick={notify} aria-label="Настройки виджетов"><BankIcon name="settings" /></button></div></div>
        <div className="bank-onboarding">
          <button className="bank-progress-card" onClick={notify}><strong>Все задания</strong><span className="bank-progress-track"><span /></span><span>3 / 7 выполнено</span></button>
          <button onClick={notify}><BankIcon name="document" /><strong>Оплатить коммунальные услуги</strong></button>
          <button onClick={notify}><BankIcon name="transfer" /><strong>Перевести на свой счёт физлица</strong></button>
          <button onClick={notify}><BankIcon name="receipt" /><strong>Совершить платёж</strong><small>+300 баллов</small></button>
          <button onClick={notify}><BankIcon name="card" /><strong>Изучить тариф</strong><small>+200 баллов</small></button>
        </div>
      </section>

      <section className="bank-feed" aria-labelledby="bank-feed-title">
        <div className="bank-feed-title"><h2 id="bank-feed-title">Лента операций</h2><span>Демонстрационные данные</span></div>
        <div className="bank-feed-search"><button onClick={notify}><span>21–22 октября</span><BankIcon name="calendar" /></button><form onSubmit={event => { event.preventDefault(); notify(); }}><BankIcon name="search" /><input aria-label="Поиск по операциям" placeholder="Контрагент, ИНН, БИК, назначение или номер счёта" onFocus={notify} autoComplete="off" /></form></div>
        <div className="bank-feed-filters"><button onClick={notify} aria-label="Фильтры операций"><BankIcon name="filter" /></button>{['Входящие', 'Исходящие', 'Счёт', 'Контрагент', 'Статус', 'Сумма', 'Тип операции'].map((label, index) => <button key={label} onClick={notify}>{label}{index > 1 && <BankIcon name="chevron" />}</button>)}</div>
        <div className="bank-feed-note">Выберите период и счёт, чтобы увидеть обороты и остатки</div>
        <div className="bank-feed-toolbar"><button onClick={notify}><span className="bank-faux-checkbox" aria-hidden="true" />Показать реестры отдельными платежами</button><div><button onClick={notify}>Настройки</button><button onClick={notify}>Скачать<BankIcon name="chevron" /></button></div></div>
        <div className="bank-table-wrap"><table className="bank-operations"><thead><tr><th>Операция</th><th>Дата</th><th>Статус</th><th>Сумма</th></tr></thead><tbody>{operations.map((operation, index) => <tr key={index}><td><button onClick={notify}><strong>{operation.company}</strong><span>{operation.detail}</span></button></td><td>{operation.date}</td><td><span className={`bank-operation-status${operation.status === 'НА ОБРАБОТКЕ' ? ' is-pending' : ''}`}>{operation.status}</span></td><td className={operation.incoming ? 'bank-incoming' : ''}>{operation.amount}<small> ₽</small></td></tr>)}</tbody></table></div>
      </section>
      <footer className="bank-demo-footer"><span>Демонстрационный прототип для кейса «Сигнал»</span><span>Все компании, суммы и операции вымышлены. Связи с банковским аккаунтом нет.</span></footer>
    </main>
    <button className="bank-help" onClick={notify} aria-label="Помощь" ref={helpButton}><BankIcon name="help" /></button>
    {toast && <div className="bank-toast" role="status"><BankIcon name="help" /><span>{unavailable}</span><button onClick={() => setToast(false)} aria-label="Закрыть уведомление" ref={toastCloseButton}><BankIcon name="close" /></button></div>}
  </div>;
}
