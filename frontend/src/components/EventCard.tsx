import { Link } from 'react-router-dom';
import type { FeedItem } from '../api/types';
import { ActionIcon } from '../signal/components/ActionIcon';
import { dateLabel, KIND_LABELS, relevance, sourceLabel } from '../report';
import { Icon } from './Icon';
export default function EventCard({ item, roleName, saved, onToggleSave, keywords = [] }: { item: FeedItem; roleName: string; saved: boolean; onToggleSave: () => void; keywords?: string[] }) {
  const source = sourceLabel(item);
  const searchable = [item.news.title, item.news.summary, item.insight].join(' ').toLocaleLowerCase('ru-RU');
  const matches = keywords.filter(word => word.trim() && searchable.includes(word.toLocaleLowerCase('ru-RU')));
  return <article className="w-event">
    <div className="w-event-meta"><span className="w-event-origin"><time dateTime={item.news.publishedAt}>{dateLabel(item.news.publishedAt)}</time>{source && <span>{source}</span>}</span><button className={'w-icon ' + (saved ? 'saved' : '')} aria-label={saved ? 'Убрать из закладок' : 'Сохранить в закладки'} aria-pressed={saved} onClick={onToggleSave}><Icon name="bookmark" size={18} /></button></div>
    <h3><Link className="w-title-link" to={'/news/' + item.id}>{item.news.title || 'Без заголовка'}<ActionIcon direction="external" /></Link></h3>
    <p className="w-summary">{item.news.summary || 'Сообщение источника не передано.'}</p>
    <div className="w-impact"><span>Значение для бизнеса · интерпретация</span><p>{item.insight || 'Интерпретация не передана.'}</p></div>
    <div className="w-chips w-event-status"><span className={'w-chip ' + item.kind}>{KIND_LABELS[item.kind] ?? 'Неизвестный тип'}</span><span className="w-chip">{roleName}</span><span className="w-chip">Релевантность {relevance(item.score)}</span></div>
    {!!matches.length && <div className="signal-keyword-matches" aria-label="Совпадения ключевых слов"><span>Ключевые слова</span>{matches.map(word => <mark key={word}>{word}</mark>)}</div>}
    <div className="w-card-foot"><Link className="action-link" to={'/news/' + item.id} aria-label={'Разобрать: ' + item.news.title}>Разобрать <ActionIcon /></Link></div>
  </article>;
}
