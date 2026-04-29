let projects=[];let current=null;let entities={sensors:[],actuators:[]};
function showErr(e){console.error(e);alert('Fehler: '+(e?.message||e));}
function resolveApiUrl(url){
  if(url.startsWith('http')) return url;
  const clean=url.replace(/^\//,'');
  return new URL(clean, window.location.href.endsWith('/') ? window.location.href : window.location.href + '/').toString();
}
async function api(url,m='GET',b=null){
  const r=await fetch(resolveApiUrl(url),{method:m,headers:{'content-type':'application/json'},body:b?JSON.stringify(b):null});
  const d=await r.json().catch(()=>({detail:'invalid response'}));
  if(!r.ok) throw new Error(d.detail||d.message||('HTTP '+r.status));
  return d;
}
const byId=i=>document.getElementById(i); const sortByName=a=>[...a].sort((x,y)=>(x.friendly_name||x.entity_id).localeCompare(y.friendly_name||y.entity_id));
async function boot(){try{entities=await api('/api/entities');fillEntitySelects();await refreshProjects()}catch(e){showErr(e)}}
function fillEntitySelects(){const ss=byId('sensorSel');ss.innerHTML='';sortByName(entities.sensors).forEach(e=>{const o=document.createElement('option');o.value=e.entity_id;o.textContent=`${e.friendly_name} (${e.entity_id})`;ss.appendChild(o)});const as=byId('actSel');as.innerHTML='';sortByName(entities.actuators).forEach(e=>{const o=document.createElement('option');o.value=e.entity_id;o.textContent=`${e.friendly_name} (${e.entity_id})`;as.appendChild(o)})}
async function refreshProjects(){const d=await api('/api/projects');projects=d.projects||[];renderProjectList();if(!current&&projects.length)selectProject(projects[0].id)}
function renderProjectList(){const p=byId('plist');p.innerHTML='';projects.forEach(x=>{const d=document.createElement('div');d.className='item';d.innerHTML=`<b>${x.name}</b><div class='small'>${x.id}</div>`;d.onclick=()=>selectProject(x.id);p.appendChild(d)});if(!projects.length)p.innerHTML="<div class='small'>Noch keine Projekte.</div>"}
const find=id=>projects.find(x=>x.id===id);
function selectProject(id){current=id;const p=find(id);if(!p)return;byId('pname').textContent=p.name;byId('shadowBtn').textContent='Shadow: '+(p.shadow_mode?'ON':'OFF');byId('allSensors').checked=!!p.include_all_sensors;byId('allActs').checked=!!p.include_all_actuators;renderChosen();renderSuggestions();loadGraph()}
async function createProject(){try{const p=await api('/api/projects','POST',{name:byId('newName').value||'Neues NN Projekt'});projects.push(p);renderProjectList();selectProject(p.id)}catch(e){showErr(e)}}
async function renameProject(){if(!current)return;const p=find(current);const n=prompt('Neuer Name',p.name);if(!n)return;Object.assign(p,await api('/api/projects/'+current,'PATCH',{name:n}));renderProjectList();selectProject(current)}
async function deleteProject(){if(!current||!confirm('Projekt löschen?'))return;await api('/api/projects/'+current,'DELETE');projects=projects.filter(x=>x.id!==current);current=null;renderProjectList();if(projects[0])selectProject(projects[0].id)}
async function toggleShadow(){if(!current)return;const p=find(current);Object.assign(p,await api('/api/projects/'+current,'PATCH',{shadow_mode:!p.shadow_mode}));selectProject(current)}
async function saveToggles(){if(!current)return;Object.assign(find(current),await api('/api/projects/'+current,'PATCH',{include_all_sensors:byId('allSensors').checked,include_all_actuators:byId('allActs').checked}))}
async function addEntity(k){if(!current)return;const p=find(current),key=k==='sensor'?'sensor_entities':'actuator_entities',sel=byId(k==='sensor'?'sensorSel':'actSel');const set=new Set(p[key]||[]);set.add(sel.value);const payload={};payload[key]=[...set];Object.assign(p,await api('/api/projects/'+current,'PATCH',payload));renderChosen();loadGraph()}
function renderChosen(){const p=find(current);if(!p)return;byId('chosen').innerHTML=`<div><b>Sensoren</b><div style='margin-top:6px'>${(p.sensor_entities||[]).map(x=>`<span class='chip'>🟦 ${x}</span>`).join('')||"<span class='small'>-</span>"}</div></div><hr style='border-color:#2f4776'><div><b>Aktuatoren</b><div style='margin-top:6px'>${(p.actuator_entities||[]).map(x=>`<span class='chip'>🟩 ${x}</span>`).join('')||"<span class='small'>-</span>"}</div></div>`}
async function analyze(){if(!current)return;const d=await api('/api/projects/'+current+'/analyze','POST',{});Object.assign(find(current),d.project);renderSuggestions();loadGraph()}
function renderSuggestions(){const p=find(current);if(!p)return;const sugs=p.last_suggestions||[];byId('sugs').innerHTML=!sugs.length?"<div class='small'>Noch keine Vorschläge. Klicken Sie auf Analyse.</div>":sugs.map(s=>`<div class='item'><b>${s.title}</b><div class='small'>${s.reason} · conf ${s.confidence}</div><div class='small'>${s.will_execute?"<span class='warn'>LIVE ACTION</span>":"<span class='ok'>Shadow only</span>"}</div><div class='grid2' style='margin-top:6px'><button data-action='feedback' data-sid='${s.id}' data-vote='1'>👍 Gut</button><button data-action='feedback' data-sid='${s.id}' data-vote='-1'>👎 Nein</button></div></div>`).join('')}
async function fb(id,v){if(!current)return;await api('/api/projects/'+current+'/feedback','POST',{suggestion_id:id,vote:v});alert('Feedback gespeichert')}
async function loadGraph(){if(!current)return;const g=await api('/api/projects/'+current+'/nn-graph');const svg=byId('graph');svg.innerHTML='';const W=svg.clientWidth||900,H=340,map={};(g.nodes||[]).forEach((n,i)=>{let x=50,y=40+i*20;if(n.kind==='core'){x=W/2;y=H/2}else if(n.kind==='sensor'){x=120;y=28+(i*22)%300}else{x=W-180;y=28+(i*22)%300}map[n.id]={x,y,n}});(g.edges||[]).forEach(e=>{const a=map[e.from],b=map[e.to];if(!a||!b)return;const l=document.createElementNS('http://www.w3.org/2000/svg','line');l.setAttribute('x1',a.x);l.setAttribute('y1',a.y);l.setAttribute('x2',b.x);l.setAttribute('y2',b.y);l.setAttribute('stroke','#5b7fc8');l.setAttribute('stroke-width',String(1+2*(e.weight||0.5)));svg.appendChild(l)});Object.values(map).forEach(({x,y,n})=>{const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('cx',x);c.setAttribute('cy',y);c.setAttribute('r',n.kind==='core'?12:6);c.setAttribute('fill',n.kind==='core'?'#85ffd0':n.kind==='sensor'?'#78a8ff':'#ffd28a');svg.appendChild(c);const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x',x+10);t.setAttribute('y',y+3);t.setAttribute('fill','#d7e6ff');t.setAttribute('font-size','10');t.textContent=n.label;svg.appendChild(t)})}
document.addEventListener('click', async (ev)=>{
  const btn = ev.target.closest('button[data-action]');
  if(!btn) return;
  const a = btn.dataset.action;
  try {
    if(a==='create-project') return await createProject();
    if(a==='refresh-projects') return await refreshProjects();
    if(a==='rename-project') return await renameProject();
    if(a==='delete-project') return await deleteProject();
    if(a==='toggle-shadow') return await toggleShadow();
    if(a==='analyze') return await analyze();
    if(a==='add-entity') return await addEntity(btn.dataset.kind);
    if(a==='feedback') return await fb(btn.dataset.sid, Number(btn.dataset.vote||0));
  } catch(e){ showErr(e); }
});

boot();
