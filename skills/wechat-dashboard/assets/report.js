const input=document.getElementById('search');
const status=document.getElementById('result');
const monthButton=document.getElementById('toggle-months');
const monthButtonIcon=monthButton.querySelector('svg')?.cloneNode(true);
const monthDetails=[...document.querySelectorAll('.month-card')];
function search(){
  const terms=input.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  let matches=0, visibleSections=0;
  document.querySelectorAll('main > .report, main .month-report').forEach(section=>{
    let visible=0;
    section.querySelectorAll('.piece').forEach(piece=>{
      if(piece.classList.contains('month-card')) return;
      const text=piece.textContent.toLocaleLowerCase();
      const found=!terms.length||terms.every(term=>text.includes(term));
      piece.hidden=!found;
      if(found){
        visible++;matches++;
        const parentDetails=piece.closest('details');
        if(terms.length&&parentDetails) parentDetails.open=true;
      }
    });
    const ownText=section.classList.contains('month-report')
      ? section.querySelector('.month-content')?.textContent.toLocaleLowerCase() || '' : '';
    const ownMatch=terms.length && section.classList.contains('month-report') && terms.every(term=>ownText.includes(term));
    if(ownMatch){ visible++; matches++; section.querySelector('.month-card').open=true; }
    section.hidden=!!terms.length&&!visible;
    if(!section.hidden) visibleSections++;
  });
  if(!terms.length){
    monthDetails.forEach(detail=>detail.open=false);
    document.querySelectorAll('.graphics-fold').forEach(detail=>detail.open=false);
    document.querySelectorAll('.chapter').forEach(detail=>detail.open=false);
    status.textContent='共 '+monthDetails.length+' 个月度详析，按需展开。';
  } else {
    status.textContent='找到 '+matches+' 处相关内容；相关月报已展开。';
  }
  setMonthButtonLabel(monthDetails.length>0&&monthDetails.every(detail=>detail.open));
}
input.addEventListener('input',search);
document.getElementById('reset').addEventListener('click',()=>{input.value='';search();});
monthButton.addEventListener('click',()=>{
  const open=monthDetails.some(detail=>!detail.open);
  monthDetails.forEach(detail=>detail.open=open);
  setMonthButtonLabel(open);
});
document.querySelectorAll('.month-chip, nav a[href^="#report-"]').forEach(link=>link.addEventListener('click',()=>{
  const target=document.querySelector(link.getAttribute('href'));
  target?.querySelector('.month-card')?.setAttribute('open','');
}));
status.textContent='共 '+monthDetails.length+' 个月度详析，按需展开。';

// Navigation and graphics enhance the same full report; they add no conclusions.
let selectedYear='all';
function applyYear(year){
 selectedYear=year;
 document.querySelectorAll('.year-filters button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.year===year)));
 document.querySelectorAll('.year-group').forEach(g=>g.classList.toggle('is-filtered-out',year!=='all'&&g.querySelector('h2 span').textContent!==year));
 document.querySelectorAll('.period-track .month-chip').forEach(a=>a.classList.toggle('is-filtered-out',year!=='all'&&!a.dataset.period.startsWith(year)));
 document.querySelectorAll('.activity-bar').forEach(g=>g.classList.toggle('is-dimmed',year!=='all'&&!g.dataset.period.startsWith(year)));
}
document.querySelectorAll('.year-filters button').forEach(b=>b.addEventListener('click',()=>applyYear(b.dataset.year)));
document.querySelectorAll('.period-track .month-chip').forEach(a=>{
 const label=a.querySelector('span');label.textContent=a.dataset.period.slice(5);a.querySelector('small').textContent=a.dataset.period.slice(0,4);
});
function openMonth(period){
 const target=[...document.querySelectorAll('.month-report')].find(s=>s.dataset.period===period);
 if(!target)return;
 if(input.value){input.value='';search();}
 applyYear('all');
 target.hidden=false;target.querySelector('.month-card').open=true;
 document.querySelectorAll('[data-period]').forEach(el=>el.classList.toggle('is-selected',el.dataset.period===period));
 document.querySelector('.period-selection').textContent='已选择 '+period+'，下方月报已展开';
 target.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
}
document.querySelectorAll('.month-chip').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();openMonth(a.dataset.period);}));
document.querySelectorAll('.activity-bar').forEach(g=>{
 const readout=g.closest('.visual-panel').querySelector('.chart-readout');
 function describe(){readout.textContent=g.dataset.period+' · '+Number(g.dataset.count).toLocaleString()+' 条消息 · 点击打开月报';}
 g.addEventListener('pointerenter',describe);g.addEventListener('focus',describe);
 g.addEventListener('click',()=>openMonth(g.dataset.period));
 g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openMonth(g.dataset.period);}});
});
function selectChart(view){
 document.querySelectorAll('.chart-tabs button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));
 document.querySelectorAll('[data-panel]').forEach(p=>p.classList.toggle('is-inactive',p.dataset.panel!==view));
}
document.querySelectorAll('.chart-tabs button').forEach(b=>b.addEventListener('click',()=>selectChart(b.dataset.view)));
const firstChart=document.querySelector('.chart-tabs button');if(firstChart)selectChart(firstChart.dataset.view);
input.addEventListener('input',()=>{document.body.classList.toggle('searching',!!input.value.trim());if(input.value.trim())applyYear('all');});
document.getElementById('reset').addEventListener('click',()=>document.body.classList.remove('searching'));
function setMonthButtonLabel(open){
 monthButton.textContent=open?'收起全部月份':'展开全部月份';if(monthButtonIcon)monthButton.prepend(monthButtonIcon.cloneNode(true));
}
monthDetails.forEach(d=>d.addEventListener('toggle',()=>setMonthButtonLabel(monthDetails.length>0&&monthDetails.every(x=>x.open))));
const progress=document.querySelector('.reading-progress span');const topButton=document.querySelector('.back-to-top');
let scheduled=false;
function updateProgress(){scheduled=false;const max=document.documentElement.scrollHeight-innerHeight;progress.style.width=(max>0?Math.min(100,Math.max(0,scrollY/max*100)):0)+'%';topButton.classList.toggle('is-visible',scrollY>600);}
window.addEventListener('scroll',()=>{if(!scheduled){scheduled=true;requestAnimationFrame(updateProgress);}},{passive:true});
window.addEventListener('resize',updateProgress);updateProgress();
topButton.addEventListener('click',()=>window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}));

