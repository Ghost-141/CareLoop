"""Private CareLoop portal routes with CareLoop-specific authenticated access."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .auth import AuthError, Identity, TokenAuth
from .core import AccessDenied, CareLoopService


PORTAL_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CareLoop — private synthetic demo</title>
<style>
:root{--ink:#102a34;--muted:#60757c;--line:#d8e3e5;--canvas:#f4f8f7;--card:#fff;--brand:#096b68;--brand-dark:#04514f;--wash:#e0f2ee;--warn:#8a4b00;--warn-bg:#fff4e5;--danger:#a52f28;--radius:18px;--shadow:0 10px 28px #1234}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,textarea,select{font:inherit}button{cursor:pointer;border:0;border-radius:10px;padding:.62rem .9rem;background:var(--brand);color:#fff;font-weight:700}button:hover{background:var(--brand-dark)}button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:3px solid #f0aa35;outline-offset:2px}.secondary{background:#e5eff0;color:var(--ink)}.danger{background:#b33c35}.shell{max-width:1200px;margin:auto;padding:24px}.top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.eyebrow{font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--brand);font-weight:800}.top h1{margin:.1rem 0;font-size:clamp(1.8rem,4vw,2.7rem)}.subtitle{color:var(--muted);margin:0}.pill{background:var(--wash);color:var(--brand-dark);border-radius:99px;padding:.35rem .65rem;font-weight:700;font-size:.85rem}.notice{margin:22px 0;padding:12px 16px;border-left:4px solid #d98916;background:var(--warn-bg);color:#593300;border-radius:8px}.signin{max-width:560px;margin:60px auto;padding:28px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}.signin h2{margin-top:0}.signin form,.stack{display:grid;gap:12px}.hint{font-size:.9rem;color:var(--muted)}label{font-weight:700}input,textarea,select{width:100%;padding:.62rem .7rem;border:1px solid #aabcc0;border-radius:9px;background:#fff;color:var(--ink)}textarea{min-height:100px}.app[hidden],.signin[hidden]{display:none}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}.nav button{background:transparent;color:var(--brand-dark);border:1px solid var(--line)}.nav button[aria-current="page"]{background:var(--brand);color:#fff;border-color:var(--brand)}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.card{grid-column:span 6;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:0 2px 8px #1231}.card.wide{grid-column:span 12}.card h2{font-size:1.15rem;margin:0 0 12px}.card h3{font-size:1rem;margin:18px 0 8px}.item{border-top:1px solid var(--line);padding:12px 0}.item:first-child{border-top:0;padding-top:0}.item p{margin:.25rem 0}.meta{font-size:.86rem;color:var(--muted)}.status{font-size:.8rem;font-weight:800;border-radius:99px;padding:.2rem .5rem;background:var(--wash);color:var(--brand-dark);display:inline-block}.status.draft{background:#fff1d9;color:var(--warn)}.status.revoked{background:#fde8e6;color:var(--danger)}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.split{display:grid;grid-template-columns:1fr 1fr;gap:10px}.empty{color:var(--muted);font-style:italic}.toast{position:fixed;right:18px;bottom:18px;z-index:3;background:#102a34;color:#fff;padding:12px 16px;border-radius:10px;box-shadow:var(--shadow);max-width:330px}.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}@media(max-width:720px){.shell{padding:16px}.top{display:block}.top>div:last-child{margin-top:12px}.card,.card.wide{grid-column:span 12}.split{grid-template-columns:1fr}.nav{overflow:auto;flex-wrap:nowrap}.nav button{white-space:nowrap}}
</style></head><body><main class="shell">
<header class="top"><div><div class="eyebrow">Private synthetic demo</div><h1>CareLoop</h1><p class="subtitle">A patient-controlled care coordination workspace.</p></div><div id="identity" class="pill" hidden></div></header>
<aside class="notice"><strong>Demo only — not medical advice or emergency monitoring.</strong> This sandbox stores synthetic information. Follow the care plan provided by a qualified clinician; contact local emergency services for urgent concerns.</aside>
<section id="signin" class="signin" aria-labelledby="signin-title"><h2 id="signin-title">Open a private demo session</h2><p>Paste an authorized CareLoop demo token. Your token stays in this browser session and is never displayed in the page.</p><form id="signin-form"><label for="token">Demo token</label><input id="token" name="token" autocomplete="off" required placeholder="Paste demo token"><button type="submit">Continue securely</button></form><p id="signin-error" class="hint" role="alert"></p></section>
<section id="app" class="app" hidden aria-live="polite"><nav class="nav" aria-label="CareLoop views"><button data-view="today" aria-current="page">Today</button><button data-view="plan">Plan review</button><button data-view="track">Track</button><button data-view="sharing">Sharing</button><button data-view="handoff">Handoff</button><button id="signout" class="secondary">Sign out</button></nav><p id="live" class="sr" aria-live="polite"></p><div id="view"></div></section>
</main><div id="toast" class="toast" role="status" hidden></div>
<script>
(() => {
  const $ = s => document.querySelector(s), apiBase = '/api/care';
  const state = { me:null, view:'today', records:[], tasks:[], observations:[], grants:[], notices:[] };
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const token = () => sessionStorage.getItem('careloopToken') || '';
  const say = msg => { $('#live').textContent = msg; $('#toast').textContent = msg; $('#toast').hidden=false; setTimeout(()=>$('#toast').hidden=true,3600); };
  async function request(path, options={}) { const r=await fetch(apiBase+path,{...options,headers:{Authorization:'Bearer '+token(),'Content-Type':'application/json',...(options.headers||{})}}); if(!r.ok){if(r.status===401||r.status===403){throw new Error('Your session does not have permission for that action.');} throw new Error('That request could not be completed.');} return r.json(); }
  const timestamp = n => n ? new Date(n*1000).toLocaleString() : 'Not dated';
  const items = (rows, fn, empty='Nothing to show yet.') => rows?.length ? rows.map(fn).join('') : `<p class="empty">${empty}</p>`;
  async function load() { state.me=(await request('/me')); const [records,tasks,observations,grants]=await Promise.all([request('/records'),request('/tasks').catch(()=>({tasks:[]})),request('/observations').catch(()=>({observations:[]})),request('/grants').catch(()=>({grants:[]}))]); state.records=records.records||[];state.tasks=tasks.tasks||[];state.observations=observations.observations||[];state.grants=grants.grants||[]; if(state.me.role==='caregiver') state.notices=(await request('/notifications').catch(()=>({notifications:[]}))).notifications||[]; }
  function card(title, content, wide=false){return `<section class="card ${wide?'wide':''}"><h2>${title}</h2>${content}</section>`}
  function patientToday(){return `<div class="grid">${card('Today’s tasks',items(state.tasks,t=>`<div class="item"><div class="row"><strong>${esc(t.text||t.title||'Care task')}</strong><span class="status">${esc(t.status||'active')}</span></div><p class="meta">${t.completed_at?'Completed '+timestamp(t.completed_at):'Patient-approved plan item'}</p>${t.status==='active'&&!t.completed_at?`<button data-complete="${esc(t.id)}">Mark complete</button>`:''}</div>`,'Approve a plan task to see it here.'))}${card('Recent check-ins',items(state.observations.slice(0,4),o=>`<div class="item"><strong>Pain score: ${esc(o.pain_score)}/10</strong><p class="meta">${timestamp(o.observed_at||o.created_at)}${o.actor_id?' · recorded by '+esc(o.actor_id):''}</p></div>`,'No observations recorded. Use Track to add one.'))}${card('Private sharing',`<p>Caregivers see only what you explicitly grant. You can revoke access at any time.</p><button data-go="sharing" class="secondary">Manage access</button>`)}${card('Your plan',`<p>Review imported items before anything becomes active.</p><button data-go="plan" class="secondary">Review plan</button>`)}</div>`}
  function caregiverToday(){return `<div class="grid">${card('Action-required updates',items(state.notices,n=>`<div class="item"><strong>CareLoop update</strong><p class="meta">An update needs acknowledgement. No private care details are shown here.</p><button data-ack="${esc(n.case_id)}">Acknowledge</button></div>`,'No action-required updates.'))}${card('Your access',`<p>Access is controlled by the patient. This view shows only consent-scoped information.</p><span class="status">Private caregiver session</span>`)}${card('Tasks shared with you',items(state.tasks,t=>`<div class="item"><strong>${esc(t.text||t.title||'Care task')}</strong><p class="meta">${esc(t.status||'active')}</p></div>`,'No tasks are shared with your account.'))}</div>`}
  function plan(){ const plans=state.records.filter(r=>r.type==='PLAN_TASK'||r.type==='PLAN_RULE'); return `<div class="grid">${card('Review plan items',items(plans,p=>`<div class="item"><div class="row"><strong>${esc(p.text||p.title||'Plan item')}</strong><span class="status ${esc(p.status||'draft')}">${esc(p.status||'draft')}</span></div><p class="meta">${p.type==='PLAN_RULE'?'Clinician-sourced rule':'Task'} · requires explicit patient approval</p>${state.me.role==='patient'&&p.status==='draft'?`<button data-approve="${esc(p.id)}">Approve item</button>`:''}</div>`,'Import synthetic text below to create reviewable drafts.'),true)}${state.me.role==='patient'?card('Import a synthetic plan',`<form id="intake" class="stack"><label>Plan title<input name="title" maxlength="160" required value="Synthetic care plan"></label><label>Plan text<textarea name="text" required placeholder="TASK: Take a short walk daily&#10;RULE: PAIN_SCORE_AT_OR_ABOVE threshold=7 consecutive_days=2"></textarea></label><p class="hint">Only deterministic TASK:/RULE: demo lines are supported. Raw text is not displayed after intake.</p><button>Import for review</button></form>`):''}</div>`}
  function track(){return `<div class="grid">${card('Observation history',items(state.observations,o=>`<div class="item"><strong>Pain score: ${esc(o.pain_score)}/10</strong><p class="meta">${timestamp(o.observed_at||o.created_at)} · ${esc(o.status||'recorded')}</p></div>`,'No observations yet.'),true)}${(state.me.role==='patient')?card('Add a check-in',`<form id="observation" class="stack"><label>Pain score (0–10)<input name="pain_score" type="number" min="0" max="10" required></label><p class="hint">This is a simple patient-reported entry, not clinical interpretation.</p><button>Save check-in</button></form>`):''}</div>`}
  function sharing(){return `<div class="grid">${card('Caregiver access',items(state.grants,g=>`<div class="item"><strong>${esc(g.caregiver_id||'Caregiver')}</strong><p class="meta">Scopes: ${esc((g.scopes||[]).join(', '))||'None'}${g.expires_at?' · expires '+timestamp(g.expires_at):''}</p><span class="status ${g.status==='revoked'?'revoked':''}">${esc(g.status||'active')}</span>${state.me.role==='patient'&&g.status!=='revoked'?` <button class="danger" data-revoke="${esc(g.id||g.invitation_id)}">Revoke</button>`:''}</div>`,'No caregiver access grants yet.'))}${state.me.role==='patient'?card('Invite a caregiver',`<form id="invite" class="stack"><label>Access<select name="scope"><option value="read_tasks">View approved tasks</option><option value="write_observations">Add observations</option><option value="receive_alerts">Receive generic alerts</option><option value="acknowledge_alerts">Acknowledge alerts</option></select></label><label>Expiry (optional Unix timestamp)<input name="expires_at" inputmode="numeric" placeholder="e.g. 1735689600"></label><button>Create invitation</button><p class="hint">The caregiver must accept through their authenticated account. No sensitive plan content is sent in notifications.</p></form>`):''}</div>`}
  function handoff(){return `<div class="grid">${card('Visit handoff',`<p>Create a date-bounded, patient-generated summary with source citations. Review it before sharing with a care team.</p>${state.me.role==='patient'?`<form id="handoff" class="stack split"><label>From (Unix timestamp)<input name="from_date" required inputmode="numeric"></label><label>To (Unix timestamp)<input name="to_date" required inputmode="numeric"></label><button>Generate handoff</button></form>`:'<p class="hint">Only the patient can generate a handoff.</p>'}`,true)}<section id="handoff-result" class="card wide" hidden></section></div>`}
  function render(){ $('#identity').hidden=false;$('#identity').textContent=`${state.me.role==='patient'?'Patient':'Caregiver'} · private session`;const patient=state.me.role==='patient';const templates={today:patient?patientToday:caregiverToday,plan,track,sharing,handoff};$('#view').innerHTML=templates[state.view]();document.querySelectorAll('.nav [data-view]').forEach(b=>b.setAttribute('aria-current',b.dataset.view===state.view?'page':'false')); }
  async function refresh(message){await load();render();if(message)say(message)}
  document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.view){state.view=b.dataset.view;render();return}if(b.dataset.go){state.view=b.dataset.go;render();return}if(b.id==='signout'){sessionStorage.removeItem('careloopToken');location.reload();return}try{if(b.dataset.approve){await request('/plan/'+encodeURIComponent(b.dataset.approve)+'/approve',{method:'POST'});await refresh('Plan item approved.');}if(b.dataset.complete){await request('/tasks/'+encodeURIComponent(b.dataset.complete)+'/complete',{method:'POST',body:'{}'});await refresh('Task marked complete.');}if(b.dataset.revoke){await request('/grants/'+encodeURIComponent(b.dataset.revoke)+'/revoke',{method:'POST'});await refresh('Caregiver access revoked.');}if(b.dataset.ack){await request('/alerts/'+encodeURIComponent(b.dataset.ack)+'/acknowledge',{method:'POST'});await refresh('Update acknowledged.');}}catch(err){say(err.message)}});
  document.addEventListener('submit',async e=>{e.preventDefault();const f=e.target, d=new FormData(f);try{if(f.id==='signin-form'){sessionStorage.setItem('careloopToken',d.get('token'));await boot();return}if(f.id==='intake'){await request('/documents/text',{method:'POST',body:JSON.stringify({title:d.get('title'),text:d.get('text')})});await refresh('Synthetic plan imported for your review.');}if(f.id==='observation'){await request('/observations',{method:'POST',body:JSON.stringify({pain_score:Number(d.get('pain_score')),idempotency_key:crypto.randomUUID()})});await refresh('Check-in saved.');}if(f.id==='invite'){const expires=String(d.get('expires_at')||'').trim();const data={scopes:[d.get('scope')]};if(expires)data.expires_at=Number(expires);await request('/invitations',{method:'POST',body:JSON.stringify(data)});await refresh('Invitation created. Ask the caregiver to accept it in their private session.');}if(f.id==='handoff'){const out=await request('/handoffs',{method:'POST',body:JSON.stringify({from_date:Number(d.get('from_date')),to_date:Number(d.get('to_date'))})});const h=out.handoff;$('#handoff-result').hidden=false;$('#handoff-result').innerHTML=`<h2>Patient-generated handoff</h2><p class="meta">${esc(h.label||'Date-bounded summary')}</p><pre>${esc(JSON.stringify(h,null,2))}</pre>`;say('Handoff generated with source citations.');}}catch(err){if(f.id==='signin-form')$('#signin-error').textContent='We could not open that private session.';else say(err.message)}});
  async function boot(){try{await load();$('#signin').hidden=true;$('#app').hidden=false;render();say('Private session ready.')}catch(e){$('#signin').hidden=false;$('#app').hidden=true;}}
  if(token())boot();
})();
</script></body></html>"""


