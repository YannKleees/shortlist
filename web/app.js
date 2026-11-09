import { STATUSES, WORK_SETUPS, RELATIONS, EVENT_KINDS, GROUPS, filterJobs, sortJobs, isFollowUpDue, todayISO } from "./logic.js";

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = iso => iso ? new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
const dot = " · ";

let jobs = [], status = null;
const view = { group: "active", query: "" };

async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  if (t.matches(":popover-open")) t.hidePopover();
  t.showPopover();
  clearTimeout(toast.t); toast.t = setTimeout(() => t.hidePopover(), 3000);
}

document.querySelectorAll("dialog").forEach(d => d.addEventListener("click", e => {
  if (e.target.closest("[data-close]") || e.target === d) d.close();
}));

// Status: CV and local model

async function loadStatus() {
  status = await api("/api/status");
  $("#cv-note").hidden = !!status.cv;
  $("#cv-state").innerHTML = status.cv ? esc(status.cv.filename) : `<span class="muted">No CV uploaded</span>`;
}

document.querySelectorAll("[data-cv-input]").forEach(inp => inp.addEventListener("change", async e => {
  const f = e.target.files[0]; e.target.value = "";
  if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api("/api/cv", { method: "POST", body: fd });
    toast(`CV saved: ${r.filename}`);
    loadStatus();
  } catch (err) { toast(err.message); }
}));

// List

// The one thing that matters most about a job right now.
function signal(j) {
  const today = todayISO();
  if (isFollowUpDue(j, today)) return `<span class="bad">Follow up due</span>`;
  if (j.repliedOn) return `<span class="good">Replied ${fmt(j.repliedOn)}</span>`;
  if (j.cvSent) return `<span class="muted">Sent ${fmt(j.appliedOn)}, no reply</span>`;
  if (j.deadline) return `<span class="${j.deadline <= today ? "bad" : "muted"}">Deadline ${fmt(j.deadline)}</span>`;
  return j.fit === "Top pick" ? `<span class="accent">Top pick</span>` : j.fit ? `<span class="muted">${esc(j.fit)}</span>` : "";
}

function row(j) {
  const meta = [j.location, j.workSetup !== "Unknown" && j.workSetup].filter(Boolean).map(esc).join(dot);
  const side = [view.group !== "active" && esc(j.status), j.contactCount && `${j.contactCount} ${j.contactCount === 1 ? "person" : "people"}`].filter(Boolean).join(dot);
  return `<div class="row px-4 sm:px-5 py-3.5 grid sm:grid-cols-[1fr_auto] gap-x-6 gap-y-1" data-id="${esc(j.id)}" role="button" tabindex="0">
    <div class="min-w-0">
      <p class="sm:truncate"><span class="font-medium">${esc(j.company)}</span>${j.role ? `<span class="muted">${dot}${esc(j.role)}</span>` : ""}</p>
      ${meta ? `<p class="text-sm muted truncate">${meta}</p>` : ""}
    </div>
    <div class="text-sm sm:text-right">
      <p>${signal(j)}</p>
      ${side ? `<p class="muted">${side}</p>` : ""}
    </div>
  </div>`;
}

