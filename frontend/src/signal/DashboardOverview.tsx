import { useEffect, useRef, useState } from 'react';
import { Button } from './components/ui';
import { BankOffer } from './BankSolutions';
import { ActionIcon } from './components/ActionIcon';
import type { SolutionId } from './BankSolutions';
import './styles/overview.css';

type Kind='rate'|'currency'|'events'|'cash'|'payments'|'receivables'|'imports';
type Widget={id:string;kind:Kind;period:string;currency:string};
const defaultStorageKey='signal.dashboard.widgets.v1';
const catalog:{kind:Kind;name:string;category:string;description:string}[]=[
 {kind:'rate',name:'Ключевая ставка',category:'Рынок',description:'Динамика ставки для оценки стоимости финансирования.'},
 {kind:'currency',name:'Курсы валют',category:'Рынок',description:'Рублёвая стоимость доллара, евро или юаня в динамике.'},
 {kind:'events',name:'События за неделю',category:'Сигнал',description:'Интенсивность новостного потока вашей компании.'},
 {kind:'cash',name:'Свободные средства',category:'Компания',description:'Остаток после плановых платежей и возможности размещения.'},
 {kind:'payments',name:'Платежи и поступления',category:'Компания',description:'Баланс денежных потоков и потребность в финансировании.'},
 {kind:'receivables',name:'Ожидаемая оплата',category:'Компания',description:'Поступления от покупателей с отсрочкой платежа.'},
 {kind:'imports',name:'Зарубежные закупки',category:'Компания',description:'План международных платежей и сопровождение сделок.'},
];
const widgetOffers:Record<Kind,{ids:SolutionId[];context:string}>={
 rate:{ids:['deposit'],context:'вы следите за ставкой и условиями размещения свободных средств'},
 currency:{ids:['exchange','hedging'],context:'вы следите за курсом валюты для будущих расчётов'},
 events:{ids:['credit'],context:'в демонстрационной ленте партнёр изменил условия оплаты на предоплату'},
 cash:{ids:['deposit'],context:'демонстрационный платёжный план показывает свободный остаток'},
 payments:{ids:['credit'],context:'в демонстрационном плане выплаты опережают поступления'},
 receivables:{ids:['factoring'],context:'демонстрационные договоры предусматривают оплату с отсрочкой'},
 imports:{ids:['ved'],context:'демонстрационный план включает международные расчёты за комплектующие'}
};
function readWidgets(storageKey:string):Widget[]{try{const raw=localStorage.getItem(storageKey);if(!raw)return [{id:'initial-rate',kind:'rate',period:'6 месяцев',currency:'USD'}];const parsed:unknown=JSON.parse(raw);if(Array.isArray(parsed))return parsed.filter((w):w is Widget=>!!w&&typeof w==='object'&&typeof w.id==='string'&&catalog.some(c=>c.kind===w.kind)&&['1 месяц','6 месяцев','1 год'].includes(w.period)&&['USD','EUR','CNY'].includes(w.currency)).slice(0,12);}catch{/* Use the default when storage is unavailable. */}return [{id:'initial-rate',kind:'rate',period:'6 месяцев',currency:'USD'}];}

