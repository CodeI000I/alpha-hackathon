import { useState } from "react";
import type { FormEvent } from "react";
import { Icon } from "./Icon";
import { DemoBadge } from "./ui";

interface ChatMessage {
  question: string;
  answer: string;
}

type ChatHistory = Record<string, ChatMessage[]>;

export interface DemoChatProps {
  itemTitle: string;
  roleName: string;
  compact?: boolean;
}

const STORAGE_KEY = "alpha-insights:demo-chat";

function readHistory(): ChatHistory {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const value: unknown = JSON.parse(raw);
    return value && typeof value === "object" ? (value as ChatHistory) : {};
  } catch {
    return {};
  }
}

function saveHistory(history: ChatHistory) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
  } catch {
    // Чат остаётся доступен в текущей вкладке, даже если localStorage заблокирован.
  }
}

function preparedAnswer(question: string, itemTitle: string, roleName: string) {
  const normalized = question.toLocaleLowerCase("ru-RU");
  if (normalized.includes("данн") || normalized.includes("провер")) {
    return `Для события «${itemTitle}» проверьте сроки, суммы, действующие обязательства и источник новости. Затем сопоставьте их с данными вашей компании.`;
  }
  if (normalized.includes("команд") || normalized.includes("обсуд")) {
    return `Соберите ответственных за затронутый процесс, зафиксируйте ближайший срок решения и назначьте владельца следующего шага. Для роли «${roleName}» начните с показателей, которыми вы управляете.`;
  }
  if (normalized.includes("роль") || normalized.includes("влиян")) {
    return `С точки зрения роли «${roleName}» оцените прямое влияние на сроки, бюджет и обязательства. Этот демо-ответ не использует внутренние документы компании.`;
  }
  return `Начните с проверки первоисточника события «${itemTitle}» и подтвердите факты у владельца процесса. Это подготовленный демо-ответ без подключения аналитической модели.`;
}

const SUGGESTIONS = ["Какие данные нужно проверить?", "Что обсудить с командой?", "Как это влияет на мою роль?"];

export function DemoChat({ itemTitle, roleName, compact = false }: DemoChatProps) {
  const contextKey = itemTitle || "Общий чат";
  const [history, setHistory] = useState<ChatHistory>(readHistory);
  const [question, setQuestion] = useState("");
  const messages = history[contextKey] ?? [];

  const ask = (value: string) => {
    const cleanQuestion = value.trim();
    if (!cleanQuestion) return;
    const message = { question: cleanQuestion, answer: preparedAnswer(cleanQuestion, itemTitle, roleName) };
    setHistory((current) => {
      const next = { ...current, [contextKey]: [...(current[contextKey] ?? []), message] };
      saveHistory(next);
      return next;
    });
    setQuestion("");
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    ask(question);
  };

  return (
    <aside className={`demo-chat${compact ? " demo-chat--compact" : ""}`} aria-labelledby="demo-chat-title">
      <div className="demo-chat__header">
        <span className="demo-chat__spark" aria-hidden="true">
          <Icon name="spark" size={18} />
        </span>
        <div>
          <h2 id="demo-chat-title">Обсудить событие</h2>
          <span>Подготовленные ответы</span>
        </div>
        <DemoBadge />
      </div>
      <div className="demo-chat__body">
        <p className="demo-chat__notice">
          Чат работает локально. Вопросы не отправляются на сервер и не анализируются моделью.
        </p>
        <div className="demo-chat__suggestions" aria-label="Примеры вопросов">
          {SUGGESTIONS.map((suggestion) => (
            <button type="button" key={suggestion} onClick={() => ask(suggestion)}>
              {suggestion}
              <Icon name="arrow-right" size={16} />
            </button>
          ))}
        </div>
        {messages.length > 0 && (
          <div className="demo-chat__history" aria-live="polite">
            {messages.map((message, index) => (
              <div className="demo-chat__message" key={`${message.question}-${index}`}>
                <p className="demo-chat__question">{message.question}</p>
                <p className="demo-chat__answer">{message.answer}</p>
              </div>
            ))}
          </div>
        )}
      </div>
      <form className="demo-chat__form" onSubmit={submit}>
        <label className="sr-only" htmlFor="demo-chat-question">
          Вопрос по событию
        </label>
        <textarea
          id="demo-chat-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Задайте вопрос по событию"
          rows={2}
          maxLength={1000}
        />
        <button type="submit" aria-label="Отправить вопрос" disabled={!question.trim()}>
          <Icon name="send" size={17} />
        </button>
      </form>
    </aside>
  );
}

export default DemoChat;