function render() {
  for (const g of Object.keys(GROUPS)) $(`[data-count=${g}]`).textContent = jobs.filter(j => GROUPS[g].includes(j.status)).length;
  document.querySelectorAll("[data-group]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.group === view.group)));
  const due = jobs.filter(j => isFollowUpDue(j)).length;
  $("#due-note").hidden = !due;
  $("#due-note").textContent = `${due} follow up${due === 1 ? "" : "s"} due`;

  const shown = sortJobs(filterJobs(jobs, view));
  $("#list").innerHTML = shown.length ? shown.map(row).join("")
    : jobs.length ? `<p class="p-6 muted">Nothing here.</p>`
    : `<div class="p-8 text-center grid gap-3 justify-items-center">
        <p class="font-medium">No jobs yet</p>
        <p class="muted max-w-sm">Found a job on LinkedIn, Indeed or a company site? Add its link and keep track of it here.</p>
        <button type="button" data-action="add" class="btn btn-primary">Add job</button></div>`;
}

async function loadJobs() {
  jobs = await api("/api/jobs");
  render();
}

document.querySelectorAll("[data-group]").forEach(b => b.addEventListener("click", () => { view.group = b.dataset.group; render(); }));
for (const id of ["#search", "#search-mobile"]) $(id).addEventListener("input", e => { view.query = e.target.value; render(); });

$("#list").addEventListener("click", e => {
  if (e.target.closest("[data-action=add]")) return openAdd();
  const el = e.target.closest("[data-id]");
  if (el) openDetail(el.dataset.id);
});
$("#list").addEventListener("keydown", e => {
  const el = e.target.closest("[data-id]");
  if (el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDetail(el.dataset.id); }
});

// Add a job

function openAdd() {
  const f = $("#link-form"); f.reset(); f.querySelector("[data-error]").textContent = "";
  $("#add-dialog").showModal(); f.url.focus();
}
$("#add-btn").addEventListener("click", openAdd);
$("#manual-btn").addEventListener("click", () => { $("#add-dialog").close(); openJob(null); });

$("#link-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, err = f.querySelector("[data-error]"), btn = f.querySelector("[type=submit]");
  err.textContent = ""; btn.disabled = true; btn.textContent = "Reading";
  try {
    const text = f.text.value.trim();
    if (text && !f.company.value.trim()) throw new Error("Enter the company name for pasted text.");
    const job = await api("/api/jobs/import-link", { method: "POST", json: text ? { url: f.url.value, text, company: f.company.value, role: f.role.value } : { url: f.url.value } });
    $("#add-dialog").close(); await loadJobs();
    openDetail(job.id);
  } catch (ex) { err.textContent = ex.message; }
  btn.disabled = false; btn.textContent = "Add";
});

// Basics: add by hand or edit

const jf = $("#job-form");
jf.workSetup.innerHTML = WORK_SETUPS.map(s => `<option>${s}</option>`).join("");

function openJob(job) {
  jf.reset(); jf.querySelector("[data-error]").textContent = "";
  $("#delete-confirm").hidden = true;
  $("#delete-btn").hidden = !job;
  $("#job-title").textContent = job ? "Edit job" : "Add a job by hand";
  const j = job || { workSetup: "Unknown" };
  for (const el of jf.elements) if (el.name && j[el.name] != null) el.value = j[el.name];
  jf.id.value = job ? job.id : "";
  $("#job-dialog").showModal(); jf.company.focus();
}

jf.addEventListener("submit", async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(jf)), id = data.id;
  delete data.id;
  try {
    const j = id ? await api(`/api/jobs/${id}`, { method: "PATCH", json: data }) : await api("/api/jobs", { method: "POST", json: data });
    $("#job-dialog").close(); await loadJobs();
    openDetail(j.id);
  } catch (ex) { jf.querySelector("[data-error]").textContent = ex.message; }
});
$("#delete-btn").addEventListener("click", () => { $("#delete-confirm").hidden = false; $("#delete-btn").hidden = true; });
$("#delete-no").addEventListener("click", () => { $("#delete-confirm").hidden = true; $("#delete-btn").hidden = false; });
$("#delete-yes").addEventListener("click", async () => {
  await api(`/api/jobs/${jf.id.value}`, { method: "DELETE" });
  $("#job-dialog").close(); $("#detail-dialog").close(); await loadJobs(); toast("Job deleted");
});

// One job

const dd = $("#detail-dialog");
let cur = null;
$("#d-status").innerHTML = STATUSES.map(s => `<option>${s}</option>`).join("");
$("#person-form").relation.innerHTML = RELATIONS.map(s => `<option>${s}</option>`).join("");
$("#event-form").kind.innerHTML = EVENT_KINDS.map(s => `<option>${s}</option>`).join("");

const state = msg => { if (msg) toast(msg); };