function WidgetPlot({widget}:{widget:Widget}) {
 const {kind,period,currency}=widget;
 const [hover,setHover]=useState<number|null>(null);
 const rate=period==='1 месяц'?[17,17,17,16.5,16.5,16.5]:period==='1 год'?[21,21,20,20,19,18,18,17,17,17,16.5,16.5]:[20,19,18,17,17,16.5];
 const fx=currency==='USD'?[91.2,92.8,91.6,94.1,93.2,94.6]:currency==='EUR'?[101.4,102.6,101.8,104.2,103.1,104.8]:[12.8,13.1,12.9,13.3,13.2,13.4];
 const corporate=kind==='cash'||kind==='payments'||kind==='receivables'||kind==='imports';
 const corporateBase=kind==='cash'?[6.5,8.2,7.1,10.4,9.6,8.2]:kind==='payments'?[3.2,2.4,1.1,-1.8,-2.4,1.6]:kind==='receivables'?[8.5,10.2,11.6,9.8,13.2,12.4]:[2.2,3.6,2.8,4.2,3.4,4.8];
 const values=kind==='rate'?rate:kind==='events'?[3,5,4,8,6,9,7]:corporate?(period==='1 год'?[...corporateBase.map(v=>v*.8),...corporateBase]:period==='1 месяц'?corporateBase.map(v=>v*.9):corporateBase):period==='1 год'?[...fx.map(v=>v*.94),...fx]:period==='1 месяц'?fx.map((v,i)=>v+(i<3?.3:0)):fx;
 const labels=kind==='events'?['Пн','Вт','Ср','Чт','Пт','Сб','Вс']:period==='1 месяц'?['1 окт','5 окт','9 окт','13 окт','17 окт','21 окт']:period==='1 год'?['Ноя','Дек','Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт']:['Май','Июн','Июл','Авг','Сен','Окт'];
 const min=Math.floor(Math.min(...values)*.95),max=Math.ceil(Math.max(...values)*1.03),x=(i:number)=>8+i*226/(values.length-1),y=(v:number)=>119-(v-min)/(max-min)*85;
 const path=values.map((v,i)=>i===0?`M ${x(i)} ${y(v)}`:kind==='rate'?`H ${x(i)} V ${y(v)}`:`L ${x(i)} ${y(v)}`).join(' ');
 const unit=kind==='rate'?'%':kind==='currency'?' ₽':corporate?' млн ₽':'';
 const value=values[hover??values.length-1];
 const title=kind==='currency'?`${currency} / RUB`:catalog.find(c=>c.kind===kind)?.name;
 return <div className="widget-plot"><h3>{title}</h3><div className="widget-number">{kind==='events'&&hover===null?42:value.toLocaleString('ru-RU',{maximumFractionDigits:2})}{unit}<span>{hover===null?(kind==='events'?'всего за неделю':'на конец периода'):labels[hover]}</span></div><svg viewBox="0 0 280 150" role="img" aria-label={`${title}. Демонстрационные данные. ${labels.map((l,i)=>`${l}: ${values[i]}${unit}`).join('; ')}`} onMouseLeave={()=>setHover(null)}>
 {[min,(min+max)/2,max].map(v=><g key={v}><line x1="8" x2="234" y1={y(v)} y2={y(v)} stroke="#ffffff12"/><text x="242" y={y(v)+4}>{v.toLocaleString('ru-RU',{maximumFractionDigits:1})}</text></g>)}
 {kind==='events'?values.map((v,i)=><rect key={i} x={x(i)-6} y={y(v)} width="12" height={124-y(v)} rx="3" fill="#2288fa"/>):<><path d={`${path} L 234 124 L 8 124 Z`} fill="#2288fa" fillOpacity=".07"/><path d={path} fill="none" stroke="#2288fa" strokeWidth="2.5" strokeLinejoin="round"/></>}
 {values.map((v,i)=><g key={i} tabIndex={0} className="widget-point" onFocus={()=>setHover(i)} onBlur={()=>setHover(null)} onMouseEnter={()=>setHover(i)} aria-label={`${labels[i]}: ${v}${unit}`}><rect x={x(i)-10} y="15" width="20" height="112" fill="transparent"/><circle cx={x(i)} cy={y(v)} r={hover===i?4:0} fill="#9acbff"/><title>{labels[i]}: {v}{unit}</title></g>)}<text x="8" y="146">{labels[0]}</text><text x="234" y="146" textAnchor="end">{labels[labels.length-1]}</text></svg></div>;
}

