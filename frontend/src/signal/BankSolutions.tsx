import { useEffect, useRef, useState } from 'react';
import { ActionIcon } from './components/ActionIcon';
import './styles/bank-solutions.css';

export type SolutionId='exchange'|'hedging'|'deposit'|'credit'|'factoring'|'ved';
const solutions:Record<SolutionId,{name:string;prompt:string;action:string;description:string;steps:string[];url:string}>={
 exchange:{name:'Конвертация валют · Alfa FX',prompt:'Если планируете платёж в валюте, сравните условия её покупки.',action:'Посмотреть курс обмена',description:'Сравните условия покупки валюты для расчётов с иностранным партнёром. Курс операции может отличаться от справочного графика.',steps:['Выберите валюту и сумму будущего платежа.','Уточните доступные условия конвертации в банке.','Проведите обмен в банковском сервисе после проверки условий.'],url:'https://alfabank.ru/corporate/ved/conversion/'},
 hedging:{name:'Хеджирование валютного риска',prompt:'Если валютный платёж впереди, обсудите защиту от изменения курса.',action:'Обсудить защиту от курса',description:'Обсудите с банком инструменты управления валютным риском будущих платежей. Подходящий инструмент зависит от сделки, сроков и обязательств компании.',steps:['Подготовьте сумму, валюту и дату расчёта.','Обсудите сценарии изменения курса и условия инструмента.','Согласуйте решение с профильным специалистом банка.'],url:'https://alfabank.ru/corporate/ved/hedging/'},
 deposit:{name:'Депозиты и овернайт',prompt:'Если часть денег временно не нужна для платежей, сравните варианты размещения.',action:'Подобрать размещение',description:'Рассмотрите размещение свободного остатка на подходящий срок. Сначала проверьте, когда деньги понадобятся для платежей компании.',steps:['Определите свободную сумму и ближайшие обязательства.','Сравните сроки и условия размещения.','Уточните доступную ставку и оформите размещение в банке.'],url:'https://alfabank.ru/corporate/deposit-new/'},
 credit:{name:'Овердрафт и кредитная линия',prompt:'Если поставщику нужно заплатить до оплаты от клиентов, рассмотрите финансирование закупки на этот период.',action:'Посмотреть финансирование',description:'Сравните варианты финансирования текущих расходов и закупок. Овердрафт может помочь при краткосрочном разрыве, кредитная линия — при повторяющейся потребности.',steps:['Определите сумму и срок потребности в средствах.','Подготовьте график платежей и поступлений.','Уточните условия и доступность финансирования у банка.'],url:'https://alfabank.ru/corporate/credit/'},
 factoring:{name:'Факторинг',prompt:'Если покупатели платят с отсрочкой, рассмотрите финансирование до поступления оплаты.',action:'Узнать о факторинге',description:'Рассмотрите финансирование поставок с отсрочкой платежа. Банк поможет определить подходящую схему с учётом договоров и ваших покупателей.',steps:['Выберите поставки, по которым ожидаете оплату.','Уточните сроки отсрочки и условия договоров.','Обсудите с банком схему и стоимость финансирования.'],url:'https://alfabank.ru/corporate/credit/factoring/'},
 ved:{name:'Решения для внешней торговли',prompt:'Если условия зарубежной поставки меняются, проверьте варианты расчётов и сопровождения сделки.',action:'Подобрать решение для сделки',description:'Обсудите международные расчёты, валютный контроль и аккредитивы. Состав решения зависит от страны, контрагента и условий контракта.',steps:['Укажите страну, валюту и условия расчётов.','Подготовьте контракт и сроки поставки.','Уточните доступный маршрут расчётов и сопровождение сделки.'],url:'https://alfabank.ru/corporate/'}
};

function OfferCloseIcon(){
 return <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true" focusable="false"><path d="m4 4 8 8M12 4l-8 8"/></svg>;
}

function BankActionLabel({children,external=false}:{children:string;external?:boolean}){
 const lastSpace=children.lastIndexOf(' ');
 return <span className="bank-action-text">{lastSpace>=0&&`${children.slice(0,lastSpace)} `}<span className="bank-action-tail">{children.slice(lastSpace+1)}<ActionIcon direction={external?'external':'forward'}/></span></span>;
}
const defaultStorageKey='signal.bank-solutions.hidden.v1';
function readHidden(storageKey:string):string[]{try{const value:unknown=JSON.parse(localStorage.getItem(storageKey)||'[]');return Array.isArray(value)?value.filter((v):v is string=>typeof v==='string'):[];}catch{return [];}}

