import { Link } from "react-router-dom";
import { isDemoMode } from "../api/client";
import { DemoBadge } from "../components/ui";

const valueCards = [
  {
    title: "Что изменится в бюджете?",
    text: "События связываются с денежным потоком, обязательствами и возможными расходами.",
  },
  {
    title: "Где может возникнуть сбой?",
    text: "Лента выделяет влияние на поставки, запасы и сроки исполнения заказов.",
  },
  {
    title: "Какое решение принять?",
    text: "Каждый разбор заканчивается проверяемыми следующими шагами для команды.",
  },
];

const roleCards = [
  {
    image: "/assets/finance.webp",
    eyebrow: "Финансы",
    title: "Контролируйте влияние на бюджет",
    text: "Платежи, стоимость альтернатив и риск кассовых разрывов — в контексте конкретного события.",
  },
  {
    image: "/assets/operations.webp",
    eyebrow: "Операции",
    title: "Замечайте угрозы для процессов",
    text: "Сроки, поставщики и производственный план собраны в одном персональном обзоре.",
  },
  {
    image: "/assets/management.webp",
    eyebrow: "Управление",
    title: "Сверяйте решения между командами",
    text: "Один факт показывается с разных управленческих ракурсов — без потери первоисточника.",
  },
];

export default function LandingPage({ hasSession }: { hasSession: boolean }) {
  const appTarget = hasSession ? "/feed" : "/onboarding";

  return (
    <div className="landing-page">
      <header className="public-header page-width">
        <Link className="brand" to="/" aria-label="Альфа Инсайты — на главную">
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span>Альфа Инсайты</span>
        </Link>
        <nav aria-label="Навигация по странице">
          <a href="#possibilities">Возможности</a>
          <a href="#how-it-works">Как работает</a>
        </nav>
        <div className="public-header__actions">
          {isDemoMode && <DemoBadge>Деморежим</DemoBadge>}
          <Link className="button button--secondary" to={appTarget}>
            {hasSession ? "Открыть сервис" : "Начать"}
          </Link>
        </div>
      </header>

      <main>
        <section className="hero page-width">
          <div className="hero__copy">
            <span className="eyebrow">Персональная новостная аналитика</span>
            <h1>События, которые важны именно вашему бизнесу</h1>
            <p>
              Альфа Инсайты превращают поток новостей в понятные риски, возможности и действия для
              руководителя.
            </p>
            <div className="hero__actions">
              <Link className="button button--primary" to={appTarget}>
                {hasSession ? "Перейти к событиям" : "Настроить ленту"}
              </Link>
              <a className="text-link" href="#how-it-works">
                Посмотреть, как это работает <span aria-hidden="true">↓</span>
              </a>
            </div>
          </div>
          <div className="hero__visual" aria-hidden="true">
            <span className="hero__glow" />
            <img src="/assets/hero-analysis.webp" alt="" width="900" height="900" />
          </div>
        </section>

        <section className="landing-section landing-section--light" id="possibilities">
          <div className="page-width">
            <span className="eyebrow eyebrow--dark">В фокусе руководителя</span>
            <h2>Что важно для вашей компании</h2>
            <div className="value-grid">
              {valueCards.map((card) => (
                <article className="value-card" key={card.title}>
                  <span className="value-card__dot" aria-hidden="true" />
                  <h3>{card.title}</h3>
                  <p>{card.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-section" id="how-it-works">
          <div className="page-width">
            <span className="eyebrow">Как работает сервис</span>
            <h2>От новости до следующего действия</h2>
            <ol className="steps-grid">
              <li>
                <span>01</span>
                <h3>Собирает события</h3>
                <p>Новости и отраслевые источники остаются доступными для проверки.</p>
              </li>
              <li>
                <span>02</span>
                <h3>Учитывает профиль</h3>
                <p>Роль руководителя и контекст компании меняют приоритеты ленты.</p>
              </li>
              <li>
                <span>03</span>
                <h3>Объясняет влияние</h3>
                <p>Риск или возможность переводятся в конкретные вопросы и действия.</p>
              </li>
            </ol>
          </div>
        </section>

        <section className="landing-section landing-section--light">
          <div className="page-width">
            <span className="eyebrow eyebrow--dark">Разные ракурсы</span>
            <h2>Одна лента для всей управленческой команды</h2>
            <div className="role-showcase">
              {roleCards.map((card) => (
                <article className="role-showcase__card" key={card.eyebrow}>
                  <img src={card.image} alt="" width="900" height="900" loading="lazy" />
                  <span className="eyebrow eyebrow--dark">{card.eyebrow}</span>
                  <h3>{card.title}</h3>
                  <p>{card.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-section landing-result">
          <div className="page-width landing-result__inner">
            <div>
              <span className="eyebrow">Результат</span>
              <h2>Вместо ещё одной подборки новостей — рабочий контекст</h2>
              <p>
                В каждой карточке видны источник, релевантность, значение для вашей роли и связанные
                элементы профиля компании.
              </p>
              <Link className="button button--primary" to={appTarget}>
                {hasSession ? "Открыть мою ленту" : "Создать профиль"}
              </Link>
            </div>
            <img src="/assets/result.webp" alt="" width="900" height="900" loading="lazy" />
          </div>
        </section>
      </main>

      <footer className="public-footer page-width">
        <span>Альфа Инсайты</span>
        <p>Прототип сервиса персональной аналитики для бизнеса.</p>
      </footer>
    </div>
  );
}