function fillDetail(j) {
  cur = j;
  $("#d-company").textContent = j.company;
  $("#d-role").textContent = j.role || "";
  $("#d-meta").textContent = [j.location, j.workSetup !== "Unknown" && j.workSetup, j.source && `via ${j.source}`, j.fit].filter(Boolean).join(dot);
  $("#d-link").hidden = !j.link; $("#d-link").href = j.link || "#";
  $("#d-status").value = j.status;
  $("#d-cv").checked = !!j.cvSent;
  $("#d-due").hidden = !isFollowUpDue(j);
  dd.querySelectorAll("[data-field]").forEach(el => { if (el !== document.activeElement) el.value = j[el.dataset.field] || ""; });
  const n = j.letters?.length || 0;
  $("#d-letter-info").textContent = n ? `${n} draft${n === 1 ? "" : "s"}, last edited ${fmt(j.letters[0].updatedAt)}` : "No draft yet";
  renderPeople(); renderEvents();
}

function renderPeople() {
  const ppl = cur.contacts || [];
  $("#d-people").innerHTML = ppl.length ? ppl.map(c => `<li class="group grid grid-cols-[1fr_auto] gap-x-3 text-sm" data-cid="${c.id}">
      <div class="min-w-0">
        <p><span class="font-medium">${esc(c.name)}</span><span class="muted">${[c.role, c.relation].filter(Boolean).map(x => dot + esc(x)).join("")}</span></p>
        ${c.email || c.linkedin || c.lastContact ? `<p class="muted flex flex-wrap gap-x-3">${c.email ? `<span class="mono select-all">${esc(c.email)}</span>` : ""}${c.linkedin ? `<a class="underline underline-offset-2" href="${esc(c.linkedin)}" target="_blank" rel="noopener">LinkedIn</a>` : ""}${c.lastContact ? `<span>Last contact ${fmt(c.lastContact)}</span>` : ""}</p>` : ""}
        ${c.notes ? `<p class="mt-0.5">${esc(c.notes)}</p>` : ""}
      </div>
      <div class="flex items-start sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
        <button type="button" data-person="edit" class="btn btn-sm btn-quiet">Edit</button>
        <button type="button" data-person="del" class="btn btn-sm btn-quiet">Remove</button>
      </div></li>`).join("")
    : `<li class="text-sm muted">Recruiters you wrote to, and anyone you know there.</li>`;
}

const KIND_CLASS = { Reply: "good", Offer: "good", Rejection: "bad", Applied: "accent", Interview: "accent" };
function renderEvents() {
  const ev = cur.events || [];
  $("#d-events").innerHTML = ev.length ? ev.map(e => `<li class="group grid grid-cols-[4.5rem_1fr_auto] gap-x-3 items-baseline" data-eid="${e.id}">
      <span class="mono muted">${fmt(e.date)}</span>
      <p class="min-w-0"><span class="font-medium ${KIND_CLASS[e.kind] || ""}">${esc(e.kind)}</span>${e.text ? `<span class="muted">${dot}</span>${esc(e.text)}` : ""}</p>
      <button type="button" data-event="del" class="btn btn-sm btn-quiet sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">Remove</button></li>`).join("")
    : `<li class="muted">Emails, messages, calls and replies, with their date.</li>`;
}

async function openDetail(id) {
  state("");
  $("#person-form").hidden = true;
  const f = $("#event-form"); f.reset(); f.date.value = todayISO();
  fillDetail(await api(`/api/jobs/${id}`));
  if (!dd.open) { dd.showModal(); dd.scrollTop = 0; }
}

async function refresh(msg) {
  fillDetail(await api(`/api/jobs/${cur.id}`));
  loadJobs();
  state(msg || "");
}

async function patch(fields, msg = "Saved") {
  try {
    await api(`/api/jobs/${cur.id}`, { method: "PATCH", json: fields });
    await refresh(msg);
  } catch (ex) { state(ex.message); }
}

