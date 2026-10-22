import type { MouseEvent } from 'react';
import { Button, Tag } from './components/ui';

const roleCards = [
  { role: 'finance', title: 'Что изменится в бюджете?', text: 'Обязательства, денежный поток и возможные дополнительные расходы.', tags: ['Платежи', 'Затраты'] },
  { role: 'operations', title: 'Где может возникнуть сбой?', text: 'Поставки, запасы и сроки исполнения заказов.', tags: ['Поставщики', 'Производство'] },
  { role: 'executive', title: 'Какое решение нужно принять?', text: 'Влияние на бизнес, варианты действий и ответственность команды.', tags: ['Приоритеты', 'Решения'] },
] as const;

const steps = [
  ['Задать контекст', 'Компания, ваша роль и зона ответственности.'],
  ['Выделить событие', 'Увидеть сигнал, который может затронуть бизнес.'],
  ['Проверить основания', 'Отделить сообщение источника от предположений.'],
  ['Подготовить действие', 'Сохранить итог и определить следующий шаг.'],
] as const;

const asset = (name: string) => `${import.meta.env.BASE_URL}assets/${name}.webp`;

function scrollToSection(event: MouseEvent<HTMLAnchorElement>) {
  const id = event.currentTarget.hash.slice(1);
  const target = id ? document.getElementById(id) : null;
  if (!target) return;
  event.preventDefault();
  target.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
}

function Brand({ productName }: { productName: string }) {
  return <a className="brand" href="#top" onClick={scrollToSection} aria-label={`${productName} — в начало`}><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>{productName}<span className="brand-dot">.</span></a>;
}

export type LandingProps = {
  hasSession: boolean;
  goToRegister: () => void;
  goToDashboard: () => void;
  productName?: string;
  demoMode?: boolean;
};

export function Landing({
  hasSession,
  goToRegister,
  goToDashboard,
  productName = 'Сигнал',
  demoMode = false,
}: LandingProps) {
  const openApp = hasSession ? goToDashboard : goToRegister;

  return <div id="top" className="landing-v3">
    <a className="skip-link" href="#main">К содержанию</a>
    <header className="header shell">
      <Brand productName={productName} />
      <nav aria-label="Основная навигация"><a href="#value" onClick={scrollToSection}>Возможности</a><a href="#how" onClick={scrollToSection}>Как работает</a><a href="#demo" onClick={scrollToSection}>Результат</a></nav>
      <Button variant="secondary" onClick={openApp}>{hasSession ? 'Открыть сервис' : 'Начать'}</Button>
    </header>
    <main id="main">
      <section className="hero shell" aria-labelledby="hero-title">
        <div className="hero-content"><h1 id="hero-title">Аналитика событий<br />для вашего бизнеса</h1><p className="hero-lead">Новости, их влияние на компанию<br className="desktop-break" /> и действия для руководителя</p><Button onClick={openApp}>{hasSession ? 'Перейти к событиям' : 'Перейти в сервис'}</Button></div>
        <div className="hero-art"><img src={asset('hero-analysis-v2')} width="1024" height="1024" alt="Объёмная лупа и отчёт с графиком" /></div>
      </section>

      <section className="section theme-light" id="value" aria-labelledby="value-title"><div className="shell"><h2 id="value-title">Что важно для вашей компании</h2><div className="role-grid">{roleCards.map(card => <article className="role-card" key={card.role}><h3>{card.title}</h3><p>{card.text}</p><div className="tags">{card.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}</div><img className="role-art" src={asset(`${card.role === 'executive' ? 'management' : card.role}-v2`)} width="160" height="160" alt="" loading="lazy" /></article>)}</div></div></section>

      <section className="section theme-light theme-soft" id="how" aria-labelledby="how-title"><div className="shell"><h2 id="how-title">Как работает сервис</h2><ol className="steps">{steps.map(([title, text], index) => <li key={title}><span className="step-number">{index + 1}</span><h3>{title}</h3><p>{text}</p></li>)}</ol></div></section>

      <section className="section demo-section" id="demo" aria-labelledby="demo-title"><div className="shell demo-grid"><div className="demo-intro"><h2 id="demo-title">Персональный обзор бизнеса</h2><p className="demo-lead">Роль и контекст компании меняют приоритеты, объяснение влияния и следующие шаги.</p><div className="demo-note"><span className="note-mark" aria-hidden="true">↗</span><h3>{hasSession ? 'Ваш профиль готов' : 'Начните с профиля компании'}</h3><p>{hasSession ? 'Откройте ленту, чтобы посмотреть актуальные события и разборы.' : 'Укажите компанию и выберите роли. Доступные роли загружаются из сервиса.'}</p><Button onClick={openApp}>{hasSession ? 'Открыть ленту' : 'Создать профиль'}</Button></div></div>
        <article className="profile-form" aria-label="Демонстрационный пример результата"><div className="form-heading"><h3>Что вы получите</h3><Tag>{demoMode ? 'Деморежим' : 'Пример'}</Tag></div><div className="analysis-group"><h4>События по вашей роли</h4><p>Риски и возможности отсортированы по релевантности для компании.</p></div><div className="analysis-group"><h4>Проверяемые основания</h4><p>Источник остаётся рядом с объяснением, а неподтверждённые сведения не подменяют факты.</p></div><div className="analysis-group"><h4>Следующее действие</h4><p>Разбор помогает перейти от новости к вопросу, который стоит проверить команде.</p></div></article>
      </div></section>

      <section className="section theme-light" aria-labelledby="result-title"><div className="shell"><h2 id="result-title">От события к действию</h2><div className="result-layout"><article className="event-panel"><h3>Поставщик переносит отгрузку комплектующих</h3><p>Источник сообщает о переносе ближайшей партии. Сервис сохраняет исходное сообщение и показывает его значение в контексте компании.</p><div className="event-actions"><Tag>Демонстрационный пример</Tag></div></article><article className="empty-result"><div className="empty-copy"><h3>Что это значит<br />для вашей компании?</h3><p>Создайте профиль, чтобы увидеть последствия и возможные действия.</p><Button variant="secondary" onClick={openApp}>{hasSession ? 'Открыть мою ленту' : 'Задать контекст'}</Button></div><img src={asset('result-v2')} width="260" height="260" alt="Объёмная папка с готовым отчётом" loading="lazy" /></article></div></div></section>
    </main>
    <footer className="footer theme-light"><div className="shell footer-inner"><Brand productName={productName} /><p>Прототип команды · Альфа-хакатон 2026</p></div></footer>
  </div>;
}

export default Landing;