class InvitationIn(BaseModel):
    scopes: list[str] = Field(min_length=1)
    expires_at: int | None = None


class DocumentTextIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=24 * 1024)


class CompletionIn(BaseModel):
    completed_at: int | None = Field(default=None, ge=0)

class ObservationIn(BaseModel):
    pain_score: int = Field(ge=0, le=10)
    observed_at: int | None = Field(default=None, ge=0)
    idempotency_key: str = Field(min_length=1, max_length=128)

class HandoffIn(BaseModel):
    from_date: int = Field(ge=0)
    to_date: int = Field(ge=0)


PDF_MAX_BYTES = 2 * 1024 * 1024


def _extract_pdf_text(data: bytes) -> str:
    """Validate PDF bytes before using an optional *local* extractor.

    The base project has no PDF dependency.  In that case PDFs are not
    retained or parsed; the caller is directed to manual review.  This keeps
    a malformed upload from becoming a text fixture by accident.
    """
    if len(data) > PDF_MAX_BYTES:
        raise HTTPException(413, "Document exceeds the upload limit")
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise HTTPException(422, "Invalid PDF bytes")
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
        from io import BytesIO
        reader = PdfReader(BytesIO(data), strict=True)
        if not reader.pages or len(reader.pages) > 20:
            raise HTTPException(422, "PDF page count is unsupported")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ImportError as exc:
        raise HTTPException(422, "PDF extractor is unavailable; manual review required") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "PDF could not be safely extracted") from exc
    if not any(page.strip() for page in pages):
        raise HTTPException(422, "Scanned PDF requires manual review")
    return "\f".join(pages)