dd.querySelectorAll("[data-field]").forEach(el => el.addEventListener("change", () => patch({ [el.dataset.field]: el.value })));
$("#d-status").addEventListener("change", e => patch({ status: e.target.value }, `Moved to ${e.target.value}`));
$("#d-cv").addEventListener("change", e => e.target.checked && cur.status === "To apply"
  ? patch({ status: "Applied" }, "Marked as applied. Follow up in 10 days.")
  : patch({ cvSent: e.target.checked ? 1 : 0 }));
$("#d-edit").addEventListener("click", () => openJob(cur));
$("#d-letter").addEventListener("click", () => openLetter(cur));

const pf = $("#person-form");
function openPerson(c) {
  pf.reset(); pf.hidden = false;
  for (const el of pf.elements) if (el.name) el.value = c?.[el.name] ?? (el.name === "relation" ? "Recruiter" : "");
  pf.name.focus();
}
$("#d-add-person").addEventListener("click", () => openPerson(null));
$("#person-cancel").addEventListener("click", () => { pf.hidden = true; });
pf.addEventListener("submit", async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(pf)), cid = data.id;
  delete data.id;
  try {
    if (cid) await api(`/api/contacts/${cid}`, { method: "PATCH", json: data });
    else await api(`/api/jobs/${cur.id}/contacts`, { method: "POST", json: data });
    pf.hidden = true; await refresh(cid ? "Person updated" : "Person added");
  } catch (ex) { state(ex.message); }
});
$("#d-people").addEventListener("click", async e => {
  const b = e.target.closest("[data-person]");
  if (!b) return;
  const cid = Number(b.closest("[data-cid]").dataset.cid);
  if (b.dataset.person === "edit") return openPerson(cur.contacts.find(c => c.id === cid));
  await api(`/api/contacts/${cid}`, { method: "DELETE" }); await refresh("Person removed");
});

$("#event-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target;
  try {
    await api(`/api/jobs/${cur.id}/events`, { method: "POST", json: Object.fromEntries(new FormData(f)) });
    f.text.value = ""; await refresh("Added to the timeline");
  } catch (ex) { state(ex.message); }
});
$("#d-events").addEventListener("click", async e => {
  const b = e.target.closest("[data-event]");
  if (!b) return;
  await api(`/api/events/${b.closest("[data-eid]").dataset.eid}`, { method: "DELETE" }); await refresh("Removed");
});

// Letters

let letterJob = null, letters = [], current = null, dirty = false;

function showLetter(l) {
  current = l; dirty = false;
  $("#letter-text").value = l ? l.text : "";
  for (const [id, f] of [["#letter-txt", "txt"], ["#letter-docx", "docx"]]) {
    const a = $(id);
    a.href = l ? `/api/letters/${l.id}/download?format=${f}` : "#";
    a.classList.toggle("pointer-events-none", !l); a.classList.toggle("opacity-40", !l);
  }
  $("#letter-save").disabled = $("#letter-copy").disabled = !l;
  $("#revise-bar").querySelectorAll("button, input").forEach(el => (el.disabled = !l));
  $("#letter-version").hidden = !letters.length;
  $("#letter-version").innerHTML = letters.map((x, i) =>
    `<option value="${x.id}" ${l && x.id === l.id ? "selected" : ""}>Version ${letters.length - i}${dot}${esc(x.language)}${dot}${fmt(x.updatedAt)}</option>`).join("");
  $("#letter-state").textContent = l ? `Written with ${l.model}` : "";
}

async function openLetter(job) {
  letterJob = job;
  $("#letter-job").textContent = `${job.company}${job.role ? dot + job.role : ""}`;
  letters = await api(`/api/jobs/${job.id}/letters`);
  showLetter(letters[0] || null);
  $("#letter-dialog").showModal();
}

