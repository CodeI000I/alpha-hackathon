import { useId, useState, type FormEvent } from 'react';
import { localKey, useStoredState } from '../localState';
import { ActionIcon } from '../signal/components/ActionIcon';
import { Icon } from './Icon';
interface ChatMessage { question: string; answer: string }
export interface DemoChatProps { userId: number; companyId: number | null; itemId?: number; itemTitle: string; roleName: string; compact?: boolean }
const SUGGESTIONS = ['Какие данные нужно проверить?', 'Что обсудить с командой?', 'Как это влияет на мою роль?'];
function preparedAnswer(question: string, title: string, role: string) {
  const normalized = question.toLocaleLowerCase('ru-RU');
  if (normalized.includes('команд')) return 'Обсудите первоисточник с ответственными за процесс, уточните сроки и назначьте следующий шаг. Документы компании не анализировались.';
  if (normalized.includes('роль')) return 'Для роли «' + role + '»: сопоставьте событие с бюджетом, сроками и обязательствами. Это общий подготовленный ответ, а не вывод модели.';
  return 'Проверьте первоисточник «' + title + '», сроки и действующие обязательства. Вопрос не отправлен на сервер; ответ не использует документы компании.';
}
function displayedAnswer(answer: string): string {
  return answer.replace(/^Демо-подсказка для роли /, 'Для роли ').replace(/^Демо-подсказка: (.)/, (_, first: string) => first.toLocaleUpperCase('ru-RU'));
}
export function DemoChat({ userId, companyId, itemId, itemTitle, roleName, compact = false }: DemoChatProps) {
  const id = useId(); const [question, setQuestion] = useState('');
  const [messages, setMessages] = useStoredState<ChatMessage[]>(localKey(userId, 'chat:' + (itemId ?? 'overview:' + roleName), companyId), []);
  const ask = (value: string) => { const clean = value.trim(); if (!clean) return; setMessages(current => [...current.slice(-49), { question: clean, answer: preparedAnswer(clean, itemTitle, roleName) }]); setQuestion(''); };
  const submit = (event: FormEvent) => { event.preventDefault(); ask(question); };
  return <aside className={compact ? 'general-chat' : 'w-chat'} aria-labelledby={id + '-title'}>
    <div className="w-chat-title"><Icon name="spark" /><h2 id={id + '-title'}>{compact ? 'Спросить о новостях' : 'Обсудить событие'}</h2></div>
    <div className="w-chat-body">
      <div className="chat-quick-questions"><span className="chat-quick-label">Быстрые вопросы</span><p className="chat-quick-hint">Нажмите на вопрос, чтобы увидеть пример ответа.</p>{SUGGESTIONS.map(value => <button className="w-prompt" key={value} onClick={() => ask(value)}>{value}<ActionIcon /></button>)}</div>
      <div className={compact ? 'general-history' : 'w-chat-history'} aria-live="polite" aria-relevant="additions">{messages.map((message, index) => <div className="w-message-pair" key={index}><p className="w-message-user">{message.question}</p><p className="w-message-answer">{displayedAnswer(message.answer)}</p></div>)}</div>
    </div>
    <form className="w-chat-form" onSubmit={submit}><label className="sr-only" htmlFor={id}>Вопрос по событию</label><textarea id={id} value={question} onChange={event => setQuestion(event.target.value)} placeholder="Задайте свой вопрос" rows={2} maxLength={1000} /><div className="chat-submit-row"><button className="action-link" type="submit" disabled={!question.trim()}>Отправить <ActionIcon direction="up" /></button></div></form>
    <details className="data-note chat-about"><summary>Об ответах</summary><p>Здесь используются подготовленные ответы, а не аналитика ИИ. Вопросы не отправляются на сервер; история сохраняется только в этом браузере для текущего пользователя и компании.</p></details>
  </aside>;
}
export default DemoChat;