// Give each integrated topic its own reading controls and source-linked time map.
document.querySelectorAll('.integrated-report > .chapter').forEach((chapter,index)=>{
 const body=chapter.querySelector('.chapter-body');
 const title=chapter.querySelector('.chapter-title').textContent;
 const firstText=body.querySelector('.reading-chunk')?.textContent.trim()||'';
 if(firstText){
  const preview=document.createElement('span');preview.className='chapter-preview';preview.textContent=firstText;
  chapter.querySelector('summary').append(preview);
 }
 const tools=document.createElement('div');tools.className='chapter-reader-tools';
 const caption=document.createElement('span');caption.textContent='主题 '+String(index+1).padStart(2,'0')+' · 分段阅读';tools.append(caption);
 const button=document.createElement('button');button.type='button';button.textContent='连续阅读';button.setAttribute('aria-pressed','false');
 button.addEventListener('click',()=>{const continuous=chapter.classList.toggle('continuous-reading');button.textContent=continuous?'分段阅读':'连续阅读';button.setAttribute('aria-pressed',String(continuous));});tools.append(button);
 body.prepend(tools);
 const periods=[...new Set([...body.textContent.matchAll(/\[20\d{2}-\d{2}[^\]]*\]/g)].flatMap(m=>m[0].match(/20\d{2}-\d{2}/g)||[]))].sort();
 const existingMonths=new Set([...document.querySelectorAll('.month-report')].map(s=>s.dataset.period));
 const knownPeriods=periods.filter(period=>existingMonths.has(period));
 if(knownPeriods.length){
  const map=document.createElement('div');map.className='chapter-source-map';
  const label=document.createElement('small');label.textContent='本节引用月份 · 点击回看月报';map.append(label);
  const track=document.createElement('div');track.className='chapter-source-track';
  knownPeriods.forEach(period=>{const b=document.createElement('button');b.type='button';b.textContent=period;b.addEventListener('click',()=>openMonth(period));track.append(b);});map.append(track);tools.after(map);
 }
 let view=null;
 if(/性格|人格|MBTI|兴趣|偏好|喜好|互动模式/.test(title))view='compare';
 else if(/人际|关系网络|社会关系/.test(title))view='relationships';
 else if(/日期|相识|认识|工作|学习|学业|阶段|跨期变化/.test(title))view='timeline';
 const panels=view?[...document.querySelectorAll('.graphic-report [data-panel="'+view+'"]')]:[];
 const personalityTopic=/性格|人格|MBTI/.test(title);
 const original=panels.find(panel=>personalityTopic===/性格|人格|MBTI/.test(panel.querySelector('h3')?.textContent||''))||panels[0];
 if(original){
  const graphic=document.createElement('details');graphic.className='topic-graphic';
  const summary=document.createElement('summary');summary.textContent='展开全历史'+(personalityTopic?'性格画像':({compare:'偏好对照',relationships:'人际关系图',timeline:'时间图'})[view])+'，与本节对照';graphic.append(summary);
  const clone=original.cloneNode(true);clone.removeAttribute('data-panel');clone.classList.remove('is-inactive','piece');clone.hidden=false;
  // Date-range, relationship and comparison panels contain no generated IDs.
  clone.querySelectorAll('[id]').forEach(el=>el.removeAttribute('id'));
  graphic.append(clone);(body.querySelector('.chapter-source-map')||tools).after(graphic);
 }
});
const integrated=document.querySelector('.integrated-report');
if(integrated){
 const topicTools=document.createElement('div');topicTools.className='topic-controls';
 const caption=document.createElement('span');caption.textContent='按主题阅读';topicTools.append(caption);
 const expand=document.createElement('button');expand.type='button';expand.textContent='展开全部主题';
 expand.addEventListener('click',()=>{const chapters=[...integrated.querySelectorAll(':scope > .chapter')];const open=chapters.some(c=>!c.open);chapters.forEach(c=>c.open=open);expand.textContent=open?'收起全部主题':'展开全部主题';});topicTools.append(expand);
 const first=integrated.querySelector(':scope > .chapter');if(first)first.before(topicTools);
}