def build_router(service: CareLoopService, auth: TokenAuth) -> APIRouter:
    router = APIRouter()

    def current_identity(authorization: Annotated[str | None, Header()] = None) -> Identity:
        try:
            return auth.identity_for_headers({"authorization": authorization or ""})
        except AuthError as exc:
            raise HTTPException(401, "CareLoop authentication required", headers={"WWW-Authenticate": "Bearer"}) from exc

    def denied(call):
        try:
            return call()
        except (AccessDenied, ValueError) as exc:
            # Never include potentially sensitive identifiers or record details in an HTTP error.
            raise HTTPException(403, "CareLoop access denied") from exc

    @router.get("/care", include_in_schema=False, response_class=HTMLResponse)
    def portal() -> str:
        return PORTAL_HTML

    @router.get("/api/care/me")
    def me(identity: Identity = Depends(current_identity)) -> dict[str, str]:
        return {"role": identity.role, "subject_id": identity.subject_id}

    @router.get("/api/care/grants")
    def grants(identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"grants": denied(lambda: service.list_grants(identity))}

    @router.post("/api/care/invitations")
    def invite(body: InvitationIn, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"invitation": denied(lambda: service.invite(identity, body.scopes, body.expires_at))}

    @router.post("/api/care/invitations/{invitation_id}/accept")
    def accept(invitation_id: str, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"grant": denied(lambda: service.accept_invitation(identity, invitation_id))}

    @router.post("/api/care/grants/{invitation_id}/revoke")
    def revoke(invitation_id: str, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"revoked": bool(denied(lambda: service.revoke(identity, invitation_id=invitation_id)))}

    @router.get("/api/care/records")
    def records(record_type: str | None = None, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"records": denied(lambda: service.list_records(identity, record_type))}

    @router.get("/api/care/sources/{source_id}")
    def source(source_id: str, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"source": denied(lambda: service.source_excerpt(identity, source_id))}

    @router.post("/api/care/documents/text")
    @router.post("/api/care/documents")
    def intake_text(body: DocumentTextIn, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        try:
            return {"intake": service.intake_text_document(identity, body.title, body.text)}
        except AccessDenied as exc:
            raise HTTPException(403, "CareLoop access denied") from exc
        except ValueError as exc:
            raise HTTPException(422, "Document needs manual review") from exc

    @router.post("/api/care/documents/pdf")
    async def intake_pdf(request: Request, title: str, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/pdf":
            raise HTTPException(415, "Expected application/pdf")
        length = request.headers.get("content-length")
        if length and int(length) > PDF_MAX_BYTES:
            raise HTTPException(413, "Document exceeds the upload limit")
        data = await request.body()
        try:
            text = _extract_pdf_text(data)
            return {"intake": service.intake_text_document(identity, title, text)}
        except AccessDenied as exc:
            raise HTTPException(403, "CareLoop access denied") from exc

    @router.post("/api/care/plan/{record_id}/approve")
    def approve_plan_item(record_id: str, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        try:
            return {"plan_item": service.approve_plan_item(identity, record_id)}
        except AccessDenied as exc:
            raise HTTPException(403, "CareLoop access denied") from exc
        except ValueError as exc:
            raise HTTPException(422, "Draft plan item is unavailable") from exc

    @router.get("/api/care/tasks")
    def tasks(identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"tasks": denied(lambda: service.list_care_tasks(identity))}

    @router.post("/api/care/tasks/{task_id}/complete")
    def complete_task(task_id: str, body: CompletionIn, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        try:
            return {"completion": service.record_task_completion(identity, task_id, body.completed_at)}
        except AccessDenied as exc:
            raise HTTPException(403, "CareLoop access denied") from exc
        except ValueError as exc:
            raise HTTPException(422, "Active care task is unavailable") from exc

    @router.get("/api/care/observations")
    def observations(from_date: int | None = None, to_date: int | None = None, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"observations": denied(lambda: service.list_observations(identity, from_date=from_date, to_date=to_date))}

    @router.post("/api/care/observations")
    def observation(body: ObservationIn, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        try:
            return {"observation": service.record_observation(identity, pain_score=body.pain_score, observed_at=body.observed_at, idempotency_key=body.idempotency_key)}
        except AccessDenied as exc:
            raise HTTPException(403, "CareLoop access denied") from exc
        except ValueError as exc:
            raise HTTPException(422, "Observation is unavailable") from exc

    @router.post("/api/care/observations/{observation_id}/correct")
    def correct_observation(observation_id: str, body: ObservationIn, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        try:
            return {"observation": service.record_observation(identity, pain_score=body.pain_score, observed_at=body.observed_at, idempotency_key=body.idempotency_key, corrects_id=observation_id)}
        except AccessDenied as exc:
            raise HTTPException(403, "CareLoop access denied") from exc
        except ValueError as exc:
            raise HTTPException(422, "Observation correction is unavailable") from exc

    @router.get("/api/care/history")
    def history(query: str, from_date: int | None = None, to_date: int | None = None, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"records": denied(lambda: service.search(identity, query, from_date=from_date, to_date=to_date))}

    @router.post("/api/care/handoffs")
    def handoff(body: HandoffIn, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        try:
            return {"handoff": service.create_visit_handoff(identity, body.from_date, body.to_date)}
        except AccessDenied as exc:
            raise HTTPException(403, "CareLoop access denied") from exc
        except ValueError as exc:
            raise HTTPException(422, "Handoff date range is invalid") from exc

    @router.get("/api/care/notifications")
    def notifications(identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"notifications": denied(lambda: service.notifications(identity))}

    @router.post("/api/care/alerts/{alert_id}/acknowledge")
    def acknowledge(alert_id: str, identity: Identity = Depends(current_identity)) -> dict[str, Any]:
        return {"acknowledgement": denied(lambda: service.acknowledge_alert(identity, alert_id))}

    return router
