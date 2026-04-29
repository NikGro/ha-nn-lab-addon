from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(title="HA NN Lab", version="0.2.0")

DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_FILE = DATA_DIR / "projects.json"

HA_URL = os.getenv("HA_URL", "http://10.2.1.10:80")
HA_TOKEN = os.getenv(
    "HA_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjZDNkOWY2YzE5YWI0OTE2YmY4NjlkNmEwYmQ1NDc5YyIsImlhdCI6MTc3NTM5Njk4NSwiZXhwIjoyMDkwNzU2OTg1fQ.yR1s9qc_K2L2CpUzgV40rgX6r8UWL-yzBlUvsex-4sg",
)

ACTUATOR_DOMAINS = {
    "light",
    "switch",
    "climate",
    "cover",
    "media_player",
    "fan",
    "humidifier",
    "vacuum",
    "input_boolean",
    "lock",
    "alarm_control_panel",
}


def _now() -> int:
    return int(time.time())


def _ha_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


def _load_projects() -> list[dict[str, Any]]:
    if not PROJECTS_FILE.exists():
        return []
    return json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))


def _save_projects(projects: list[dict[str, Any]]) -> None:
    PROJECTS_FILE.write_text(json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_project(name: str = "Neues NN Projekt") -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name,
        "shadow_mode": True,
        "include_all_sensors": False,
        "include_all_actuators": False,
        "sensor_entities": [],
        "actuator_entities": [],
        "feedback": [],
        "last_suggestions": [],
        "last_run": None,
        "created_at": _now(),
        "updated_at": _now(),
    }


def _find_project(pid: str, projects: list[dict[str, Any]]) -> dict[str, Any]:
    p = next((x for x in projects if x["id"] == pid), None)
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    return p


def _get_states() -> list[dict[str, Any]]:
    r = requests.get(f"{HA_URL}/api/states", headers=_ha_headers(), timeout=20)
    r.raise_for_status()
    return r.json()