$("#letter-text").addEventListener("input", () => { dirty = true; $("#letter-state").textContent = "Unsaved changes"; });
$("#letter-version").addEventListener("change", e => {
  if (dirty && !confirm("Discard your unsaved edits?")) { e.target.value = current.id; return; }
  showLetter(letters.find(x => String(x.id) === e.target.value));
});
$("#letter-generate").addEventListener("click", async () => {
  if (!status?.cv) { $("#letter-state").textContent = "Upload your CV in Settings first."; return; }
  if (dirty && !confirm("Write a new draft? Unsaved edits to this version are lost.")) return;
  const btn = $("#letter-generate");
  btn.disabled = true; btn.textContent = "Writing";
  $("#letter-state").textContent = `Writing with ${status.llm.model}. This can take a minute on a laptop.`;
  try {
    const l = await api(`/api/jobs/${letterJob.id}/letters`, { method: "POST", json: { language: $("#letter-lang").value, notes: $("#letter-notes").value } });
    letters = [l, ...letters]; showLetter(l);
    if (dd.open) refresh();
  } catch (ex) { $("#letter-state").textContent = ex.message; }
  btn.disabled = false; btn.textContent = "Write draft";
});
$("#letter-save").addEventListener("click", async () => {
  const l = await api(`/api/letters/${current.id}`, { method: "PUT", json: { text: $("#letter-text").value } });
  letters = letters.map(x => (x.id === l.id ? l : x)); showLetter(l); $("#letter-state").textContent = "Saved";
});
async function revise(instruction) {
  if (!current || !instruction.trim()) return;
  const bar = $("#revise-bar");
  bar.querySelectorAll("button, input").forEach(el => (el.disabled = true));
  $("#letter-state").textContent = "Revising. This can take a minute on a laptop.";
  try {
    const l = await api(`/api/letters/${current.id}/revise`, { method: "POST", json: { instruction, text: $("#letter-text").value } });
    letters = [l, ...letters]; showLetter(l); $("#letter-state").textContent = "Saved as a new version";
    if (dd.open) refresh();
  } catch (ex) { $("#letter-state").textContent = ex.message; }
  bar.querySelectorAll("button, input").forEach(el => (el.disabled = false));
}
$("#revise-bar").addEventListener("click", e => { const b = e.target.closest("[data-revise]"); if (b) revise(b.dataset.revise); });
$("#revise-custom").addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); revise(e.target.value); e.target.value = ""; }
});
$("#letter-copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#letter-text").value); toast("Copied"); }
  catch { $("#letter-text").select(); }
});
$("#letter-dialog").addEventListener("cancel", e => { if (dirty && !confirm("Close without saving your edits?")) e.preventDefault(); });

// Settings: model, import

$("#settings-btn").addEventListener("click", () => {
  const f = $("#settings-form"), llm = status?.llm;
  $("#import-state").textContent = "";
  if (llm) {
    f.llm_model.value = llm.model; f.llm_url.value = llm.url;
    $("#model-list").innerHTML = llm.models.map(m => `<option value="${esc(m)}">`).join("");
    $("#settings-state").innerHTML = llm.online
      ? `<span class="good">Running</span><span class="muted">${dot}${llm.models.length} model${llm.models.length === 1 ? "" : "s"}</span>`
      : `<span class="bad">Not reachable</span>`;
  }
  $("#settings-dialog").showModal();
});
$("#settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  await api("/api/settings", { method: "PUT", json: Object.fromEntries(new FormData(e.target)) });
  await loadStatus(); $("#settings-dialog").close(); toast("Settings saved");
});
$("#json-input").addEventListener("change", async e => {
  const st = $("#import-state"), fd = new FormData();
  fd.append("file", e.target.files[0]); e.target.value = "";
  st.className = "text-sm muted"; st.textContent = "Importing";
  try {
    const r = await api("/api/import/json", { method: "POST", body: fd });
    st.textContent = `Added ${r.added}, updated ${r.updated}`;
    loadJobs();
  } catch (ex) { st.className = "text-sm bad"; st.textContent = ex.message; }
});

loadStatus().catch(() => toast("The Shortlist server is not running. Start it with: python -m shortlist"));
loadJobs().catch(() => {});