export type WidgetBoardProps={storageKey?:string};
export function WidgetBoard({storageKey=defaultStorageKey}:WidgetBoardProps){
 const [widgets,setWidgets]=useState<Widget[]>(()=>readWidgets(storageKey)),[open,setOpen]=useState(false),[selection,setSelection]=useState<Kind|null>(null),[period,setPeriod]=useState('6 месяцев'),[currency,setCurrency]=useState('USD'),[category,setCategory]=useState('Все'),[search,setSearch]=useState(''),[notice,setNotice]=useState('');
 const dialog=useRef<HTMLDialogElement>(null);
 const activeStorageKey=useRef(storageKey);
 useEffect(()=>{if(activeStorageKey.current!==storageKey){activeStorageKey.current=storageKey;setWidgets(readWidgets(storageKey));return;}try{localStorage.setItem(storageKey,JSON.stringify(widgets));}catch{setNotice('Настройки доступны только до закрытия страницы.');}},[storageKey,widgets]);
 useEffect(()=>{if(open&&!dialog.current?.open)dialog.current?.showModal();else if(!open&&dialog.current?.open)dialog.current.close();},[open]);
 function launch(){setSelection(null);setSearch('');setCategory('Все');setOpen(true);}
 function choose(kind:Kind){setSelection(kind);setPeriod('6 месяцев');setCurrency('USD');}
 function move(index:number,direction:number){setWidgets(old=>{const next=[...old];[next[index],next[index+direction]]=[next[index+direction],next[index]];return next;});}
 function add(){if(!selection)return;setWidgets(old=>[...old,{id:crypto.randomUUID(),kind:selection,period,currency}]);setOpen(false);setNotice('Виджет добавлен на главный экран');}
 const selected=catalog.find(c=>c.kind===selection);
 const draft:Widget={id:'preview',kind:selection??'rate',period,currency};
 const choices=catalog.filter(c=>(category==='Все'||c.category===category)&&`${c.name} ${c.description}`.toLowerCase().includes(search.toLowerCase()));
 return <section className="widget-board" aria-labelledby="widgets-heading"><div className="widget-board-heading"><h2 id="widgets-heading">Мои виджеты</h2><span className="widget-count" aria-label={`Виджетов: ${widgets.length}`}>{widgets.length}</span><button className="widget-add-icon" onClick={launch} disabled={widgets.length>=12} aria-label="Добавить виджет" title="Добавить виджет"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14 M5 12h14"/></svg></button></div>
 {widgets.map((w,i)=><article className="market-widget" key={w.id}><div className="widget-meta"><span>{catalog.find(c=>c.kind===w.kind)?.category} · демо</span><details className="widget-menu"><summary aria-label={`Настройки виджета ${catalog.find(c=>c.kind===w.kind)?.name}`}>···</summary><div><button disabled={i===0} onClick={()=>move(i,-1)}>Поднять выше ↑</button><button disabled={i===widgets.length-1} onClick={()=>move(i,1)}>Опустить ниже ↓</button><button onClick={()=>{setWidgets(old=>old.filter(item=>item.id!==w.id));setNotice('Виджет удалён');}}>Удалить виджет</button></div></details></div><WidgetPlot widget={w}/>{w.kind!=='events'&&<select className="widget-period" aria-label={`Период: ${catalog.find(c=>c.kind===w.kind)?.name}`} value={w.period} onChange={e=>setWidgets(old=>old.map(item=>item.id===w.id?{...item,period:e.target.value}:item))}><option>1 месяц</option><option>6 месяцев</option><option>1 год</option></select>}<p className="widget-footnote">{w.kind==='events'?'Новостной поток компании':'Иллюстративные данные · не прогноз'}</p><BankOffer ids={widgetOffers[w.kind].ids} context={widgetOffers[w.kind].context} scope={"widget-"+w.id} storageKey={`${storageKey}.offers`}/></article>)}
 {!widgets.length&&<div className="widget-empty"><strong>Соберите свой обзор</strong><p>Добавьте показатели, за которыми следите каждый день.</p></div>}
<p className="widget-status" role="status">{notice}</p>
 <dialog className="widget-dialog" ref={dialog} onCancel={()=>setOpen(false)} onClose={()=>setOpen(false)} onClick={e=>{if(e.target===e.currentTarget){const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)setOpen(false);}}} aria-labelledby="widget-dialog-title">
 <header className="widget-dialog-header"><div><span className="daily-kicker">Ваш рабочий экран</span><h2 id="widget-dialog-title">{selection?'Настроить виджет':'Добавить виджет'}</h2></div><button className="w-icon" aria-label="Закрыть каталог виджетов" onClick={()=>setOpen(false)}>✕</button></header>
 {!selection?<><p className="widget-dialog-intro">Всё, за чем вы следите, — рядом с новостями компании.</p><input className="widget-search" aria-label="Поиск виджетов" placeholder="Найти показатель или график" value={search} onChange={e=>setSearch(e.target.value)}/><div className="widget-categories">{['Все','Рынок','Компания','Сигнал'].map(c=><button key={c} aria-pressed={category===c} className={category===c?'active':''} onClick={()=>setCategory(c)}>{c}</button>)}</div><div className="widget-catalog">{choices.map(c=><button className="widget-catalog-card" key={c.kind} onClick={()=>choose(c.kind)}><span>{c.category}</span><svg viewBox="0 0 200 48" aria-hidden="true"><path d={c.kind==='rate'?'M0 8 H40 V15 H85 V26 H130 V30 H165 V40 H200':c.kind==='currency'?'M0 38 L28 29 L55 34 L85 13 L115 22 L145 10 L172 17 L200 4':'M10 45 V30 M40 45 V17 M70 45 V26 M100 45 V4 M130 45 V13 M160 45 V7 M190 45 V20'} fill="none" stroke="#2288fa" strokeWidth={c.kind==='events'?12:2}/></svg><h3>{c.name}</h3><p>{c.description}</p><div>{widgets.filter(w=>w.kind===c.kind).length?`На экране: ${widgets.filter(w=>w.kind===c.kind).length}`:'Предпросмотр и настройки'}<ActionIcon direction="forward"/></div></button>)}</div>{!choices.length&&<div className="widget-empty"><strong>Ничего не найдено</strong><p>Попробуйте «ставка», «валюты» или другую категорию.</p><button className="w-text-btn" onClick={()=>{setSearch('');setCategory('Все');}}>Сбросить поиск</button></div>}<p className="widget-demo-note">Каталог прототипа. Рыночные показатели вымышлены и не являются аналитикой Альфа-Банка.</p></>:<><button className="widget-back action-back" onClick={()=>setSelection(null)}><ActionIcon direction="back"/>Все виджеты</button><div className="widget-config"><div className="widget-preview"><span>Так будет на вашем экране</span><div className="market-widget"><div className="widget-meta">{selected?.category} · демо</div><WidgetPlot widget={draft}/><p className="widget-footnote">Иллюстративные данные · не прогноз</p></div></div><div className="widget-settings"><h3>{selected?.name}</h3><p>{selected?.description}</p>{selection==='currency'&&<label>Валютная пара<select value={currency} onChange={e=>setCurrency(e.target.value)}><option value="USD">Доллар / рубль</option><option value="EUR">Евро / рубль</option><option value="CNY">Юань / рубль</option></select></label>}<label>Период графика<select disabled={selection==='events'} value={selection==='events'?'1 неделя':period} onChange={e=>setPeriod(e.target.value)}>{selection==='events'?<option>1 неделя</option>:<><option>1 месяц</option><option>6 месяцев</option><option>1 год</option></>}</select></label><p className="widget-demo-note">{selection==='events'?'Демонстрационный новостной поток.':'Вымышленный ряд для предпросмотра. Подключение данных банка не требуется.'}</p></div></div><footer className="widget-dialog-footer"><button className="widget-back" onClick={()=>setOpen(false)}>Отмена</button><Button onClick={add}>Добавить на главный экран</Button></footer></>}
 </dialog></section>;
}