def _entity_split(states: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sensors = []
    actuators = []
    for s in states:
        eid = s.get("entity_id", "")
        if "." not in eid:
            continue
        dom = eid.split(".", 1)[0]
        item = {
            "entity_id": eid,
            "domain": dom,
            "state": s.get("state"),
            "friendly_name": s.get("attributes", {}).get("friendly_name", eid),
        }
        if dom in ACTUATOR_DOMAINS:
            actuators.append(item)
        else:
            sensors.append(item)
    return sensors, actuators


def _suggestions(project: dict[str, Any], states_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    sugs: list[dict[str, Any]] = []

    # very first practical policy hints (shadow only by default)
    occ = states_map.get("binary_sensor.wohnzimmer_bewegungsmelder_occupancy", {}).get("state")
    lux = states_map.get("sensor.wohnzimmer_bewegungsmelder_illuminance", {}).get("state")
    light = states_map.get("light.wohnzimmer_lichtgruppe", {}).get("state")
    try:
        lux_v = float(lux) if lux not in (None, "unknown", "unavailable") else None
    except Exception:
        lux_v = None

    if occ == "on" and lux_v is not None and lux_v < 30 and light == "off":
        sugs.append(
            {
                "id": uuid.uuid4().hex[:8],
                "type": "action_proposal",
                "title": "Wohnzimmer Lichtgruppe einschalten",
                "service": "light.turn_on",
                "target": {"entity_id": "light.wohnzimmer_lichtgruppe"},
                "data": {"brightness_pct": 35},
                "confidence": 0.76,
                "reason": "Bewegung erkannt + niedrige Helligkeit",
                "will_execute": not project.get("shadow_mode", True),
            }
        )

    vac = states_map.get("vacuum.s7_maxv", {}).get("state")
    blocker = states_map.get("input_boolean.staubsauger_blocker", {}).get("state")
    if vac in {"cleaning", "returning"} and blocker != "on":
        sugs.append(
            {
                "id": uuid.uuid4().hex[:8],
                "type": "action_proposal",
                "title": "Staubsauger-Blocker aktivieren",
                "service": "input_boolean.turn_on",
                "target": {"entity_id": "input_boolean.staubsauger_blocker"},
                "data": {},
                "confidence": 0.83,
                "reason": "Saugroboter aktiv ohne Blocker",
                "will_execute": not project.get("shadow_mode", True),
            }
        )

    return sugs


def _nn_graph(project: dict[str, Any]) -> dict[str, Any]:
    # visual proxy graph (project-specific)
    sensors = project.get("sensor_entities", [])[:20]
    acts = project.get("actuator_entities", [])[:20]
    center = {"id": "policy_core", "label": project.get("name", "NN Core"), "kind": "core"}
    nodes = [center]
    edges = []
    for i, s in enumerate(sensors):
        nid = f"s{i}"
        nodes.append({"id": nid, "label": s, "kind": "sensor"})
        edges.append({"from": nid, "to": "policy_core", "weight": round(0.4 + (i % 6) * 0.09, 2)})
    for i, a in enumerate(acts):
        nid = f"a{i}"
        nodes.append({"id": nid, "label": a, "kind": "actuator"})
        edges.append({"from": "policy_core", "to": nid, "weight": round(0.45 + (i % 5) * 0.1, 2)})
    return {"nodes": nodes, "edges": edges}


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "ha-nn-lab", "version": "0.2.0", "ha_url": HA_URL}


@app.get("/api/entities")
async def entities() -> dict[str, Any]:
    states = _get_states()
    sensors, actuators = _entity_split(states)
    return {"sensors": sensors, "actuators": actuators}


@app.get("/api/projects")
async def projects() -> dict[str, Any]:
    return {"projects": _load_projects()}


@app.post("/api/projects")
async def create_project(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    projects = _load_projects()
    p = _default_project(str(payload.get("name") or "Neues NN Projekt"))
    projects.append(p)
    _save_projects(projects)
    return p


@app.patch("/api/projects/{pid}")
async def update_project(pid: str, payload: dict[str, Any]) -> dict[str, Any]:
    projects = _load_projects()
    p = _find_project(pid, projects)
    for k in [
        "name",
        "shadow_mode",
        "include_all_sensors",
        "include_all_actuators",
        "sensor_entities",
        "actuator_entities",
    ]:
        if k in payload:
            p[k] = payload[k]
    p["updated_at"] = _now()
    _save_projects(projects)
    return p


@app.delete("/api/projects/{pid}")
async def delete_project(pid: str) -> dict[str, Any]:
    projects = _load_projects()
    before = len(projects)
    projects = [p for p in projects if p["id"] != pid]
    if len(projects) == before:
        raise HTTPException(status_code=404, detail="project not found")
    _save_projects(projects)
    return {"ok": True}


@app.post("/api/projects/{pid}/analyze")
async def analyze_project(pid: str) -> dict[str, Any]:
    projects = _load_projects()
    p = _find_project(pid, projects)

    states = _get_states()
    states_map = {s.get("entity_id"): s for s in states}
    sensors, actuators = _entity_split(states)

    if p.get("include_all_sensors"):
        p["sensor_entities"] = [x["entity_id"] for x in sensors]
    if p.get("include_all_actuators"):
        p["actuator_entities"] = [x["entity_id"] for x in actuators]

    sugs = _suggestions(p, states_map)
    p["last_suggestions"] = sugs
    p["last_run"] = _now()
    p["updated_at"] = _now()
    _save_projects(projects)

    return {
        "project": p,
        "summary": {
            "sensor_count": len(p.get("sensor_entities", [])),
            "actuator_count": len(p.get("actuator_entities", [])),
            "suggestion_count": len(sugs),
            "shadow_mode": p.get("shadow_mode", True),
        },
    }


@app.post("/api/projects/{pid}/feedback")
async def feedback(pid: str, payload: dict[str, Any]) -> dict[str, Any]:
    projects = _load_projects()
    p = _find_project(pid, projects)
    p.setdefault("feedback", []).append(
        {
            "ts": _now(),
            "suggestion_id": payload.get("suggestion_id"),
            "vote": payload.get("vote"),
            "note": payload.get("note", ""),
        }
    )
    p["updated_at"] = _now()
    _save_projects(projects)
    return {"ok": True}


@app.get("/api/projects/{pid}/nn-graph")
async def nn_graph(pid: str) -> dict[str, Any]:
    p = _find_project(pid, _load_projects())
    return _nn_graph(p)


UI = """
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>HA NN Lab</title>
<style>
body{margin:0;font-family:Inter,system-ui;background:#0b1020;color:#e8edff} .app{display:grid;grid-template-columns:300px 1fr;min-height:100vh}
.sidebar{border-right:1px solid #263760;padding:14px;background:#111a33}.main{padding:14px}
.card{background:#151f3d;border:1px solid #2e4377;border-radius:12px;padding:12px;margin-bottom:10px}
input,select,button,textarea{width:100%;padding:8px;border-radius:8px;border:1px solid #345292;background:#0f1832;color:#fff}
button{cursor:pointer}.row{display:flex;gap:8px}.row>button{flex:1}.small{font-size:12px;color:#9fb2e2}
.list{max-height:220px;overflow:auto;border:1px dashed #324d86;border-radius:8px;padding:8px}
.p{padding:6px;border-bottom:1px solid #2a3e6e}.p:last-child{border-bottom:none}.ok{color:#8dffbf}.warn{color:#ffd38d}
svg{width:100%;height:340px;background:#0c1430;border:1px solid #2f467f;border-radius:8px}
</style></head><body>
<div class='app'>
  <aside class='sidebar'>
    <h3>HA NN Lab</h3>
    <div class='small'>Sidebar-ready WebUI</div>
    <div class='card'>
      <div class='small'>Projektname</div>
      <input id='newName' value='Neues NN Projekt'>
      <div class='row' style='margin-top:8px'><button onclick='createProject()'>+ Anlegen</button></div>
    </div>
    <div class='card'>
      <div class='small'>Projekte</div>
      <div id='plist' class='list'></div>
    </div>
  </aside>
  <main class='main'>
    <div class='card'>
      <h3 id='pname'>Kein Projekt gewählt</h3>
      <div class='row'>
        <button onclick='renameProject()'>Umbenennen</button>
        <button onclick='deleteProject()'>Löschen</button>
      </div>
      <div class='row' style='margin-top:8px'>
        <button onclick='toggleShadow()' id='shadowBtn'>Shadow: ON</button>
        <button onclick='analyze()'>Analyse laufen lassen</button>
      </div>
      <div class='row' style='margin-top:8px'>
        <label style='flex:1'><input type='checkbox' id='allSensors' onchange='saveToggles()'> alle Sensoren</label>
        <label style='flex:1'><input type='checkbox' id='allActs' onchange='saveToggles()'> alle Aktuatoren</label>
      </div>
    </div>

    <div class='card'>
      <h4>Sensoren/Aktuatoren manuell</h4>
      <div class='row'>
        <select id='sensorSel'></select>
        <button onclick='addEntity("sensor")'>+ Sensor</button>
      </div>
      <div class='row'>
        <select id='actSel'></select>
        <button onclick='addEntity("actuator")'>+ Aktuator</button>
      </div>
      <div class='small'>Manuell ausgewählt</div>
      <div id='chosen' class='list'></div>
    </div>

    <div class='card'>
      <h4>NN Vorschläge</h4>
      <div id='sugs'></div>
    </div>

    <div class='card'>
      <h4>NN Visual</h4>
      <svg id='graph'></svg>
    </div>
  </main>
</div>
<script>
let projects=[]; let current=null; let entities={sensors:[],actuators:[]};
async function api(url,method='GET',body=null){const r=await fetch(url,{method,headers:{'content-type':'application/json'},body:body?JSON.stringify(body):null});const d=await r.json(); if(!r.ok) throw new Error(d.detail||'error'); return d;}
async function boot(){entities=await api('/api/entities'); fillEntitySelects(); await refreshProjects();}
function fillEntitySelects(){
  const ss=document.getElementById('sensorSel'); ss.innerHTML='';
  entities.sensors.forEach(e=>{const o=document.createElement('option');o.value=e.entity_id;o.textContent=e.friendly_name+' ('+e.entity_id+')';ss.appendChild(o);});
  const as=document.getElementById('actSel'); as.innerHTML='';
  entities.actuators.forEach(e=>{const o=document.createElement('option');o.value=e.entity_id;o.textContent=e.friendly_name+' ('+e.entity_id+')';as.appendChild(o);});
}
async function refreshProjects(){const d=await api('/api/projects');projects=d.projects||[];renderProjectList();if(!current&&projects.length){selectProject(projects[0].id);}}
function renderProjectList(){const p=document.getElementById('plist');p.innerHTML='';projects.forEach(x=>{const d=document.createElement('div');d.className='p';d.innerHTML=`<b>${x.name}</b><div class='small'>${x.id}</div>`;d.onclick=()=>selectProject(x.id);p.appendChild(d);});}
function find(id){return projects.find(x=>x.id===id);}
function selectProject(id){current=id; const p=find(id); if(!p) return; document.getElementById('pname').textContent=p.name; document.getElementById('shadowBtn').textContent='Shadow: '+(p.shadow_mode?'ON':'OFF'); document.getElementById('allSensors').checked=!!p.include_all_sensors; document.getElementById('allActs').checked=!!p.include_all_actuators; renderChosen(); renderSuggestions(); loadGraph();}
async function createProject(){const name=document.getElementById('newName').value||'Neues NN Projekt';const p=await api('/api/projects','POST',{name});projects.push(p);renderProjectList();selectProject(p.id);}
async function renameProject(){if(!current) return; const p=find(current); const n=prompt('Neuer Name',p.name); if(!n) return; const up=await api('/api/projects/'+current,'PATCH',{name:n}); Object.assign(p,up); renderProjectList(); selectProject(current);}
async function deleteProject(){if(!current) return; if(!confirm('Projekt löschen?')) return; await api('/api/projects/'+current,'DELETE'); projects=projects.filter(x=>x.id!==current); current=null; renderProjectList(); if(projects[0]) selectProject(projects[0].id);}
async function toggleShadow(){if(!current) return; const p=find(current); const up=await api('/api/projects/'+current,'PATCH',{shadow_mode:!p.shadow_mode}); Object.assign(p,up); selectProject(current);}
async function saveToggles(){if(!current) return; const up=await api('/api/projects/'+current,'PATCH',{include_all_sensors:document.getElementById('allSensors').checked,include_all_actuators:document.getElementById('allActs').checked}); Object.assign(find(current),up);}
async function addEntity(kind){if(!current) return; const p=find(current); const key=kind==='sensor'?'sensor_entities':'actuator_entities'; const sel=document.getElementById(kind==='sensor'?'sensorSel':'actSel'); const set=new Set(p[key]||[]); set.add(sel.value); const payload={}; payload[key]=[...set]; const up=await api('/api/projects/'+current,'PATCH',payload); Object.assign(p,up); renderChosen(); loadGraph();}
function renderChosen(){const p=find(current); if(!p) return; const box=document.getElementById('chosen'); const s=(p.sensor_entities||[]).map(x=>'🟦 '+x).join('<br>'); const a=(p.actuator_entities||[]).map(x=>'🟩 '+x).join('<br>'); box.innerHTML='<b>Sensoren</b><br>'+ (s||'<span class="small">-</span>') +'<hr><b>Aktuatoren</b><br>'+ (a||'<span class="small">-</span>');}
async function analyze(){if(!current) return; const d=await api('/api/projects/'+current+'/analyze','POST',{}); const p=find(current); Object.assign(p,d.project); renderSuggestions(); loadGraph();}
function renderSuggestions(){const p=find(current); if(!p) return; const box=document.getElementById('sugs'); const sugs=p.last_suggestions||[]; if(!sugs.length){box.innerHTML='<div class="small">Noch keine Vorschläge.</div>'; return;} box.innerHTML=sugs.map(s=>`<div class='p'><b>${s.title}</b><div class='small'>${s.reason} · conf ${s.confidence}</div><div class='small'>${s.will_execute?'<span class="warn">LIVE ACTION</span>':'<span class="ok">Shadow only</span>'}</div><div class='row'><button onclick='fb("${s.id}",1)'>👍</button><button onclick='fb("${s.id}",-1)'>👎</button></div></div>`).join('');}
async function fb(id,v){if(!current) return; await api('/api/projects/'+current+'/feedback','POST',{suggestion_id:id,vote:v}); alert('Feedback gespeichert');}
async function loadGraph(){if(!current) return; const g=await api('/api/projects/'+current+'/nn-graph'); const svg=document.getElementById('graph'); svg.innerHTML=''; const W=svg.clientWidth||900,H=340; const nodes=g.nodes||[]; const edges=g.edges||[]; const map={}; nodes.forEach((n,i)=>{let x=50,y=40+i*20;if(n.kind==='core'){x=W/2;y=H/2}else if(n.kind==='sensor'){x=120;y=30+(i*22)%300}else{x=W-180;y=30+(i*22)%300} map[n.id]={x,y,n};}); edges.forEach(e=>{const a=map[e.from],b=map[e.to]; if(!a||!b)return; const l=document.createElementNS('http://www.w3.org/2000/svg','line'); l.setAttribute('x1',a.x);l.setAttribute('y1',a.y);l.setAttribute('x2',b.x);l.setAttribute('y2',b.y);l.setAttribute('stroke','#5b7fc8');l.setAttribute('stroke-width',String(1+2*(e.weight||0.5))); svg.appendChild(l);}); Object.values(map).forEach(({x,y,n})=>{const c=document.createElementNS('http://www.w3.org/2000/svg','circle'); c.setAttribute('cx',x);c.setAttribute('cy',y);c.setAttribute('r',n.kind==='core'?12:7); c.setAttribute('fill',n.kind==='core'?'#85ffd0':n.kind==='sensor'?'#78a8ff':'#ffd28a'); svg.appendChild(c); const t=document.createElementNS('http://www.w3.org/2000/svg','text'); t.setAttribute('x',x+10);t.setAttribute('y',y+4); t.setAttribute('fill','#d7e6ff');t.setAttribute('font-size','10'); t.textContent=n.label; svg.appendChild(t);});}
boot();
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(UI)