export type BankOfferProps={ids:SolutionId[];context:string;scope:string;headingLevel?:2|3;storageKey?:string};
export function BankOffer({ids,context,scope,headingLevel=3,storageKey=defaultStorageKey}:BankOfferProps){
 const OfferHeading=headingLevel===2?'h2':'h3';
 const [hidden,setHidden]=useState<string[]>(()=>readHidden(storageKey)),[selected,setSelected]=useState<SolutionId|null>(null),[amount,setAmount]=useState('1000000'),[days,setDays]=useState('7'),[rate,setRate]=useState('12');
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>setHidden(readHidden(storageKey)),[storageKey]);
 useEffect(()=>{if(selected&&!dialog.current?.open)dialog.current?.showModal();else if(!selected&&dialog.current?.open)dialog.current.close();},[selected]);
 function hide(id:SolutionId){const next=[...new Set([...readHidden(storageKey),`${scope}:${id}`])];setHidden(next);try{localStorage.setItem(storageKey,JSON.stringify(next));}catch{/* Hidden until this component is closed. */}}
 function restore(){const next=readHidden(storageKey).filter(key=>!ids.some(id=>key===`${scope}:${id}`));setHidden(next);try{localStorage.setItem(storageKey,JSON.stringify(next));}catch{/* Keep the visible state. */}}
 const visible=ids.filter(id=>!hidden.includes(`${scope}:${id}`));
 const solution=selected?solutions[selected]:null;
 const valid=Number(amount)>0&&Number(amount)<=1e12&&Number(days)>=1&&Number(days)<=365&&Number(rate)>=0&&Number(rate)<=100&&amount!==''&&days!==''&&rate!=='';
 const income=valid?Number(amount)*Number(rate)/100*Number(days)/365:0;
 return <div className="bank-offers">
  {visible.length>0&&<OfferHeading className="bank-offers-label"><span className="bank-offers-mark" aria-hidden="true">А</span>Демо · предложение от Альфа-Банка</OfferHeading>}
  {visible.map(id=><div className="bank-offer" key={id}>
   <button type="button" className="bank-offer-hide" aria-label={`Скрыть предложение: ${solutions[id].name}`} onClick={()=>hide(id)}><OfferCloseIcon/></button>
   <strong className="bank-offer-name">{solutions[id].name}</strong>
   <p className="bank-offer-copy">{solutions[id].prompt}</p>
   <button type="button" className="bank-offer-action" onClick={()=>setSelected(id)}><BankActionLabel>{solutions[id].action}</BankActionLabel></button>
  </div>)}
  {visible.length<ids.length&&<button type="button" className="bank-restore" onClick={restore}>Показать скрытые предложения</button>}
  <dialog ref={dialog} className="bank-solution-dialog" aria-label={solution?.name??'Предложение от Альфа-Банка'} onCancel={()=>setSelected(null)} onClose={()=>setSelected(null)}>
   <header><div className="bank-offers-label"><span className="bank-offers-mark" aria-hidden="true">А</span>Демо · предложение от Альфа-Банка</div><button type="button" className="bank-solution-close" aria-label="Закрыть решение банка" onClick={()=>setSelected(null)}><OfferCloseIcon/></button></header>
   {solution&&<><h2>{solution.name}</h2><p className="bank-context">Почему здесь: {context}</p><p className="bank-description">{solution.description}</p>{selected==='deposit'&&<section className="deposit-calculator" aria-label="Пример расчёта дохода"><h3>Оцените доход от размещения</h3><div className="deposit-fields"><label>Сумма, ₽<input type="number" min="1" max="1000000000000" value={amount} onChange={e=>setAmount(e.target.value)}/></label><label>Срок, дней<input type="number" min="1" max="365" step="1" value={days} onChange={e=>setDays(e.target.value)}/></label><label>Ставка для примера, %<input type="number" min="0" max="100" step="0.1" value={rate} onChange={e=>setRate(e.target.value)}/></label></div><output aria-live="polite">{valid?`+${income.toLocaleString('ru-RU',{maximumFractionDigits:0})} ₽`:'Проверьте сумму, срок и ставку'}<span>{valid?'условный доход за выбранный срок':'Сумма больше 0, срок 1–365 дней, ставка 0–100%.'}</span></output><p>Ставка задана для примера и не является ставкой банка. Простой расчёт без капитализации; фактические условия уточняются отдельно.</p></section>}<h3 className="bank-steps-heading">Как перейти к решению</h3><ol className="bank-solution-steps">{solution.steps.map((step,i)=><li key={step}><span>{i+1}</span>{step}</li>)}</ol><footer><p>Условия и доступность продукта уточняются на сайте банка. Заявка из прототипа не отправляется.</p><a className="bank-official-link" href={solution.url} target="_blank" rel="noopener noreferrer"><BankActionLabel external>Условия на сайте Альфа-Банка</BankActionLabel></a></footer></>}
  </dialog>
 </div>;
}
