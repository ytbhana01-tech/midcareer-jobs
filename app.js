'use strict';
const $ = id => document.getElementById(id);
const regions = ['광주','전남','서울','경기','인천','강원','충북','충남','대전','세종','전북','전남광주','경북','경남','대구','부산','울산','제주','해외'];
for (const region of regions) { const option = document.createElement('option'); option.value=region; option.textContent=region==='전남광주'?'광주·전남 (ALIO 통합)':region; $('region').append(option); }
let jobs=[], limit=20, feed=null;
const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function koreaToday(now=new Date()) { return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(now); }
function validDate(value) { return typeof value==='string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0,10)===value; }
function safeURL(value) { try { const u=new URL(value); return u.protocol==='https:'&&!u.username&&!u.password&&!/[\x00-\x20]/.test(value)&&!/(servicekey|api[_-]?key|token|authorization)=/i.test(u.search)?u.href:null; } catch {return null;} }
function isActive(job,today=koreaToday()) { return validDate(job.deadline)&&job.deadline>=today&&(!job.start||validDate(job.start)&&job.start<=today)&&(!job.closes_at||Number.isFinite(Date.parse(job.closes_at))&&Date.parse(job.closes_at)>=Date.now())&&(!job.opens_at||Number.isFinite(Date.parse(job.opens_at))&&Date.parse(job.opens_at)<=Date.now()); }
const sourceNames={alio:'ALIO',nara:'나라일터',busan:'부산광역시'};
function sourcesOf(j){return [...new Set((Array.isArray(j.attributions)?j.attributions.map(a=>a.source_id):[j.source_id||'alio']).filter(id=>Object.hasOwn(sourceNames,id)))];}
function employmentTypes(j){return Array.isArray(j.employment_types)?j.employment_types:(j.tags||[]).filter(t=>['공무직','무기계약직','기간제'].includes(t)).length?(j.tags||[]).filter(t=>['공무직','무기계약직','기간제'].includes(t)):(j.type?['기타']:[]);}
function hasTag(j,tag) { return Array.isArray(j.tags)&&j.tags.includes(tag); }
function matches(j,filters) {
  if(filters.source&&!sourcesOf(j).includes(filters.source))return false;
  const q=filters.q.trim().toLocaleLowerCase('ko');
  if(q&&!`${j.title} ${j.org} ${j.region} ${j.description||''}`.toLocaleLowerCase('ko').includes(q))return false;
  if(filters.region&&!String(j.region).split(',').map(x=>x.trim()).includes(filters.region))return false;
  const employment=filters.employment;
  if(employment==='focus'&&!hasTag(j,'공무직')&&!hasTag(j,'무기계약직'))return false;
  if(employment==='unknown'&&j.type)return false;
  if(employment&&!['focus','unknown'].includes(employment)){
    if(['공무직','무기계약직','기간제','기타'].includes(employment)){if(!employmentTypes(j).includes(employment))return false;}
    else if(!String(j.type).split(',').map(x=>x.trim()).includes(employment))return false;
  }
  if(filters.career==='unknown'&&j.career)return false;
  if(filters.career&&filters.career!=='unknown'&&j.career!==filters.career)return false;
  if(filters.education==='unknown'&&j.education)return false;
  if(filters.education==='학력무관'&&!hasTag(j,'학력무관'))return false;
  return true;
}
function filtersNow(){return Object.fromEntries(['q','source','region','employment','career','education'].map(id=>[id,$(id).value]));}
function render(){
  const today=koreaToday(), active=jobs.filter(j=>isActive(j,today)), filters=filtersNow();
  $('total-stat').textContent=active.length.toLocaleString('ko');
  $('focus-stat').textContent=active.filter(j=>hasTag(j,'공무직')||hasTag(j,'무기계약직')).length.toLocaleString('ko');
  $('education-stat').textContent=active.filter(j=>hasTag(j,'학력무관')).length.toLocaleString('ko');
  const filtered=active.filter(j=>matches(j,filters)).sort((a,b)=>$('sort').value==='recent'?(b.published_date||b.start||'').localeCompare(a.published_date||a.start||'')||a.deadline.localeCompare(b.deadline):a.deadline.localeCompare(b.deadline)||a.id.localeCompare(b.id));
  $('count').textContent=filtered.length.toLocaleString('ko');
  $('active-filter').textContent=[filters.q?`검색: ${filters.q}`:'',...['source','region','employment','career','education'].filter(id=>$(id).value).map(id=>$(id).selectedOptions[0].textContent)].filter(Boolean).join(' · ')||'전체 접수 중 공고';
  $('cards').innerHTML=filtered.length?filtered.slice(0,limit).map(j=>{
    const days=Math.round((Date.parse(j.deadline)-Date.parse(today))/86400000);
    return `<article class="job"><div class="card-top"><span class="org">${esc(j.org)}</span><span class="countdown ${days<=3?'urgent':''}">${days===0?'오늘 마감':`D−${days}`}</span></div><h3>${esc(j.title)}</h3><p class="source-attribution">출처: ${sourcesOf(j).map(id=>esc(sourceNames[id])).join(' · ')} · ${esc(j.collected_at?new Date(j.collected_at).toLocaleDateString('ko-KR',{timeZone:'Asia/Seoul'}):'기존 피드')}</p><div class="tags">${(j.tags||[]).map(tag=>`<span class="tag ${['공무직','무기계약직'].includes(tag)?'focus':''}">${esc(tag)}</span>`).join('')}${!(j.tags||[]).length?'<span class="tag">관심 조건 명시 없음</span>':''}${j.source_id==='nara'&&!j.start?'<span class="tag">접수 시작일 원문 확인</span>':''}</div><dl class="facts"><dt>근무지</dt><dd>${esc(j.region||'미확인')}</dd><dt>고용형태</dt><dd>${esc(j.type||'미확인')}</dd><dt>경력 · 학력</dt><dd>${esc(j.career||'미확인')} · ${esc(j.education||'미확인')}</dd><dt>접수 마감</dt><dd>${esc(j.deadline)} <span>(한국 날짜)</span></dd></dl><div class="card-bottom"><button type="button" data-detail="${esc(j.id)}" aria-label="${esc(j.title)} 상세 보기">자격요건 · 상세 보기 →</button><a class="source-link" href="${esc(safeURL(j.source_url))}" target="_blank" rel="noopener noreferrer" aria-label="${esc(j.title)} 공고 원문 새 창">공고 원문 ↗</a></div></article>`;
  }).join(''):`<div class="empty"><b>${feed?'조건에 맞는 접수 중 공고가 없습니다.':'채용정보를 표시할 수 없습니다.'}</b>${feed?'검색어나 필터를 바꿔 보세요. 확인되지 않은 조건은 검색 결과에 포함하지 않습니다.':'잠시 후 다시 시도해 주세요. 데이터를 임의로 만들어 표시하지 않습니다.'}</div>`;
  $('more').hidden=filtered.length<=limit;
  $('more').textContent=`공고 더 보기 (${Math.min(limit,filtered.length)} / ${filtered.length})`;
  $('cards').setAttribute('aria-busy','false');
}
function detail(id){
  const j=jobs.find(job=>job.id===id);if(!j)return;
  if(!isActive(j)){render();return;}
  $('detail-org').textContent=j.org;$('detail-title').textContent=j.title;
  $('detail-facts').replaceChildren();
  for(const [label,value] of [['출처',sourcesOf(j).map(id=>sourceNames[id]).join(' · ')],['근무지',j.region],['고용형태',j.type],['경력',j.career],['학력',j.education],['접수기간',`${j.start||'미확인'} ~ ${j.deadline}`]]){
    const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value||'미확인';$('detail-facts').append(dt,dd);
  }
  $('detail-content').replaceChildren();
  for(const [title,value] of [['공고 내용',j.description],['지원 자격',j.qualifications],['전형 절차',j.procedure],['우대 조건',j.preference]]){
    const h=document.createElement('h3'),p=document.createElement('p');h.textContent=title;p.textContent=value||'출처에서 확인되지 않았습니다. 공고 원문을 확인해 주세요.';$('detail-content').append(h,p);
  }
  $('detail-source').href=safeURL(j.source_url);$('detail').showModal();$('detail').scrollTop=0;
}
$('filters').addEventListener('submit',e=>{e.preventDefault();limit=20;render();$('results').scrollIntoView({block:'start'});});
for(const id of ['q','source','region','employment','career','education','sort'])$(id).addEventListener(id==='q'?'input':'change',()=>{limit=20;render();});
$('reset-filters').addEventListener('click',()=>{$('filters').reset();$('employment').value='';$('sort').value='deadline';limit=20;render();});
$('more').addEventListener('click',()=>{limit+=20;render();});
$('cards').addEventListener('click',e=>{const button=e.target.closest('[data-detail]');if(button)detail(button.dataset.detail);});
$('close-detail').addEventListener('click',()=>$('detail').close());
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close();}});
function feedStatus(){
  if(!feed)return;
  const date=new Date(feed.updated_at),valid=Boolean(feed.updated_at)&&!Number.isNaN(date.getTime());
  $('updated').textContent=valid?`갱신 ${date.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})} KST`:'갱신 시각 미확인';
  if(feed.sources){
    let warning=false;
    const messages=Object.entries(sourceNames).map(([id,name])=>{
      const status=feed.sources[id]||{status:'disabled'};
      const count=jobs.filter(j=>isActive(j)&&sourcesOf(j).includes(id)).length;
      const stamp=status.updated_at?Date.parse(status.updated_at):NaN;
      const stale=!Number.isFinite(stamp)||Date.now()-stamp>48*3600000;
      const pending=status.status==='disabled'||status.status==='unavailable';
      const cached=status.status==='cached';
      if(pending||cached||stale||status.mode==='alio-public-preview')warning=true;
      let label=pending?'연결 대기':`${count}건${cached?' · 이전 데이터':''}${stale?' · 갱신 지연':''}`;
      if(!pending&&status.mode==='alio-public-preview')label+=' · 공개 조회, 인증 API 미검증';
      if(!pending&&!status.originals_verified)label+=' · 원문 재검증 대기';
      if(status.coverage&&!pending)label+=' · '+status.coverage;
      const rejected=(status.stats?.detail_mismatch||0)+(status.stats?.unmatched_original||0);
      if(rejected)label+=` · 불일치 제외 ${rejected}건`;
      return `${name}: ${label}`;
    });
    $('feed-notice').textContent=messages.join(' / ')+' · 종료된 공고는 자동 제외됩니다.';
    $('feed-notice').classList.toggle('error',warning);
    for(const option of $('source').options){if(option.value){const status=feed.sources[option.value];option.textContent=sourceNames[option.value]+(!status||['disabled','unavailable'].includes(status.status)?' (연결 대기)':'');}}
    return;
  }
  const stale=!valid||Date.now()-date.getTime()>48*3600000;
  $('feed-notice').textContent=(feed.source==='alio-api'&&feed.authenticated_api_verified?'ALIO 목록·상세 API에서 수집한 공고입니다.':'ALIO 공식 공개 조회의 실제 목록·상세 데이터입니다. 인증 API 연결은 아직 검증되지 않았습니다.')+(stale?' 수집 후 48시간이 지나 최신 정보가 아닐 수 있습니다. 원문을 확인하세요.':' 종료일이 지난 공고는 자동으로 제외됩니다.');
  $('feed-notice').classList.toggle('error',stale||!feed.authenticated_api_verified);
}
fetch('./jobs.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('feed');return r.json();}).then(data=>{
  if(!data||!Array.isArray(data.jobs))throw Error('schema');
  const seen=new Set();jobs=data.jobs.filter(j=>{
    if(!j||typeof j.id!=='string'||seen.has(j.id)||!j.title||!j.org||!safeURL(j.source_url))return false;
    seen.add(j.id);return true;
  });feed=data;feedStatus();render();
}).catch(()=>{$('feed-notice').textContent='채용정보를 불러오지 못했습니다. 새로고침하거나 잠시 후 다시 접속해 주세요.';$('feed-notice').classList.add('error');render();});
setInterval(()=>{feedStatus();render();},60000);
