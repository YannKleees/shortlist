// Sift: one page app. Routes live in the hash: #/, #/find, #/job/<id>, #/job/<id>/letter, #/you, #/join/<token>.
import { STATUSES, RELATIONS, GROUPS, WORK_SETUPS, sortJobs, isFollowUpDue, todayISO, addDays, searchJobs, nextAction } from "./logic.js";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = iso => iso ? new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
const plural = (n, word, many = word + "s") => `${n} ${n === 1 ? word : many}`;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const standalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const store = { get: k => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };

const ICONS = {
  find: '<circle cx="12" cy="12" r="8"/><path d="m15.2 8.8-1.8 4.6-4.6 1.8 1.8-4.6z"/>',
  home: '<path d="M4 11.5 12 5l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z"/>',
  car: '<path d="M5 16.5v-3.2l1.6-4.6A1.5 1.5 0 0 1 8 7.7h8a1.5 1.5 0 0 1 1.4 1l1.6 4.6v3.2M4.5 13.3h15M5 16.5h14v1.8h-2.6v-1.8M5 16.5v1.8h2.6v-1.8"/>',
  bike: '<circle cx="6.5" cy="16" r="3.5"/><circle cx="17.5" cy="16" r="3.5"/><path d="M6.5 16 10 9h5l2.5 7M10 9 9 6.5H7M12.5 16 15 9"/>',
  walk: '<circle cx="12.5" cy="5" r="1.6"/><path d="m12 9-3 2.5v3M12 9l3.5 2 2 .5M12 9l-.8 5 2.8 2.5V20M11.2 14 9 20"/>',
  train: '<rect x="6" y="4" width="12" height="12" rx="2.5"/><path d="M6 11h12M9.5 13.8h.01M14.5 13.8h.01M8.5 16 7 20M15.5 16l1.5 4"/>',
  jobs: '<path d="M4 7.5h16v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5z"/><path d="M9 7.5V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1.5M4 12.5h16"/>',
  you: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 19.5c1.2-3.2 3.8-5 7-5s5.8 1.8 7 5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  chev: '<path d="M9 5l7 7-7 7"/>',
  more: '<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  paste: '<rect x="6" y="5" width="12" height="15" rx="2"/><path d="M9 5V4h6v1M9 10h6M9 14h4"/>',
  open: '<path d="M14 5h5v5M19 5l-8 8M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
  edit: '<path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-4-4L4 16z"/>',
  trash: '<path d="M5 7h14M10 11v6M14 11v6M6 7l1 12.5a1.5 1.5 0 0 0 1.5 1.5h7a1.5 1.5 0 0 0 1.5-1.5L18 7M9 7V4.5h6V7"/>',
  letter: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4.5 6.5l7.5 6 7.5-6"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  share: '<path d="M12 4v11M8 8l4-4 4 4M6 12v6.5A1.5 1.5 0 0 0 7.5 20h9a1.5 1.5 0 0 0 1.5-1.5V12"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>',
  inbox: '<path d="M4 13.5l2.2-7.1A2 2 0 0 1 8.1 5h7.8a2 2 0 0 1 1.9 1.4l2.2 7.1V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18z"/><path d="M4 13.5h4.5l1 2h5l1-2H20"/>',
  reply: '<path d="M10 8L5 12.5l5 4.5"/><path d="M5.5 12.5H14a5 5 0 0 1 5 5v1"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5h4"/>',
};
const icon = (name, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

const BRAND_MARK = `<svg class="brand-mark" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5.6" width="14" height="3.1" rx="1.55"/><rect x="8" y="10.6" width="8" height="3.1" rx="1.55"/><circle cx="12" cy="17.6" r="2.1"/></svg>`;
const state = { live: "", ctl: new AbortController(), mails: [], unseen: 0, openMail: false, user: null, needsSetup: false, status: null, jobs: [], loaded: false, group: store.get("group") || "active", job: null, painted: false, lastJob: null };
const isOwner = () => state.user?.role === "owner";
const ownerName = () => state.status?.firstName || "them";

// Talking to the server

async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; }
  let r;
  try { r = await fetch(path, init); } catch { throw new Error("No connection. Check your internet and try again."); }
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && !path.startsWith("/api/auth/")) { state.user = null; route(); }
  if (!r.ok) throw Object.assign(new Error(typeof data.detail === "string" ? data.detail : `Something went wrong (${r.status}).`), { status: r.status });
  return data;
}

// Toasts, sheets, menus

function toast(msg, { action, onAction, ms = 3200 } = {}) {
  const t = $("#toast");
  t.innerHTML = `<span class="msg">${esc(msg)}</span>${action ? `<button class="btn btn-sm" type="button">${esc(action)}</button>` : ""}`;
  if (action) $("button", t).onclick = () => { t.hidePopover(); onAction?.(); };
  if (!t.matches(":popover-open")) t.showPopover();
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.matches(":popover-open") && t.hidePopover(), ms);
}

const sheet = $("#sheet");
function openSheet(html, onOpen) {
  sheet.innerHTML = `<div class="sheet-grip" aria-hidden="true"></div><div class="sheet-body">${html}</div>`;
  if (!sheet.open) sheet.showModal();
  onOpen?.(sheet);
}
const closeSheet = () => sheet.open && sheet.close();
sheet.addEventListener("click", e => { if (e.target === sheet || e.target.closest("[data-close]")) closeSheet(); });

// Drag the sheet down to close it. A quick flick is enough; a slow drag needs to pass a third of the height.
(() => {
  let start = null;
  sheet.addEventListener("pointerdown", e => {
    if (e.pointerType === "mouse" || !e.target.closest(".sheet-grip, .sheet-body > h2") || sheet.scrollTop > 0) return;
    start = { y: e.clientY, t: performance.now() };
    sheet.setPointerCapture(e.pointerId);
    sheet.style.transition = "none";
  });
  sheet.addEventListener("pointermove", e => {
    if (!start) return;
    const dy = e.clientY - start.y;
    sheet.style.transform = `translateY(${dy > 0 ? dy : dy / 6}px)`; // friction when pulled up
  });
  const end = e => {
    if (!start) return;
    const dy = e.clientY - start.y, v = dy / (performance.now() - start.t);
    start = null;
    sheet.style.transition = "";
    sheet.style.transform = "";
    if (dy > sheet.offsetHeight / 3 || v > 0.5) closeSheet();
  };
  sheet.addEventListener("pointerup", end);
  sheet.addEventListener("pointercancel", end);
})();

const menu = $("#menu");
function openMenu(button, items) {
  // Opens next to the button and grows from the corner nearest to it.
  menu.innerHTML = items.map((it, i) => it.href
    ? `<a role="menuitem" href="${esc(it.href)}" target="_blank" rel="noopener">${icon(it.icon)}${esc(it.label)}</a>`
    : `<button role="menuitem" type="button" data-i="${i}" class="${it.danger ? "danger" : ""}">${icon(it.icon)}${esc(it.label)}</button>`).join("");
  const r = button.getBoundingClientRect(), right = r.left > innerWidth / 2;
  Object.assign(menu.style, { top: `${r.bottom + 6}px`, left: right ? "auto" : `${r.left}px`, right: right ? `${innerWidth - r.right}px` : "auto" });
  menu.style.setProperty("--origin", `top ${right ? "right" : "left"}`);
  menu.onclick = e => { const b = e.target.closest("[data-i]"); if (b) { menu.hidePopover(); items[b.dataset.i].run(); } };
  menu.showPopover();
  $("[role=menuitem]", menu)?.focus();
}

// Routing, with a shared element transition between a card and its job page where the browser supports it.

function transition(update) {
  // No animation for the first screen, or where the browser or the person does not want it.
  if (!document.startViewTransition || reduced() || !$("#root .screen")) return update();
  const t = document.startViewTransition(update);
  t.ready.catch(() => {}); // a quick second tap skips the first animation; that is fine
  return t;
}

// Deeper screens slide in from the right and back out to the right; tabs move sideways in tab bar order.
const TAB_ORDER = { jobs: 0, find: 1, inbox: 2, you: 3 };
function setDirection(r) {
  const now = { depth: r.name === "job" ? (r.sub === "letter" ? 2 : 1) : 0, tab: TAB_ORDER[r.name] ?? 0 };
  const was = state.place || now;
  document.documentElement.dataset.nav = now.depth > was.depth ? "forward" : now.depth < was.depth ? "back"
    : now.tab > was.tab ? "right" : now.tab < was.tab ? "left" : "fade";
  state.place = now;
}

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  return { name: parts[0] || "jobs", id: parts[1], sub: parts[2] };
}

async function route() {
  const r = parseRoute();
  // The computer icon opens a one time sign in link; when you are signed in already it is not needed.
  if (r.name === "join" && r.sub === "auto" && state.user) { history.replaceState(null, "", "#/"); return route(); }
  if (r.name === "join") return renderJoin(r.id, r.sub === "auto");
  if (!state.user) return state.needsSetup ? renderSetup() : renderLogin();
  if (r.name === "add") { history.replaceState(null, "", "#/"); renderJobs(); return openAdd(); }
  closeSheet();
  setDirection(r);
  if (r.name === "job" && r.sub === "letter" && isOwner()) return renderLetter(r.id);
  if (r.name === "job") return showJob(r.id);
  // The update itself is synchronous (a skeleton first), so the transition never waits on the network.
  if (r.name === "find" && isOwner()) return transition(() => { renderFind(); });
  if (r.name === "inbox" && isOwner()) return transition(() => { renderInbox(); });
  if (r.name === "you") return transition(() => { renderYou().then(() => r.id && $(`#f-${r.id}`)?.setAttribute("open", "")); });
  return transition(renderJobs);
}
addEventListener("hashchange", route);
const go = hash => { if (location.hash !== hash) location.hash = hash; else route(); };

// The frame around every screen

function frame(active, body) {
  state.ctl.abort(); // listeners of the previous screen go with it
  (state.maps || []).forEach(m => m.remove());
  state.maps = [];
  state.ctl = new AbortController();
  state.screen = active;
  const newFinds = state.status?.finds?.new || 0;
  const badge = key => key === "inbox" ? `<span class="badge num" data-badge ${state.unseen ? "" : "hidden"}>${state.unseen}</span>`
    : key === "find" ? `<span class="nav-count num" data-count-find ${newFinds ? "" : "hidden"}>${newFinds}</span>` : "";
  const nav = (key, href, label) => `<a href="${href}" ${active === key ? 'aria-current="page"' : ""}>${label}${badge(key)}</a>`;
  const tab = (key, href, label, ic) => `<a class="tab" href="${href}" ${active === key ? 'aria-current="page"' : ""}>${icon(ic)}<span>${label}</span>${badge(key)}</a>`;
  const owner = isOwner();
  const inbox = owner && (state.status?.mail?.ready || state.mails.length > 0);  // no Gmail, no Inbox tab
  $("#root").innerHTML = `
    <header class="topbar"><div class="wrap">
      <a class="brand" href="#/">${BRAND_MARK}Sift</a>
      <span class="notch-live small" role="status" ${state.live ? "" : "hidden"}>${esc(state.live || "")}</span>
      <nav class="nav-desktop" aria-label="Main">${nav("jobs", "#/", "Jobs")}${owner ? nav("find", "#/find", "Find") : ""}${inbox ? nav("inbox", "#/inbox", "Inbox") : ""}${nav("you", "#/you", owner ? "You" : "Account")}</nav>
      <button class="notch-add desk-only" type="button" data-add>${icon("plus")}Add job</button>
    </div></header>
    <main class="wrap screen">${body}</main>
    <nav class="tabbar" aria-label="Main">
      ${tab("jobs", "#/", "Jobs", "jobs")}
      ${owner ? tab("find", "#/find", "Find", "find") : ""}
      <button class="tab-add" type="button" data-add aria-label="Add a job">${icon("plus")}</button>
      ${inbox ? tab("inbox", "#/inbox", "Inbox", "inbox") : ""}
      ${tab("you", "#/you", owner ? "You" : "Account", "you")}
    </nav>`;
  $$("[data-add]").forEach(b => b.addEventListener("click", () => openAdd()));
  const dir = document.documentElement.dataset.nav;
  if (!document.startViewTransition && !reduced() && dir && dir !== "fade" && state.painted) $("main.screen").dataset.enter = dir;
  window.scrollTo(0, 0);
}

// What is going on right now, said in the notch: it grows to hold the words and shrinks back when they go.
function setLive(text = "") {
  state.live = text;
  const el = $(".notch-live");
  if (el) { el.textContent = text; el.hidden = !text; }
}

// The number next to Find: jobs that were found and that you have not looked at yet.
function paintFindCount() {
  const n = state.status?.finds?.new || 0;
  $$("[data-count-find]").forEach(el => { el.textContent = n; el.hidden = !n; });
}

// Small motion helpers

// A short burst of confetti from an element, for the moments worth it: applying, an interview, an offer.
function celebrate(el, n = 18) {
  if (!el || reduced()) return;
  const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const colors = ["var(--accent)", "var(--accent-2)", "var(--top)", "var(--maybe)", "var(--good)"];
  for (let i = 0; i < n; i++) {
    const d = document.createElement("i");
    d.className = "confetti";
    d.style.left = `${cx}px`; d.style.top = `${cy}px`; d.style.background = colors[i % colors.length];
    document.body.appendChild(d);
    const a = (Math.PI * 2 * i) / n + Math.random() * 0.5, dist = 60 + Math.random() * 70;
    d.animate([
      { transform: "translate(-50%, -50%) scale(1) rotate(0deg)", opacity: 1 },
      { transform: `translate(calc(-50% + ${Math.cos(a) * dist}px), calc(-50% + ${Math.sin(a) * dist - 30}px)) scale(.9) rotate(${Math.random() * 360}deg)`, opacity: 1, offset: 0.6 },
      { transform: `translate(calc(-50% + ${Math.cos(a) * dist * 1.1}px), calc(-50% + ${Math.sin(a) * dist + 50}px)) scale(.6) rotate(${Math.random() * 540}deg)`, opacity: 0 },
    ], { duration: 900 + Math.random() * 300, easing: "cubic-bezier(.2,.7,.3,1)" }).onfinish = () => d.remove();
  }
}

addEventListener("scroll", () => $(".topbar")?.classList.toggle("scrolled", scrollY > 4), { passive: true });

// Maps: Leaflet is loaded the first time a map is shown

let leaflet;
function loadLeaflet() {
  leaflet ??= new Promise((done, fail) => {
    document.head.append(Object.assign(document.createElement("link"), { rel: "stylesheet", href: "/vendor/leaflet.css" }));
    document.head.append(Object.assign(document.createElement("script"), { src: "/vendor/leaflet.js", onload: () => done(window.L), onerror: fail }));
  });
  return leaflet;
}

function makeMap(L, el, { wheel = false } = {}) {
  const touch = matchMedia("(pointer: coarse)").matches;  // on a phone one finger scrolls the page, two move the map
  const map = L.map(el, { zoomControl: false, scrollWheelZoom: wheel, dragging: !touch, zoomSnap: 0.25, attributionControl: false });
  L.control.attribution({ prefix: false }).addTo(map);
  if (!touch) L.control.zoom({ position: "bottomright" }).addTo(map);
  // OpenStreetMap's own tiles, toned down in CSS so the pins and the route stand out.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  }).addTo(map);
  state.maps.push(map);
  return map;
}

const mins = m => m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
const pinIcon = (L, j, i = 0) => L.divIcon({ className: "", iconSize: [34, 34], iconAnchor: [17, 41],
  html: `<span class="pin ${fitClass(j)}" data-pin="${esc(j.id)}" style="--i:${i}"><b>${typeof j.score === "number" ? j.score : "?"}</b></span>` });
const homeIcon = L => L.divIcon({ className: "", iconSize: [30, 30], iconAnchor: [15, 15], html: `<span class="pin home">${icon("home")}</span>` });

// Jobs

const fitClass = j => typeof j.score !== "number" ? "none" : j.fit === "Top pick" ? "top" : j.fit === "Good" ? "good" : j.fit === "Maybe" ? "maybe" : "low";
const fromWho = j => j.addedBy && !["you", "pipeline"].includes(j.addedBy) ? j.addedBy : "";
// "Luxembourg, Luxembourg, Luxembourg" reads as "Luxembourg".
const place = j => [...new Set(String(j.location || "").split(",").map(x => x.trim()).filter(Boolean))].join(", ");
const km = j => typeof j.distanceKm === "number" ? `${Math.round(j.distanceKm)} km` : "";
// The fit as a number in a box. How full the box is says how good the fit is: solid, outlined, thin, dashed.
const scoreBadge = (j, size = "", extra = "") => {
  const n = typeof j.score === "number" ? j.score : null;
  return `<span class="score ${size} ${n === null ? "none" : fitClass(j)}" ${extra} role="img" aria-label="Fit ${n ?? "unknown"} of 100"><b>${n ?? "?"}</b></span>`;
};
const ago = iso => {
  if (!iso) return "";
  const d = Math.floor((Date.now() - new Date(iso.slice(0, 10) + "T12:00:00")) / 864e5);
  return d <= 0 ? "today" : d === 1 ? "yesterday" : d < 30 ? `${d} days ago` : "over a month ago";
};

const byCar = j => state.travel?.[j.id] ? `${mins(state.travel[j.id])} by car` : "";
const cardMeta = j => [place(j), byCar(j) || km(j), j.workSetup !== "Unknown" && j.workSetup, j.salary].filter(Boolean).map(esc).join(" · ");

function card(j, i) {
  const meta = cardMeta(j);
  const fresh = state.mails.some(m => !m.seen && m.jobId === j.id);
  const act = fresh ? { text: "New mail", tone: "top" }
    : isOwner() ? nextAction(j) : { text: j.status === "To apply" ? "" : j.status, tone: j.status === "Interview" ? "top" : "" };
  const who = fromWho(j);
  const vt = state.lastJob === j.id;
  const name = n => vt ? `style="view-transition-name: ${n}"` : "";
  return `<a class="card" href="#/job/${encodeURIComponent(j.id)}" data-id="${esc(j.id)}" style="--i:${i}">
    <span class="who">
      <span class="company" ${name("job-company")}>${esc(j.role || j.company || "Job")}</span>
      ${j.role ? `<span class="role">${esc(j.company || "Company unknown")}</span>` : ""}
      ${meta || who ? `<span class="meta">${meta}${who ? `${meta ? " · " : ""}from ${esc(who)}` : ""}</span>` : ""}
      ${act.text ? `<span class="signal ${act.tone}">${esc(act.text)}</span>` : ""}
    </span>
    ${scoreBadge(j, "", name("job-score"))}
  </a>`;
}

function summaryLine() {
  const due = state.jobs.filter(j => isFollowUpDue(j)).length;
  const waiting = state.jobs.filter(j => j.cvSent && !j.repliedOn && GROUPS.progress.includes(j.status)).length;
  if (!state.jobs.length) return "Nothing saved yet.";
  return [state.unseen && `<a href="#/inbox" class="signal top">${plural(state.unseen, "new reply", "new replies")}</a>`, waiting && `${waiting} waiting for an answer`, due && `<span class="signal low">${plural(due, "follow up")} due</span>`]
    .filter(Boolean).map(s => `<span style="white-space:nowrap">${s}</span>`).join(" · ") || "All caught up.";
}

function installHint() {
  if (standalone() || !isIOS() || store.get("hint-install")) return "";
  return `<div class="callout info small" style="display:flex;gap:12px;align-items:start;margin-bottom:14px">
    <span style="flex:1">Put Sift on your Home Screen: tap ${icon("share", "").replace("<svg", '<svg style="width:18px;height:18px;vertical-align:-3px"')} Share, then <b>Add to Home Screen</b>. Then it opens like an app and can send you notifications.</span>
    <button class="btn btn-sm btn-quiet" type="button" data-hide-hint>Hide</button></div>`;
}

const SEARCH_FROM = 6;  // a short list needs no search box

function renderJobs() {
  const owner = isOwner();
  const counts = Object.fromEntries(Object.keys(GROUPS).map(g => [g, state.jobs.filter(j => GROUPS[g].includes(j.status)).length]));
  const head = owner
    ? `<h1 class="title-xl">Jobs</h1><p class="muted" id="summary">${state.loaded ? summaryLine() : "&nbsp;"}</p>`
    : `<h1 class="title-xl">Jobs for ${esc(ownerName())}</h1>
       <p class="muted" style="margin-top:8px">Found something? Tap ${icon("plus").replace("<svg", '<svg style="width:16px;height:16px;vertical-align:-2px"')} to send it. You see how well it fits right away.</p>`;
  frame("jobs", `
    <header class="screen-head">${head}</header>
    ${installHint()}
    ${owner && !state.status?.cv && state.loaded ? onboarding() : ""}
    <div class="home"><div class="map home-map" id="home-map" hidden><div class="canvas"></div></div><div>
    ${state.jobs.length > SEARCH_FROM ? `<div class="search" style="margin-bottom:12px">
      ${icon("search")}
      <input class="field" id="q" type="search" role="combobox" aria-expanded="false" aria-controls="q-list" aria-autocomplete="list"
        autocomplete="off" placeholder="Search company, role or place" aria-label="Search jobs">
      <div class="listbox" id="q-list" role="listbox" hidden></div>
    </div>` : ""}
    ${owner ? `<div class="segments" role="tablist" aria-label="Lists" style="margin-bottom:14px">
      <span class="segment-thumb" aria-hidden="true"></span>
      ${[["active", "To apply"], ["progress", "Applied"], ["done", "Closed"]].map(([g, l]) =>
        `<button class="segment" role="tab" type="button" data-group="${g}" aria-selected="${state.group === g}">${l}<span class="count">${counts[g]}</span></button>`).join("")}
    </div>` : ""}
    <div id="list" class="list"></div></div></div>`);
  $("[data-hide-hint]")?.addEventListener("click", e => { store.set("hint-install", "1"); e.target.closest(".callout").remove(); });
  $$("[data-group]").forEach(b => b.addEventListener("click", () => switchGroup(b.dataset.group)));
  $("[data-onboard-cv]")?.addEventListener("change", uploadCv);
  if ($("#q")) setupSearch();
  renderList();
  drawHomeMap();
}

// The map of your jobs: a pin per job in the list you are looking at, coloured by fit, and your home.
async function homeMap() {
  if (!$("#home-map")) return;
  try { state.mapData = await api("/api/map"); } catch { return; }
  state.travel = Object.fromEntries(state.mapData.jobs.filter(j => j.minutes).map(j => [j.id, j.minutes]));
  $$("#list .card").forEach(c => { const j = state.jobs.find(x => x.id === c.dataset.id), m = $(".meta", c); if (j && m) m.textContent = cardMeta(j); });
  drawHomeMap();
}

async function drawHomeMap() {
  const box = $("#home-map"), d = state.mapData;
  if (!box || !d) return;
  const shown = new Set((isOwner() ? state.jobs.filter(j => GROUPS[state.group].includes(j.status)) : state.jobs).map(j => j.id));
  const pins = d.jobs.filter(j => shown.has(j.id));
  box.hidden = !pins.length;
  if (box.parentElement.classList.toggle("has-map", pins.length > 0) !== box._had) placeThumb(true);  // the list just changed width
  box._had = pins.length > 0;
  if (!pins.length) return;
  const L = await loadLeaflet();
  if (!box.isConnected) return;
  if (!box._map) { box._map = makeMap(L, $(".canvas", box), { wheel: innerWidth >= 980 }); box._pins = L.layerGroup().addTo(box._map); }
  const map = box._map, pts = [];
  box._pins.clearLayers();
  if (d.home) { L.marker([d.home.lat, d.home.lon], { icon: homeIcon(L), interactive: false, keyboard: false }).addTo(box._pins); pts.push([d.home.lat, d.home.lon]); }
  // Jobs in the same town would sit on top of each other: fan them out in a small circle.
  const same = {};
  pins.forEach(j => { (same[`${j.lat},${j.lon}`] ||= []).push(j); });
  pins.forEach((j, i) => {
    const group = same[`${j.lat},${j.lon}`], k = group.indexOf(j), a = (k / group.length) * 2 * Math.PI;
    const at = group.length > 1 ? [j.lat + 0.006 * Math.cos(a), j.lon + 0.009 * Math.sin(a)] : [j.lat, j.lon];
    const card = () => $(`#list .card[data-id="${CSS.escape(j.id)}"]`);
    L.marker(at, { icon: pinIcon(L, j, i), riseOnHover: true, alt: `${j.company}, fit ${j.score}` }).addTo(box._pins)
      .bindTooltip(`${esc(j.company)}<small>${esc(j.role || "")}${j.minutes ? ` · ${mins(j.minutes)} by car` : ""}</small>`, { className: "tip", direction: "top", offset: [0, -40] })
      .on("click", () => go(`#/job/${encodeURIComponent(j.id)}`))
      .on("mouseover", () => card()?.classList.add("on")).on("mouseout", () => card()?.classList.remove("on"));
    pts.push(at);
  });
  map.invalidateSize();
  map.fitBounds(pts, { padding: [44, 44], maxZoom: 12, animate: false });
}

// Switching lists: the thumb springs over, the cards slide in from the side you moved towards.
function switchGroup(g) {
  if (!isOwner()) return;
  const order = Object.keys(GROUPS), dir = Math.sign(order.indexOf(g) - order.indexOf(state.group));
  state.group = g; store.set("group", g);
  renderList();
  drawHomeMap();
  const list = $("#list");
  if (dir && list && !reduced()) list.animate([{ transform: `translateX(${dir * 36}px)`, opacity: 0 }, { transform: "none", opacity: 1 }],
    { duration: 380, easing: "cubic-bezier(.23,1,.32,1)" });
}

function onboarding() {
  return `<div class="panel" style="margin-bottom:14px">
    <p class="title-md">Three steps to start</p>
    <ol class="steps" style="margin-top:12px">
      <li><span>Upload your CV, so every job gets a fit score and letters use your real experience.
        <label class="btn btn-sm btn-secondary" style="margin-top:8px;cursor:pointer">Upload CV<input type="file" accept=".pdf,.docx,.tex,.zip,.txt,.md" class="sr" data-onboard-cv></label></span></li>
      <li><span>Add a job: tap ${icon("plus").replace("<svg", '<svg style="width:16px;height:16px;vertical-align:-2px"')} and paste a link.</span></li>
      <li><span>Invite your family under <a href="#/you" style="color:var(--accent)">You</a>, so they can send you jobs.</span></li>
    </ol></div>`;
}

function placeThumb(jump = false) {
  const thumb = $(".segment-thumb"), sel = $(`[data-group="${state.group}"]`);
  if (!thumb || !sel) return;
  $$("[data-group]").forEach(b => b.setAttribute("aria-selected", String(b === sel)));
  if (jump || !thumb.style.width) { thumb.style.transition = "none"; requestAnimationFrame(() => requestAnimationFrame(() => { thumb.style.transition = ""; })); }
  thumb.style.width = `${sel.offsetWidth}px`;
  thumb.style.transform = `translateX(${sel.offsetLeft}px)`;
}
addEventListener("resize", () => placeThumb(true));

function renderList() {
  const list = $("#list");
  if (!list) return;
  placeThumb();
  if (!state.loaded) { list.innerHTML = '<div class="skeleton"></div>'.repeat(4); return; }
  const shown = isOwner()
    ? sortJobs(state.jobs.filter(j => GROUPS[state.group].includes(j.status)))
    : [...state.jobs].sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
  list.classList.toggle("stagger", !state.painted && !reduced());
  state.painted = true;
  list.innerHTML = shown.length ? shown.map(card).join("") : emptyState();
  $("[data-empty-add]", list)?.addEventListener("click", () => openAdd());
  $$(".card", list).forEach(a => {
    const pin = () => $(`[data-pin="${CSS.escape(a.dataset.id)}"]`);
    a.addEventListener("pointerenter", () => pin()?.classList.add("on"));
    a.addEventListener("pointerleave", () => pin()?.classList.remove("on"));
  });
  $$(".card", list).forEach(a => a.addEventListener("click", () => {
    // Name the clicked card's score and company so they morph into the job page. Only one element may carry a name.
    $$(".card .score, .card .company", list).forEach(el => { el.style.viewTransitionName = ""; });
    state.lastJob = a.dataset.id;
    $(".score", a).style.viewTransitionName = "job-score";
    $(".company", a).style.viewTransitionName = "job-company";
  }));
}

function emptyState() {
  if (!state.jobs.length) return `<div class="empty">
    <p class="title-md">${isOwner() ? "No jobs yet" : `Nothing sent to ${esc(ownerName())} yet`}</p>
    <p class="muted">${isOwner() ? "Let Sift look for jobs that fit you, or paste a link from LinkedIn, Indeed or any company site."
      : "Copy a link from LinkedIn, Indeed or any company site and paste it here."}</p>
    <div class="row-actions" style="margin-top:6px">${isOwner() ? `<a class="btn btn-primary" href="#/find">${icon("find")}Find jobs</a>` : ""}
      <button class="btn ${isOwner() ? "btn-secondary" : "btn-primary"}" type="button" data-empty-add>${icon("plus")}Add a job</button></div></div>`;
  const msg = { active: "Nothing left to apply to. Look under Find, or add a job yourself.",
    progress: "No applications yet. When you apply, the job moves here and Sift reminds you to follow up.",
    done: "Jobs you closed, got or turned down end up here." }[state.group];
  return `<div class="empty"><p class="muted">${msg}</p></div>`;
}

function setupSearch() {
  const input = $("#q"), box = $("#q-list");
  let items = [], active = -1;
  const close = () => { box.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); active = -1; };
  const paint = () => {
    $$(".option", box).forEach((o, i) => o.setAttribute("aria-selected", String(i === active)));
    if (active >= 0) input.setAttribute("aria-activedescendant", `opt-${active}`);
  };
  input.addEventListener("input", () => {
    items = searchJobs(state.jobs, input.value);
    active = items.length ? 0 : -1;
    if (!input.value.trim()) return close();
    box.innerHTML = items.length ? items.map((j, i) => `<div class="option" role="option" id="opt-${i}" data-id="${esc(j.id)}">
        ${scoreBadge(j, "sm")}
        <span style="min-width:0"><span style="display:block;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.company)}</span>
        <span class="tiny muted" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.role)}</span></span>
        <span class="tag">${esc(j.status)}</span></div>`).join("")
      : `<p class="small muted" style="padding:12px">No job matches “${esc(input.value.trim())}”.</p>`;
    box.hidden = false; input.setAttribute("aria-expanded", "true"); paint();
  });
  input.addEventListener("keydown", e => {
    if (box.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % Math.max(items.length, 1); paint(); }
    else if (e.key === "Enter" && items[active]) { e.preventDefault(); go(`#/job/${encodeURIComponent(items[active].id)}`); }
    else if (e.key === "Escape") { close(); }
  });
  box.addEventListener("pointerdown", e => { const o = e.target.closest("[data-id]"); if (o) { e.preventDefault(); go(`#/job/${encodeURIComponent(o.dataset.id)}`); } });
  input.addEventListener("blur", () => setTimeout(close, 120));
}

// Mail from companies

const MAIL_KIND = { interview: ["Interview", "top"], reply: ["Reply", "good"], rejection: ["Rejection", "low"], confirmation: ["Received", ""], sent: ["You wrote", ""] };
const mailTag = m => { const [l, c] = MAIL_KIND[m.kind] || [m.kind, ""]; return `<span class="tag ${c}">${l}</span>`; };

async function loadInbox() {
  if (!isOwner()) return;
  const r = await api("/api/mails");
  const grew = r.unseen > state.unseen;
  state.mails = r.mails; state.unseen = r.unseen;
  $$("[data-badge]").forEach(b => { b.textContent = r.unseen; b.hidden = !r.unseen; b.classList.toggle("new", grew); });
  const sum = $("#summary");
  if (sum && state.loaded) sum.innerHTML = summaryLine();
}

async function markSeen(j) {
  j.mails.forEach(m => { m.seen = 1; });
  state.mails.forEach(m => { if (m.jobId === j.id) m.seen = 1; });
  try {
    const r = await api("/api/mails/seen", { method: "POST", json: { jobId: j.id } });
    state.unseen = r.unseen;
    $$("[data-badge]").forEach(b => { b.textContent = r.unseen; b.hidden = !r.unseen; });
  } catch { /* stays unread, no harm */ }
}

function jobMailBody(j) {
  const list = j.mails;
  if (!list) return '<div class="skeleton" style="height:60px"></div>';
  if (!list.length) return `<p class="small muted">${state.status?.mail?.ready ? "No mail with this company yet. Sift checks your inbox every 10 minutes." : 'Connect your Gmail under <a href="#/you/mail" style="color:var(--accent)">You</a> and replies from this company show up here.'}</p>`;
  return list.map(m => {
    const who = m.kind === "sent" ? "You" : esc(m.senderName || m.sender);
    const reply = m.kind !== "sent" && m.sender ? `mailto:${encodeURIComponent(m.sender)}?subject=${encodeURIComponent(/^re:/i.test(m.subject) ? m.subject : `Re: ${m.subject}`)}` : "";
    return `<article class="mail ${m.kind === "sent" ? "out" : ""}">
      <header class="mail-head"><b>${who}</b>${mailTag(m)}<span class="when num">${fmt(m.date)}</span></header>
      ${m.subject ? `<p class="mail-subject">${esc(m.subject)}</p>` : ""}
      ${m.body ? `<p class="mail-text clamp6">${esc(m.body)}</p>${m.body.length > 180 ? `<button class="btn btn-sm btn-quiet" type="button" data-more-mail style="margin-left:-12px">Show all</button>` : ""}` : ""}
      <div class="row-actions" style="margin-top:8px">
        ${reply ? `<a class="btn btn-sm btn-secondary" href="${reply}">${icon("reply")}Reply</a>` : ""}
        ${m.gmail ? `<a class="btn btn-sm btn-quiet" href="${esc(m.gmail)}" target="_blank" rel="noopener">${icon("open")}Open in Gmail</a>` : ""}
      </div></article>`;
  }).join("");
}

async function renderInbox() {
  const ready = state.status?.mail?.ready;
  frame("inbox", `<div class="screen-head" style="display:flex;align-items:end;justify-content:space-between;gap:12px">
      <div><h1 class="title-xl">Inbox</h1><p class="muted">Replies from companies, read from your Gmail.</p></div>
      ${ready ? `<button class="btn btn-secondary btn-sm" type="button" data-check-mail>Check now</button>` : ""}</div>
    ${ready ? "" : `<div class="panel stack" style="margin-bottom:14px"><p class="title-md">Connect your Gmail</p>
      <p class="small muted">Then every reply, interview invitation and rejection lands here and on the job, and your phone gets a notification. Sift only reads your mail.</p>
      <a class="btn btn-primary" href="#/you/mail">Connect Gmail</a></div>`}
    <div id="inbox" class="mail-list">${'<div class="skeleton"></div>'.repeat(3)}</div>`);
  $("[data-check-mail]")?.addEventListener("click", async e => { e.currentTarget.disabled = true; await checkMail(); renderInbox(); }, { signal: state.ctl.signal });
  try { await loadInbox(); } catch (ex) { toast(ex.message); }
  const box = $("#inbox");
  if (!box) return;
  box.classList.add("stagger");
  box.innerHTML = state.mails.length ? state.mails.map((m, i) => `<a class="mail-item ${m.seen ? "" : "unseen"}" href="#/job/${encodeURIComponent(m.jobId)}" data-job="${esc(m.jobId)}" style="--i:${i}">
      <span style="min-width:0;display:grid;gap:2px">
        <span class="mail-head"><b>${esc(m.company || "Company")}</b>${mailTag(m)}<span class="when num">${fmt(m.date)}</span></span>
        <span class="mail-subject">${esc(m.subject || "(no subject)")}</span>
        ${m.body ? `<span class="small muted clamp2">${esc(m.body)}</span>` : ""}
      </span></a>`).join("")
    : `<div class="empty"><p class="title-md">No replies yet</p><p class="muted">When a company answers, it shows up here.</p></div>`;
  $$("[data-job]", box).forEach(a => a.addEventListener("click", () => { state.openMail = true; }));
}

async function loadJobs() {
  state.jobs = await api("/api/jobs");
  state.loaded = true;
  if (parseRoute().name === "jobs" && $("#list")) {
    const counts = Object.fromEntries(Object.keys(GROUPS).map(g => [g, state.jobs.filter(j => GROUPS[g].includes(j.status)).length]));
    $$("[data-group]").forEach(b => { $(".count", b).textContent = counts[b.dataset.group]; });
    if (state.jobs.length > SEARCH_FROM && !$("#q")) return renderJobs();
    const s = $("#summary");
    if (s) s.innerHTML = summaryLine();
    renderList();
    homeMap();
  }
}

async function loadStatus() { state.status = await api("/api/status"); paintFindCount(); }

// Find: jobs Sift looked up for the titles and places you asked for. Open one to see what it is, then save or skip it.

async function renderFind() {
  if (state.screen !== "find") frame("find", `<header class="screen-head"><h1 class="title-xl">Find</h1></header>${'<div class="skeleton"></div>'.repeat(4)}`);
  try { state.finds = await api("/api/finds"); } catch (ex) { toast(ex.message); return; }
  if (parseRoute().name !== "find") return;
  paintFind();
  const stale = !state.finds.at || Date.now() - new Date(state.finds.at) > 12 * 3600e3;
  if (state.finds.ready && stale) searchFinds(); else readAhead();
}

const findMeta = f => {
  const x = f.facts || {};
  return [place(f), ago(f.posted), f.read && x.years ? `asks ${x.years} ${x.years === 1 ? "year" : "years"}` : "",
    f.read && f.workSetup && f.workSetup !== "Unknown" ? f.workSetup : "", f.source ? `on ${f.source}` : ""].filter(Boolean).map(esc).join(" · ");
};

function findRow(f, i = 0) {
  return `<article class="find" data-fid="${esc(f.id)}" style="--i:${i}">
    <button class="find-head" type="button" aria-expanded="false">
      <span class="who"><span class="company">${esc(f.title)}</span><span class="role">${esc(f.company || "Company unknown")}</span>
        <span class="meta">${findMeta(f)}</span></span>
      ${scoreBadge(f)}
    </button>
    <div class="find-body" hidden></div>
  </article>`;
}

function findBody(f) {
  const x = f.facts || {};
  const rows = (f.reasons || []).filter(r => ["field", "level", "experience", "degree", "languages", "distance"].includes(r.key));
  return `${f.read ? "" : `<p class="small muted">The posting could not be read, so this is a guess from the title.</p>`}
    ${x.tasks?.length ? `<h3 class="label">What you would do</h3><ul class="tasks">${x.tasks.slice(0, 4).map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    ${x.mix?.length ? `<h3 class="label">What kind of work it is</h3>${mixBar(x.mix)}` : ""}
    ${rows.length ? `<h3 class="label">How it fits you</h3><ul class="spec">${rows.map(specRow).join("")}</ul>` : ""}
    <div class="row-actions"><button class="btn btn-primary" type="button" data-save>${icon("plus")}Save to my jobs</button>
      <button class="btn btn-secondary" type="button" data-skip>Not for me</button>
      <a class="btn btn-quiet" href="${esc(f.link)}" target="_blank" rel="noopener">${icon("open")}Posting</a></div>`;
}

function paintFind() {
  const d = state.finds;
  const want = d.ready ? `${d.roles.join(", ")}${d.where.length ? ` in ${d.where.join(", ")}` : ""}` : "";
  frame("find", `
    <header class="screen-head"><h1 class="title-xl">Find</h1>
      <p class="muted">${d.ready ? `${esc(want)}. <a class="link" href="#/you/profile">Change</a>` : "Say which jobs you want, and Sift looks for them and tells you how each one fits."}</p></header>
    ${d.ready ? `<div class="find-bar"><span class="small muted" id="find-note">${findNote()}</span>
        <button class="btn btn-secondary btn-sm" type="button" data-search>Search again</button></div>
      <div id="finds" class="list">${findList()}</div>${findSources()}`
    : `<a class="btn btn-primary" href="#/you/profile">Say what you are looking for</a>`}`);
  $("[data-search]")?.addEventListener("click", searchFinds);
  $("#finds")?.addEventListener("click", onFindClick);
}

const findNote = () => {
  const d = state.finds, n = d.items.length;
  return n ? `${plural(n, "job")} to look at, best fit first${d.at ? ` · searched ${ago(d.at)}` : ""}` : d.at ? `Searched ${ago(d.at)}` : "";
};
// Where the last search looked: every site with how many jobs it gave, and the ones that did not answer.
const findSources = () => {
  const all = Object.entries(state.finds.sources || {});
  if (!all.length) return "";
  const gave = all.filter(([, s]) => s.ok).map(([name, s]) => `${esc(name)} ${s.found}`).join(" · ");
  const down = all.filter(([, s]) => !s.ok).map(([name]) => esc(name));
  return `<p class="find-sources small muted">Last search: ${gave || "no site answered"}.${down.length ? ` No answer from ${down.join(", ")}.` : ""}</p>`;
};
const isWeak = f => f.fit === "Stretch";
const findList = () => {
  const items = [...state.finds.items].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  const fits = items.filter(f => !isWeak(f)), weak = items.filter(isWeak);
  if (!items.length) return findEmpty();
  return `${fits.map(findRow).join("") || `<p class="muted" style="padding:18px 0">Nothing that fits well right now.</p>`}
    ${weak.length ? `<details class="weaker" ${fits.length ? "" : "open"}><summary><span><b data-weak-n>${weak.length}</b> more that fit less</span>
        <button class="btn btn-sm btn-quiet" type="button" data-skip-weak>Skip all</button>${icon("chev")}</summary>${weak.map(findRow).join("")}</details>` : ""}`;
};
const findEmpty = () => `<div class="empty"><p class="muted">${state.finds.at ? "Nothing new. You have seen everything that was found." : "Looking for jobs."}</p></div>`;

async function searchFinds() {
  const b = $("[data-search]"), note = $("#find-note");
  if (!b || b.disabled) return;
  b.disabled = true; b.classList.add("busy");
  if (note) note.textContent = "Searching LinkedIn, jobs.lu, EURES and four more job sites for your job titles. This takes about twenty seconds.";
  setLive("Searching 7 sites");
  try {
    const d = await api("/api/finds/search", { method: "POST" }).finally(() => setLive());
    state.finds = d;
    if (state.status) state.status.finds = { new: d.items.length, at: d.at };
    paintFindCount();
    if (parseRoute().name !== "find") { if (d.added) toast(`${plural(d.added, "new job")} found`, { action: "Look", onAction: () => go("#/find") }); return; }
    paintFind();
    toast(d.added ? `${plural(d.added, "new job")} found` : "Nothing new since the last search");
    readAhead();
  } catch (ex) {
    toast(ex.message, { ms: 6000 });
    if (b.isConnected) { b.disabled = false; b.classList.remove("busy"); }
    if (note?.isConnected) note.textContent = findNote();
  }
}

// Read a posting in full: the first guess from the title becomes a real score, with the years and degree asked.
async function readFind(id) {
  const f = state.finds?.items.find(x => x.id === id);
  if (!f || f.read) return f;
  const fresh = await api(`/api/finds/${encodeURIComponent(id)}/read`, { method: "POST" });
  Object.assign(f, fresh);
  const row = $(`.find[data-fid="${CSS.escape(id)}"]`);
  if (row) {
    $(".score", row).outerHTML = scoreBadge(f);
    $(".meta", row).innerHTML = findMeta(f);
  }
  return f;
}

// The best few are read without asking, one at a time, so the list sorts itself out while you look at it.
async function readAhead(n = 6) {
  const run = state.findRun = Symbol("run");
  for (const f of (state.finds?.items || []).filter(x => !x.read).slice(0, n)) {
    if (state.findRun !== run || state.screen !== "find") return;
    try { await readFind(f.id); } catch { /* opened by hand later */ }
    await new Promise(r => setTimeout(r, 900));
  }
  // The real scores are in: put the best fit first again, unless you are reading one right now.
  const list = $("#finds");
  if (state.findRun !== run || !list || $('.find-head[aria-expanded="true"]', list)) return;
  list.innerHTML = findList();
}

async function onFindClick(e) {
  const row = e.target.closest(".find");
  const id = row?.dataset.fid, f = state.finds.items.find(x => x.id === id), body = row && $(".find-body", row), head = row && $(".find-head", row);
  const drop = () => {
    state.finds.items = state.finds.items.filter(x => x.id !== id);
    if (state.status?.finds) state.status.finds.new = state.finds.items.length;
    paintFindCount();
    const weak = row.closest(".weaker");
    row.remove();
    if (weak) { const n = $$(".find", weak).length; if (n) $("[data-weak-n]", weak).textContent = n; else weak.remove(); }
    if (!state.finds.items.length) $("#finds").innerHTML = findList();
    const note = $("#find-note"); if (note) note.textContent = findNote();
  };
  if (e.target.closest("[data-skip-weak]")) {
    e.preventDefault();
    const gone = state.finds.items.filter(isWeak);
    state.finds.items = state.finds.items.filter(f => !isWeak(f));
    if (state.status?.finds) state.status.finds.new = state.finds.items.length;
    paintFindCount();
    $("#finds").innerHTML = findList();
    $("#find-note").textContent = findNote();
    const send = undo => Promise.all(gone.map(f => api(`/api/finds/${encodeURIComponent(f.id)}/skip`, { method: "POST", json: undo ? { undo: true } : {} })));
    send(false).catch(ex => toast(ex.message));
    toast(`Skipped ${plural(gone.length, "job")}.`, { action: "Undo", onAction: async () => {
      await send(true).catch(() => {});
      state.finds.items.push(...gone);
      if (state.status?.finds) state.status.finds.new = state.finds.items.length;
      paintFindCount();
      if (parseRoute().name === "find") paintFind();
    } });
    return;
  }
  if (!row) return;
  if (e.target.closest("[data-save]")) {
    const b = e.target.closest("[data-save]"); b.disabled = true; b.classList.add("busy");
    try {
      const job = await api(`/api/finds/${encodeURIComponent(id)}/save`, { method: "POST" });
      drop(); loadJobs();
      toast(`Saved. Fit ${job.score}.`, { action: "Open", onAction: () => go(`#/job/${encodeURIComponent(job.id)}`) });
    } catch (ex) { toast(ex.message); b.disabled = false; b.classList.remove("busy"); }
    return;
  }
  if (e.target.closest("[data-skip]")) {
    const at = state.finds.items.indexOf(f);
    drop();
    api(`/api/finds/${encodeURIComponent(id)}/skip`, { method: "POST", json: {} }).catch(ex => toast(ex.message));
    toast("Skipped. It will not come back.", { action: "Undo", onAction: async () => {
      await api(`/api/finds/${encodeURIComponent(id)}/skip`, { method: "POST", json: { undo: true } }).catch(() => {});
      state.finds.items.splice(at, 0, f);
      if (parseRoute().name === "find") paintFind();
    } });
    return;
  }
  if (!e.target.closest(".find-head")) return;
  const open = head.getAttribute("aria-expanded") !== "true";
  head.setAttribute("aria-expanded", String(open));
  body.hidden = !open;
  if (!open) return;
  if (!f.read) {
    body.innerHTML = `<p class="small muted">Reading the posting.</p>`;
    try { await readFind(id); } catch { /* shown as a guess */ }
  }
  if (body.isConnected) body.innerHTML = findBody(f);
}

// Adding a job: one box for a link, a list of links, or the job text

function openAdd(prefill = "") {
  const owner = isOwner();
  const canPaste = !!navigator.clipboard?.readText;
  openSheet(`
    <h2 id="sheet-title" class="title-lg">Add a job</h2>
    <p class="muted" style="margin-top:-8px">Paste a link from LinkedIn, Indeed or any website. A list of links, or the whole job text, works too.</p>
    <form class="form" id="add-form">
      <textarea class="field" name="text" rows="3" placeholder="https://" aria-label="Link or job text" autocapitalize="off" autocorrect="off" spellcheck="false">${esc(prefill)}</textarea>
      ${owner ? "" : `<details><summary class="small muted" style="cursor:pointer;min-height:32px;display:flex;align-items:center">Add a message for ${esc(ownerName())}</summary>
        <input class="field" name="note" placeholder="For example: this one is close to home" style="margin-top:8px"></details>`}
      <p class="error" data-error role="alert"></p>
      <div class="row-actions">
        ${canPaste ? `<button class="btn btn-secondary btn-lg" type="button" data-paste>${icon("paste")}Paste</button>` : ""}
        <button class="btn btn-primary btn-lg" type="submit">Add</button>
      </div>
    </form>
    <div id="add-results"></div>
    <p class="hint">How to copy a link: on LinkedIn or Indeed tap <b>Share</b>, then <b>Copy link</b>. Then come back here and tap Paste.</p>`, s => {
    const f = $("#add-form", s);
    if (!prefill && !matchMedia("(pointer: coarse)").matches) f.text.focus();
    f.addEventListener("submit", e => { e.preventDefault(); submitAdd(f); });
    $("[data-paste]", s)?.addEventListener("click", async () => {
      try {
        const t = (await navigator.clipboard.readText()).trim();
        if (!t) return toast("Nothing copied yet. Copy a link first.");
        f.text.value = t;
        submitAdd(f);
      } catch { f.text.focus(); toast("Press and hold in the box, then tap Paste."); }
    });
  });
}

async function submitAdd(f) {
  const err = $("[data-error]", f), btn = $("[type=submit]", f), text = f.text.value.trim();
  err.textContent = "";
  if (!text) { err.textContent = "Paste a link or the job text first."; return; }
  btn.disabled = true; btn.classList.add("busy");
  try {
    const { results } = await api("/api/jobs/add", { method: "POST", json: { text, note: f.note?.value || "" } });
    f.text.value = "";
    const label = { added: ["Added", "top"], exists: ["Already saved", ""], improved: ["Updated", "good"] };
    $("#add-results").innerHTML = `<p class="label" style="margin-bottom:4px">${results.length > 1 ? plural(results.length, "job") : "Done"}</p>` + results.map(({ job, outcome }) =>
      `<a class="result" href="#/job/${encodeURIComponent(job.id)}" style="--i:${results.indexOf(results.find(r => r.job === job))}">${scoreBadge(job)}
        <span style="min-width:0"><b style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(job.company || "Company unknown")}</b>
        <span class="small muted" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(job.role || job.fit || "")}</span></span>
        <span class="tag ${label[outcome][1]}">${label[outcome][0]}</span></a>`).join("");
    if (results.length === 1 && results[0].outcome !== "exists") toast(results[0].job.fit ? `${results[0].job.fit}: fit ${results[0].job.score}` : "Saved");
    loadJobs();
  } catch (ex) { err.textContent = ex.message; }
  btn.disabled = false; btn.classList.remove("busy");
}

// One job

async function showJob(id) {
  const cached = state.jobs.find(j => j.id === id);
  state.lastJob = id;
  if (cached) {
    state.job = { ...cached, contacts: null, events: null, letters: null };
    await transition(renderJob)?.updateCallbackDone;
  } else {
    frame("jobs", '<div class="skeleton" style="height:180px;margin-top:20px"></div>');
  }
  try {
    const j = await api(`/api/jobs/${encodeURIComponent(id)}`);
    if (parseRoute().id !== id) return;
    const first = !cached;
    state.job = j;
    if (first) renderJob(); else refreshJobParts();
  } catch (ex) { toast(ex.message); if (!cached) go("#/"); }
}

const KIND_CLASS = { Reply: "good", Offer: "good", Rejection: "bad", Applied: "accent", Interview: "accent" };

function renderJob() {
  const j = state.job, owner = isOwner();
  const who = fromWho(j);
  const meta = [esc(place(j)), km(j) && `<span data-far>${km(j)} from home</span>`,
    j.workSetup !== "Unknown" && esc(j.workSetup), esc(j.salary), who && `from ${esc(who)}`].filter(Boolean).join(" · ");
  frame("jobs", `
    <div style="display:flex;align-items:center;justify-content:space-between">
      <a class="back" href="#/">${icon("back")}Jobs</a>
      ${owner ? `<button class="icon-btn" type="button" data-more aria-label="More actions" aria-haspopup="menu">${icon("more")}</button>`
        : j.link ? `<a class="btn btn-sm btn-quiet" href="${esc(j.link)}" target="_blank" rel="noopener">${icon("open")}Posting</a>` : ""}
    </div>
    <header class="job-head">
      <h1 class="title-lg" style="view-transition-name: job-company">${esc(j.role || j.company || "Job")}</h1>
      ${j.role ? `<p class="title-md muted">${esc(j.company || "Company unknown")}</p>` : ""}
      ${meta ? `<p class="meta">${meta}</p>` : ""}
    </header>
    <div class="stack rise">
      ${fitPanel(j)}
      ${owner ? `<section class="panel next" id="next"></section>` : ""}
      ${j.hasText === false ? needsTextPanel(j) : ""}
      ${briefPanel(j.facts)}
      ${fitsPanel(j)}
      <section class="panel travel" id="travel" hidden></section>
      ${owner ? "" : helperNotePanel(j)}
      ${owner ? `<details class="fold" id="fold-mail" ${state.openMail || state.mails.some(m => !m.seen && m.jobId === j.id) ? "open" : ""} hidden><summary><span class="s-title">Mail</span><span class="s-note" data-note="mail"></span>${icon("chev")}</summary><div class="fold-body" id="mail"></div></details>` : ""}
      ${aboutFold(j)}
      ${owner ? `
        <details class="fold" id="fold-progress"><summary><span class="s-title">Progress</span><span class="s-note num" data-note="dates"></span>${icon("chev")}</summary>
          <div class="fold-body stack"><div id="status-row"></div><div id="dates"></div><div><p class="label" style="margin-bottom:8px">Timeline</p><div id="timeline"></div></div></div></details>
        <details class="fold" id="fold-people" hidden><summary><span class="s-title">People</span><span class="s-note" data-note="people"></span>${icon("chev")}</summary><div class="fold-body" id="people"></div></details>`
      : `<details class="fold" id="fold-timeline" open><summary><span class="s-title">Notes and updates</span><span class="s-note num" data-note="timeline"></span>${icon("chev")}</summary><div class="fold-body" id="timeline"></div></details>`}
    </div>`);
  $(".fit .score")?.style.setProperty("view-transition-name", "job-score");
  $$(".stack.rise > *").forEach((el, i) => el.style.setProperty("--i", i));
  $("[data-more]")?.addEventListener("click", e => openMenu(e.currentTarget, [
    ...(j.link ? [{ label: "Open the posting", icon: "open", href: j.link }] : []),
    { label: "Write a letter", icon: "letter", run: () => go(`#/job/${encodeURIComponent(j.id)}/letter`) },
    { label: "Edit details", icon: "edit", run: () => editJob() },
    { label: "Delete job", icon: "trash", danger: true, run: () => deleteJob() },
  ]));
  bindJob();
  refreshJobParts();
  state.openMail = false;
  jobTravel(j);
}

// Getting there: the way from home on a map, and how long it takes by car, by bike and on foot.
const MODE_NAME = { car: "Car", bike: "Bike", walk: "Walk" };
async function jobTravel(j) {
  let t;
  try { t = await api(`/api/jobs/${encodeURIComponent(j.id)}/travel`); } catch { return; }
  const box = $("#travel");
  if (!box || state.job?.id !== j.id || !t.place) return;
  if (!t.home || !Object.keys(t.modes).length) {
    if (!t.home && isOwner()) { box.hidden = false; box.className = "callout small"; box.innerHTML = `Add your home address under <a href="#/you/profile" style="color:var(--accent-ink);text-decoration:underline">You</a> to see how long it takes to get there.`; }
    return;
  }
  let mode = t.modes.car ? "car" : Object.keys(t.modes)[0];
  const far = $("[data-far]");
  if (far && t.modes.car) far.textContent = `${mins(t.modes.car.minutes)} by car`;
  const gmaps = how => `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(t.homeName)}&destination=${encodeURIComponent(t.placeName)}&travelmode=${how}`;
  box.hidden = false;
  box.innerHTML = `<div class="map"><div class="canvas"></div></div>
    <div class="travel-body">
      <p class="label">From home to ${esc(place(j))}</p>
      <div class="modes" role="group" aria-label="How you travel">${Object.entries(t.modes).map(([k, r]) =>
        `<button class="mode" type="button" data-mode="${k}" aria-pressed="${k === mode}"><span>${icon(k)}${MODE_NAME[k]}</span><b>${mins(r.minutes)}</b><small>${r.km} km</small></button>`).join("")}</div>
      <div class="travel-links"><a href="${esc(gmaps("transit"))}" target="_blank" rel="noopener">${icon("train")}Bus and train times</a>
        <a href="${esc(gmaps("driving"))}" target="_blank" rel="noopener">${icon("open")}Open in Google Maps</a></div>
    </div>`;
  const L = await loadLeaflet();
  if (!box.isConnected) return;
  const map = makeMap(L, $(".canvas", box)), lines = L.layerGroup().addTo(map);
  L.marker([t.home.lat, t.home.lon], { icon: homeIcon(L), interactive: false, keyboard: false }).addTo(map);
  L.marker([t.place.lat, t.place.lon], { icon: pinIcon(L, j), interactive: false, keyboard: false }).addTo(map);
  const draw = () => {
    lines.clearLayers();
    const pts = t.modes[mode].line;
    L.polyline(pts, { className: "route-halo", interactive: false }).addTo(lines);
    const path = L.polyline(pts, { className: "route-line", interactive: false }).addTo(lines).getElement();
    map.fitBounds(pts, { padding: [36, 36], animate: false });
    if (path && !reduced()) {
      path.style.setProperty("--len", path.getTotalLength());
      path.classList.add("draw");
      path.addEventListener("animationend", () => path.classList.remove("draw"), { once: true });  // zooming must not bring the dashes back
    }
  };
  map.invalidateSize();
  draw();
  $$("[data-mode]", box).forEach(b => b.addEventListener("click", () => {
    mode = b.dataset.mode;
    $$("[data-mode]", box).forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    draw();
  }));
}

// The score and, in one line, the main thing for or against the job.
function fitPanel(j) {
  const reasons = j.reasons || [];
  const bad = reasons.filter(r => r.tone === "bad"), good = reasons.filter(r => r.tone === "good");
  const line = typeof j.score !== "number" ? "No score yet." : j.hasText === false ? "A first guess from the title. Paste the job text for a real score."
    : (bad.length ? bad : good).slice(0, 2).map(r => r.note).join(" ");
  return `<section class="fit">${scoreBadge(j, "lg")}
    <div><p class="verdict">${esc(j.fit || "Fit")}</p><p class="small muted" style="margin-top:4px">${esc(line)}</p></div></section>`;
}

// What the job is: the tasks, and what kind of work fills the day, by the words the posting uses.
function mixBar(mix) {
  if (!mix?.length) return "";
  return `<div class="mix">
    <div class="mix-bar" role="img" aria-label="${esc(mix.map(m => `${m.label} ${m.share} percent`).join(", "))}">${mix.map((m, i) => `<i class="m${i}" style="flex:${m.share}"></i>`).join("")}</div>
    <ul class="mix-key">${mix.map((m, i) => `<li><i class="m${i}"></i><span>${esc(m.label)}</span><b>${m.share}%</b></li>`).join("")}</ul></div>`;
}

function briefPanel(f, limit = 5) {
  if (!f || (!f.tasks?.length && !f.mix?.length)) return "";
  return `<section class="sec">
    ${f.tasks?.length ? `<h2 class="label">What you would do</h2><ul class="tasks">${f.tasks.slice(0, limit).map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    ${f.mix?.length ? `<h2 class="label" ${f.tasks?.length ? 'style="margin-top:22px"' : ""}>What kind of work it is</h2>${mixBar(f.mix)}` : ""}
  </section>`;
}

// What the job asks for next to what you have: one row per thing, with the points it gave.
const MARK = { good: "✓", bad: "✕", ok: "–" };
const specRow = r => `<li><span class="k">${esc(r.label)}</span><span class="v">${esc(r.note)}</span>
    <span class="pts">${r.max ? `${r.points}/${r.max}` : r.points ? r.points : ""}</span><span class="mark ${r.tone}" aria-label="${{ good: "fits", bad: "does not fit", ok: "partly" }[r.tone] || ""}">${MARK[r.tone] || ""}</span></li>`;
const skillRows = j => {
  const chips = (list, cls) => list.map(x => `<span class="tag ${cls}">${esc(x)}</span>`).join("");
  return `${j.have?.length ? `<li><span class="k">You have</span><span class="v chips">${chips(j.have, "top")}</span></li>` : ""}
    ${j.need?.length ? `<li><span class="k">You would need</span><span class="v chips">${chips(j.need, "maybe")}</span></li>` : ""}`;
};

function fitsPanel(j) {
  const reasons = j.reasons || [];
  if (!reasons.length && !j.have?.length && !j.need?.length) return "";
  return `<section class="sec"><h2 class="label">How it fits you</h2>
    <ul class="spec">${reasons.map(specRow).join("")}${skillRows(j)}</ul>
    <div id="job-projects">${projectsBlock(j)}</div></section>`;
}

function projectsBlock(j) {
  // Arrives with the full job, after the page is already shown, so it lives in its own slot.
  return j.projects?.length ? `<div style="margin-top:16px"><p class="label" style="margin-bottom:6px">Projects to mention</p>
      <ul class="projects">${j.projects.map((p, i) => `<li style="--i:${i}"><a href="${esc(p.url)}" target="_blank" rel="noopener" title="${esc(p.description)}"><b>${esc(p.name)}</b>${icon("open")}</a>
        <div class="chips">${p.matched.map(m => `<span class="tag top">${esc(m)}</span>`).join("")}</div></li>`).join("")}</ul></div>` : "";
}

function needsTextPanel(j) {
  return `<form class="callout form" id="text-form">
    <div><p style="font-weight:650">This page could not be read</p>
    <p class="small muted">Some sites, like Indeed, block apps. Open the posting, copy the whole job description, and paste it here.</p></div>
    <textarea class="field" name="text" rows="4" placeholder="Paste the job description"></textarea>
    <p class="error" data-error role="alert"></p>
    <div class="row-actions">${j.link ? `<a class="btn btn-secondary" href="${esc(j.link)}" target="_blank" rel="noopener">${icon("open")}Open posting</a>` : ""}
      <button class="btn btn-primary" type="submit">Read it</button></div>
  </form>`;
}

function helperNotePanel(j) {
  return `<form class="panel form" id="note-form">
    <p class="title-md">Tell ${esc(ownerName())} something</p>
    <textarea class="field" name="text" rows="2" placeholder="For example: I know someone who works there"></textarea>
    <button class="btn btn-primary" type="submit">Send note</button>
  </form>`;
}

function aboutFold(j) {
  const owner = isOwner();
  const field = (f, ph) => owner ? `<textarea class="inline prose" data-field="${f}" placeholder="${ph}">${esc(j[f])}</textarea>` : `<p class="prose">${esc(j[f]) || `<span class="faint">${ph}</span>`}</p>`;
  return `<details class="fold" ${owner ? "" : "open"}><summary><span class="s-title">About the job</span><span class="s-note">${esc(j.source || "")}</span>${icon("chev")}</summary>
    <div class="fold-body stack">
      <div><p class="label" style="margin-bottom:6px">The role</p>${field("summary", "What the role is about")}</div>
      <div><p class="label" style="margin-bottom:6px">The company</p>${field("companyAbout", "What the company does")}</div>
      ${owner ? `<div><p class="label" style="margin-bottom:6px">Your notes</p><textarea class="inline prose" data-field="notes" placeholder="Anything worth remembering">${esc(j.notes)}</textarea></div>` : ""}
      ${j.link ? `<a class="btn btn-secondary btn-sm" href="${esc(j.link)}" target="_blank" rel="noopener">${icon("open")}Open the posting</a>` : ""}
    </div></details>`;
}

function nextPanel(j) {
  const today = todayISO(), id = encodeURIComponent(j.id);
  let title, text, actions;
  if (j.status === "To apply") {
    title = "Ready to apply?";
    text = j.deadline ? `Deadline: ${fmt(j.deadline)}${j.deadline < today ? " (passed)" : ""}` : (j.letters?.length ? `${plural(j.letters.length, "letter draft")} ready.` : "Write a letter, send it, then mark it as applied.");
    actions = `<a class="btn btn-secondary" href="#/job/${id}/letter">${icon("letter")}${j.letters?.length ? "Open letter" : "Write letter"}</a>
      <button class="btn btn-primary" type="button" data-do="applied">${icon("check")}I applied</button>`;
  } else if (["Applied", "Waiting"].includes(j.status)) {
    const due = isFollowUpDue(j, today);
    title = j.repliedOn ? `They replied on ${fmt(j.repliedOn)}` : due ? "Time to follow up" : "Waiting for an answer";
    text = [`Applied: ${fmt(j.appliedOn) || "recently"}`, !j.repliedOn && j.followUp && `${due ? "follow up was due" : "follow up"}: ${fmt(j.followUp)}`].filter(Boolean).join(" · ");
    actions = `${!j.repliedOn ? `<button class="btn ${due ? "btn-primary" : "btn-secondary"}" type="button" data-do="nudge">I followed up</button>` : ""}
      <button class="btn btn-secondary" type="button" data-do="replied">They replied</button>
      <button class="btn btn-secondary" type="button" data-do="interview">Interview</button>`;
  } else if (j.status === "Interview") {
    title = "Interview stage"; text = j.nextStep || "Good luck. Note the date and who you meet under Dates and People.";
    actions = `<button class="btn btn-primary" type="button" data-do="offer">Got an offer</button><button class="btn btn-secondary" type="button" data-do="rejected">Rejected</button>`;
  } else {
    title = { Accepted: "You got it", Rejected: "Not this time", "Not interested": "Set aside" }[j.status];
    text = j.status === "Accepted" ? "Congratulations." : "It stays here for your records.";
    actions = `<button class="btn btn-secondary" type="button" data-do="reopen">Move back to To apply</button>`;
  }
  return `<div><p class="title-md">${esc(title)}</p><p class="small muted" style="margin-top:2px">${esc(text)}</p></div>
    <div class="row-actions">${actions}</div>`;
}

const statusRow = j => `<label class="setting-row small" style="min-height:40px"><span class="muted">Status</span>
    <select class="field" data-status style="width:auto;min-height:40px;padding-top:6px;padding-bottom:6px">${STATUSES.map(s => `<option ${s === j.status ? "selected" : ""}>${s}</option>`).join("")}</select></label>`;

function datesBody(j) {
  const date = f => `<input type="date" class="inline num" data-field="${f}" value="${esc(j[f] || "")}">`;
  return `<dl class="facts">
    <dt>Deadline</dt><dd>${date("deadline")}</dd>
    ${j.status === "To apply" ? "" : `<dt>Applied on</dt><dd>${date("appliedOn")}</dd>
    <dt>Follow up on</dt><dd>${date("followUp")}</dd>`}
    <dt>Next step</dt><dd><textarea class="inline" data-field="nextStep" rows="1" placeholder="For example: call on Friday">${esc(j.nextStep)}</textarea></dd>
  </dl>`;
}

function peopleBody(j) {
  const ppl = j.contacts;
  if (!ppl) return '<div class="skeleton" style="height:40px"></div>';
  return `${ppl.length ? `<ul class="stack">${ppl.map(c => `<li class="person" data-cid="${c.id}">
      <div style="min-width:0"><b>${esc(c.name)}</b><span class="muted">${[c.role, c.relation].filter(Boolean).map(x => " · " + esc(x)).join("")}</span>
      <p class="small muted">${[c.email && `<a href="mailto:${esc(c.email)}" style="color:var(--accent)">${esc(c.email)}</a>`,
        c.linkedin && `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener" style="color:var(--accent)">LinkedIn</a>`,
        c.lastContact && `last contact ${fmt(c.lastContact)}`].filter(Boolean).join(" · ")}</p>
      ${c.notes ? `<p class="small">${esc(c.notes)}</p>` : ""}</div>
      <button class="icon-btn" type="button" data-person aria-label="Edit ${esc(c.name)}">${icon("edit")}</button></li>`).join("")}</ul>`
    : ""}`;
}

function timelineBody(j) {
  const ev = j.events;
  if (!ev) return '<div class="skeleton" style="height:40px"></div>';
  const owner = isOwner();
  const list = ev.length ? `<ol class="timeline">${ev.map(e => `<li data-eid="${e.id}">
      <span class="when">${fmt(e.date)}</span>
      <p style="min-width:0"><span class="kind ${KIND_CLASS[e.kind] || ""}">${esc(e.kind)}</span>${e.text ? `<span class="muted"> · </span>${esc(e.text)}` : ""}</p>
      ${owner ? `<button class="icon-btn" type="button" data-del-event aria-label="Remove">${icon("trash")}</button>` : "<span></span>"}</li>`).join("")}</ol>`
    : `<p class="small muted">${owner ? "Emails, calls, replies and interviews, with their date. Your mail adds them by itself once it is connected." : "Nothing yet."}</p>`;
  return list;
}

function refreshJobParts() {
  const j = state.job;
  if (!j || !$("#root .job-head")) return;
  const set = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  const slot = document.getElementById("job-projects");
  if (slot && !slot.children.length && j.projects?.length) slot.innerHTML = projectsBlock(j);
  if (isOwner()) {
    set("next", nextPanel(j));
    if (!$("#status-row :focus")) set("status-row", statusRow(j));
    if (!$("#dates :focus")) set("dates", datesBody(j));
    set("people", peopleBody(j));
    const pf = $("#fold-people");
    if (pf) pf.hidden = !j.contacts?.length;
    const note = (k, v) => { const el = $(`[data-note="${k}"]`); if (el) el.textContent = v; };
    note("dates", j.followUp && GROUPS.progress.includes(j.status) ? `Follow up ${fmt(j.followUp)}` : j.deadline ? `Deadline ${fmt(j.deadline)}` : j.status);
    note("people", j.contacts ? (j.contacts.length ? plural(j.contacts.length, "person", "people") : "None yet") : "");
  }
  set("timeline", timelineBody(j));
  if (isOwner()) {
    set("mail", jobMailBody(j));
    const mf = $("#fold-mail");
    if (mf) mf.hidden = !j.mails?.length;
    const mn = $('[data-note="mail"]'), unread = (j.mails || []).filter(m => !m.seen).length;
    if (mn) mn.innerHTML = j.mails ? (unread ? `<span class="signal top">${plural(unread, "new mail", "new mails")}</span>` : j.mails.length ? plural(j.mails.length, "mail") : "None yet") : "";
    if (unread && $("#fold-mail")?.open) markSeen(j);
  }
  const tn = $('[data-note="timeline"]');
  if (tn) tn.textContent = j.events ? (j.events.length ? plural(j.events.length, "entry", "entries") : "") : "";
}

async function reloadJob(msg) {
  const j = await api(`/api/jobs/${encodeURIComponent(state.job.id)}`);
  state.job = j;
  const i = state.jobs.findIndex(x => x.id === j.id);
  if (i >= 0) state.jobs[i] = { ...state.jobs[i], ...j };
  refreshJobParts();
  if (msg) toast(msg);
}

// Optimistic: the page changes at once, the server catches up, and a failure puts things back.
async function patchJob(fields, msg) {
  const before = { ...state.job };
  Object.assign(state.job, fields);
  if (fields.status === "Applied") Object.assign(state.job, { cvSent: 1, appliedOn: state.job.appliedOn || todayISO(), followUp: state.job.followUp || addDays(todayISO(), 10) });
  refreshJobParts();
  try {
    const j = await api(`/api/jobs/${encodeURIComponent(before.id)}`, { method: "PATCH", json: fields });
    Object.assign(state.job, j);
    const i = state.jobs.findIndex(x => x.id === j.id);
    if (i >= 0) state.jobs[i] = { ...state.jobs[i], ...j };
    refreshJobParts();
    if (msg) toast(msg);
    if (fields.status) reloadJob();
  } catch (ex) { state.job = before; refreshJobParts(); toast(ex.message); }
}

async function logEvent(kind, text = "", msg) {
  const j = state.job;
  j.events = [{ id: "tmp", date: todayISO(), kind, text }, ...(j.events || [])];
  refreshJobParts();
  try { await api(`/api/jobs/${encodeURIComponent(j.id)}/events`, { method: "POST", json: { kind, text, date: todayISO() } }); await reloadJob(msg); }
  catch (ex) { toast(ex.message); reloadJob(); }
}

function bindJob() {
  const root = $("#root"), on = { signal: state.ctl.signal };
  root.addEventListener("change", e => {
    if (e.target.matches("[data-status]")) patchJob({ status: e.target.value }, `Moved to ${e.target.value}`);
    else if (e.target.matches("[data-field]")) patchJob({ [e.target.dataset.field]: e.target.value }, "Saved");
  }, on);
  root.addEventListener("click", async e => {
    const b = e.target.closest("button");
    if (!b) return;
    const act = b.dataset.do;
    if (act === "applied") { celebrate(b); patchJob({ status: "Applied" }, "Marked as applied. Sift reminds you to follow up in 10 days."); }
    if (act === "nudge") logEvent("Email sent", "Follow up", "Logged. Next reminder in a week.");
    if (act === "replied") { await logEvent("Reply", "", "Nice. Noted their reply."); }
    if (act === "interview") { celebrate(b, 14); patchJob({ status: "Interview" }, "Interview! Good luck."); }
    if (act === "offer") { celebrate(b, 36); patchJob({ status: "Accepted" }); logEvent("Offer", "", "Congratulations!"); }
    if (act === "rejected") patchJob({ status: "Rejected" }, "Moved to Closed");
    if (act === "reopen") patchJob({ status: "To apply" }, "Back in To apply");
    if (b.matches("[data-more-mail]")) { b.previousElementSibling.classList.remove("clamp6"); b.remove(); }
    if (b.matches("[data-add-person]")) editPerson(null);
    if (b.matches("[data-person]")) editPerson(state.job.contacts.find(c => c.id === Number(b.closest("[data-cid]").dataset.cid)));
    if (b.matches("[data-del-event]")) {
      const eid = b.closest("[data-eid]").dataset.eid;
      state.job.events = state.job.events.filter(x => String(x.id) !== eid); refreshJobParts();
      api(`/api/events/${eid}`, { method: "DELETE" }).then(() => reloadJob()).catch(ex => toast(ex.message));
    }
  }, on);
  root.addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target, data = Object.fromEntries(new FormData(f));
    if (f.id === "event-form") { f.text.value = ""; return logEvent(data.kind, data.text, "Added to the timeline"); }
    if (f.id === "note-form") {
      if (!data.text.trim()) return;
      const btn = $("[type=submit]", f); btn.disabled = true;
      try {
        await api(`/api/jobs/${encodeURIComponent(state.job.id)}/notes`, { method: "POST", json: { text: data.text } });
        f.reset(); await reloadJob(`Sent to ${ownerName()}`);
      } catch (ex) { toast(ex.message); }
      btn.disabled = false;
    }
    if (f.id === "text-form") {
      const btn = $("[type=submit]", f); btn.disabled = true; btn.textContent = "Reading";
      try {
        await api(`/api/jobs/${encodeURIComponent(state.job.id)}/text`, { method: "POST", json: data });
        state.job = await api(`/api/jobs/${encodeURIComponent(state.job.id)}`);
        renderJob(); toast("Read. The fit is up to date."); loadJobs();
      } catch (ex) { $("[data-error]", f).textContent = ex.message; btn.disabled = false; btn.textContent = "Read it"; }
    }
  }, on);
}

function editJob() {
  const j = state.job;
  const input = (name, label, type = "text", ph = "") => `<label class="field-label">${label}<input class="field" name="${name}" type="${type}" value="${esc(j[name] || "")}" placeholder="${ph}"></label>`;
  openSheet(`<h2 id="sheet-title" class="title-lg">Edit job</h2>
    <form class="form" id="job-form">
      <div class="grid-2">${input("company", "Company")}${input("role", "Role")}</div>
      ${input("link", "Link", "url", "https://")}
      <div class="grid-2">${input("location", "Location")}
        <label class="field-label">Work setup<select class="field" name="workSetup">${WORK_SETUPS.map(s => `<option ${s === j.workSetup ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>
      <div class="grid-2">${input("salary", "Salary", "text", "Not stated")}${input("source", "Found on", "text", "LinkedIn")}</div>
      <p class="error" data-error role="alert"></p>
      <div class="row-actions"><button class="btn btn-secondary" type="button" data-close>Cancel</button><button class="btn btn-primary" type="submit">Save</button></div>
    </form>`, s => $("#job-form", s).addEventListener("submit", async e => {
    e.preventDefault();
    try {
      state.job = { ...state.job, ...await api(`/api/jobs/${encodeURIComponent(j.id)}`, { method: "PATCH", json: Object.fromEntries(new FormData(e.target)) }) };
      closeSheet(); renderJob(); loadJobs(); toast("Saved");
    } catch (ex) { $("[data-error]", e.target).textContent = ex.message; }
  }));
}

function deleteJob() {
  // Gone at once, with a few seconds to undo before the server forgets it.
  const j = state.job;
  state.jobs = state.jobs.filter(x => x.id !== j.id);
  let undone = false;
  go("#/");
  toast(`Deleted ${j.company || "the job"}`, { action: "Undo", ms: 5000, onAction: () => { undone = true; loadJobs(); } });
  setTimeout(() => { if (!undone) api(`/api/jobs/${encodeURIComponent(j.id)}`, { method: "DELETE" }).catch(ex => toast(ex.message)); }, 5200);
}

function editPerson(c) {
  const v = k => esc(c?.[k] || "");
  openSheet(`<h2 id="sheet-title" class="title-lg">${c ? "Edit person" : "Add a person"}</h2>
    <form class="form" id="person-form">
      <div class="grid-2"><label class="field-label">Name<input class="field" name="name" required value="${v("name")}"></label>
        <label class="field-label">How you know them<select class="field" name="relation">${RELATIONS.map(r => `<option ${r === (c?.relation || "Recruiter") ? "selected" : ""}>${r}</option>`).join("")}</select></label></div>
      <div class="grid-2"><label class="field-label">Their role<input class="field" name="role" value="${v("role")}"></label>
        <label class="field-label">Last contact<input class="field num" type="date" name="lastContact" value="${v("lastContact")}"></label></div>
      <div class="grid-2"><label class="field-label">Email<input class="field" type="email" name="email" value="${v("email")}"></label>
        <label class="field-label">LinkedIn<input class="field" type="url" name="linkedin" value="${v("linkedin")}" placeholder="https://"></label></div>
      <label class="field-label">Notes<input class="field" name="notes" value="${v("notes")}"></label>
      <p class="error" data-error role="alert"></p>
      <div class="row-actions">${c ? `<button class="btn btn-quiet btn-danger" type="button" data-remove>Remove</button>` : ""}
        <button class="btn btn-secondary" type="button" data-close>Cancel</button><button class="btn btn-primary" type="submit">Save</button></div>
    </form>`, s => {
    const f = $("#person-form", s);
    if (!c && !matchMedia("(pointer: coarse)").matches) f.name.focus();
    $("[data-remove]", s)?.addEventListener("click", async () => { closeSheet(); await api(`/api/contacts/${c.id}`, { method: "DELETE" }); reloadJob("Removed"); });
    f.addEventListener("submit", async e => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(f));
      try {
        if (c) await api(`/api/contacts/${c.id}`, { method: "PATCH", json: data });
        else await api(`/api/jobs/${encodeURIComponent(state.job.id)}/contacts`, { method: "POST", json: data });
        closeSheet(); $("#fold-people")?.setAttribute("open", ""); reloadJob(c ? "Saved" : "Added");
      } catch (ex) { $("[data-error]", f).textContent = ex.message; }
    });
  });
}

// Letter

async function renderLetter(id) {
  frame("jobs", '<div class="skeleton" style="height:60vh;margin-top:20px"></div>');
  let job, list;
  try { [job, list] = await Promise.all([api(`/api/jobs/${encodeURIComponent(id)}`), api(`/api/jobs/${encodeURIComponent(id)}/letters`)]); }
  catch (ex) { toast(ex.message); return go("#/"); }
  let current = list[0] || null, dirty = false;
  const llm = state.status?.llm || {};
  frame("jobs", `
    <a class="back" href="#/job/${encodeURIComponent(id)}">${icon("back")}${esc(job.company || "Job")}</a>
    <div class="screen-head"><h1 class="title-lg">Motivation letter</h1>
      <p class="muted">${esc(job.role || "")}${job.role ? " · " : ""}written by ${esc(llm.label || current?.model || "your model")} from your CV and this posting.</p></div>
    <div class="stack">
      ${current ? `<details class="fold no-print"><summary><span class="s-title">Write a new draft</span><span class="s-note">${plural(list.length, "version")}</span>${icon("chev")}</summary><div class="fold-body form">` : `<div class="panel form no-print">`}
        <div class="grid-2">
          <label class="field-label">Language<select class="field" id="l-lang">${["English", "French", "German", "Dutch", "Luxembourgish"].map(l => `<option>${l}</option>`).join("")}</select></label>
          <label class="field-label">Anything to stress?<input class="field" id="l-notes" placeholder="For example: my NLP thesis"></label>
        </div>
        <button class="btn btn-primary btn-lg" type="button" id="l-write">${current ? "Write a new draft" : "Write the letter"}</button>
        ${!state.status?.cv ? `<p class="hint">Upload your CV under <a href="#/you" style="color:var(--accent)">You</a> first.</p>` : ""}
        ${job.hasText === false ? `<p class="hint">The job text is missing, so the letter can only use the title. Paste the text on the job page first.</p>` : ""}
      ${current ? "</div></details>" : "</div>"}
      <div id="l-editor"></div>
    </div>`);

  const editor = () => {
    const box = $("#l-editor");
    if (!current) { box.innerHTML = ""; return; }
    box.innerHTML = `
      <div class="setting-row no-print" style="margin-bottom:8px">
        ${list.length > 1 ? `<select class="field" id="l-version" style="width:auto;min-height:40px" aria-label="Version">${list.map((x, i) =>
          `<option value="${x.id}" ${x.id === current.id ? "selected" : ""}>Version ${list.length - i} · ${esc(x.language)} · ${fmt(x.updatedAt)}</option>`).join("")}</select>` : "<span></span>"}
        <span class="small muted" id="l-state" role="status"></span>
      </div>
      <textarea class="field letter-text" id="l-text" aria-label="Letter">${esc(current.text)}</textarea>
      <div class="revise no-print" style="margin-top:10px" role="group" aria-label="Revise">
        ${[["Shorter", "Make it about 30 percent shorter. Keep the strongest points."], ["More formal", "Make the tone more formal and professional."],
           ["More personal", "Make it more personal and specific to this company, using details from the posting."], ["Fix grammar", "Fix grammar, spelling and awkward phrasing only. Change nothing else."]]
          .map(([l, ins]) => `<button class="btn btn-secondary btn-sm" type="button" data-revise="${esc(ins)}">${l}</button>`).join("")}
      </div>
      <input class="field no-print" id="l-custom" placeholder="Or say what to change, then press Enter" style="margin-top:10px">
      <div class="row-actions no-print" style="margin-top:14px">
        <button class="btn btn-secondary" type="button" id="l-copy">${icon("copy")}Copy</button>
        <a class="btn btn-secondary" href="/api/letters/${current.id}/download?format=docx">Word</a>
        <button class="btn btn-primary" type="button" id="l-save">Save</button>
      </div>
      <p class="hint" style="margin-top:12px">Read every sentence before you send it. Models still get details wrong now and then.</p>`;
    $("#l-lang").value = current.language;
    const say = m => { $("#l-state").textContent = m; };
    $("#l-text").addEventListener("input", () => { dirty = true; say("Not saved"); });
    $("#l-version")?.addEventListener("change", e => { current = list.find(x => String(x.id) === e.target.value); dirty = false; editor(); });
    $("#l-save").addEventListener("click", async () => {
      const l = await api(`/api/letters/${current.id}`, { method: "PUT", json: { text: $("#l-text").value } });
      list = list.map(x => x.id === l.id ? l : x); current = l; dirty = false; say("Saved");
    });
    $("#l-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($("#l-text").value); toast("Copied. Paste it into your email."); } catch { $("#l-text").select(); }
    });
    const revise = async ins => {
      if (!ins.trim()) return;
      $$(".revise button").forEach(b => (b.disabled = true)); say("Rewriting");
      try {
        const l = await api(`/api/letters/${current.id}/revise`, { method: "POST", json: { instruction: ins, text: $("#l-text").value } });
        list = [l, ...list]; current = l; dirty = false; editor(); $("#l-state").textContent = "Saved as a new version";
      } catch (ex) { say(""); toast(ex.message); $$(".revise button").forEach(b => (b.disabled = false)); }
    };
    $$("[data-revise]").forEach(b => b.addEventListener("click", () => revise(b.dataset.revise)));
    $("#l-custom").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); revise(e.target.value); } });
  };
  editor();
  $("#l-write").addEventListener("click", async e => {
    if (dirty && !confirm("Write a new draft? Your unsaved changes stay in the old version only if you save first.")) return;
    const b = e.currentTarget; b.disabled = true; b.textContent = "Writing your letter";
    $("#l-text")?.classList.add("writing");
    try {
      const l = await api(`/api/jobs/${encodeURIComponent(id)}/letters`, { method: "POST", json: { language: $("#l-lang").value, notes: $("#l-notes").value } });
      list = [l, ...list]; current = l; dirty = false; editor();
      b.closest("details")?.removeAttribute("open");
    } catch (ex) { toast(ex.message, { ms: 6000 }); $("#l-text")?.classList.remove("writing"); }
    b.disabled = false; b.textContent = "Write a new draft";
  });
}

// You: CV, profile, family, notifications, mail, writing, data

const fold = (id, title, note, body, open = false) => `<details class="fold" id="${id}" ${open ? "open" : ""}>
  <summary><span class="s-title">${title}</span><span class="s-note">${note}</span>${icon("chev")}</summary><div class="fold-body">${body}</div></details>`;

async function renderYou() {
  const owner = isOwner();
  if (state.screen !== "you") frame("you", `<div class="screen-head"><h1 class="title-xl">${esc(state.user.name)}</h1></div>${'<div class="skeleton" style="height:60px;margin-top:10px"></div>'.repeat(5)}`);
  let me = {}, people = [];
  try { [me, people] = await Promise.all([api("/api/me"), owner ? api("/api/people") : []]); if (owner) await loadStatus(); } catch (ex) { toast(ex.message); }
  const st = state.status || {};
  const pushOn = me.push && window.Notification?.permission === "granted";
  const body = owner ? [
    fold("f-cv", "Your CV", st.cv ? (st.review ? `${st.review.score} / 100` : esc(st.cv.filename)) : "Not uploaded", cvBody(st), !st.cv),
    fold("f-github", "GitHub", st.github?.user ? plural(st.github.projects.length, "project") : "Not added", githubBody(st)),
    fold("f-profile", "What you are looking for", st.profile?.roles?.length ? esc(st.profile.roles.join(", ")) : "Tell Sift", profileBody(st), !st.profile?.roles?.length),
    fold("f-family", "Family", people.length > 1 ? plural(people.length - 1, "person", "people") : "Invite someone", familyBody(people)),
    `<p class="label" style="margin:26px 4px 10px">Settings</p>`,
    fold("f-mail", "Email", st.mail?.ready ? (st.mail.last?.ok === false ? "Problem" : "Connected") : "Not connected", mailBody(st)),
    fold("f-push", "Notifications", pushOn ? "On" : "Off", pushBody(pushOn)),
    fold("f-ai", "Letters", esc(st.llm?.provider === "claude" ? "Claude" : "On this computer"), aiBody(st)),
    fold("f-account", "Account", esc(me.name || ""), accountBody(me, true)),
  ].join("") : [
    fold("f-push", "Notifications", pushOn ? "On" : "Off", pushBody(pushOn), true),
    fold("f-account", "Account", esc(me.name || ""), accountBody(me, false)),
  ].join("");
  frame("you", `<div class="screen-head"><h1 class="title-xl">${esc(state.user.name)}</h1>
    ${owner ? "" : `<p class="muted">You help ${esc(ownerName())} find a job. Thank you.</p>`}</div>
    ${installHint()}${body}`);
  bindYou();
}

function cvBody(st) {
  const r = st.review;
  const reviewHtml = r ? `
    <div style="display:flex;gap:16px;align-items:center;margin:4px 0 14px">
      <div class="ring" style="--p:${r.score};--c:${r.score >= 80 ? "var(--top)" : r.score >= 55 ? "var(--accent)" : "var(--low)"}"><span>${r.score}</span></div>
      <div><p style="font-weight:650">${esc(r.verdict)}</p><p class="tiny muted">${esc(st.cv.filename)} · ${fmt(st.cv.uploadedAt)}</p></div>
    </div>
    ${r.fixes?.length ? `<p class="label" style="margin-bottom:6px">To improve</p><ol class="steps" style="margin-bottom:14px">${r.fixes.map(f => `<li><span><b>${esc(f.issue)}.</b> ${esc(f.fix)}</span></li>`).join("")}</ol>` : ""}
    ${r.missing?.length ? `<p class="label" style="margin-bottom:6px">Often asked, missing</p><div class="chips" style="margin-bottom:14px">${r.missing.map(m => `<span class="tag maybe">${esc(m)}</span>`).join("")}</div>` : ""}` : "";
  return `${st.cv ? "" : `<p class="small muted" style="margin-bottom:10px">PDF, Word or LaTeX (also a zip from Overleaf). Sift uses it to score jobs and write letters.</p>`}
    ${reviewHtml}
    <div class="row-actions">
      <label class="btn ${st.cv ? "btn-secondary" : "btn-primary"}" style="cursor:pointer">${st.cv ? "Upload a new CV" : "Upload CV"}<input type="file" accept=".pdf,.docx,.tex,.zip,.txt,.md" class="sr" data-cv></label>
      ${st.cv && st.llm?.online && st.llm.provider === "claude" ? `<button class="btn btn-secondary" type="button" data-deep-review>Deep review</button>` : ""}
    </div>`;
}

function githubBody(st) {
  const g = st.github || {}, list = g.projects || [];
  return `<form class="form" id="github-form">
    <p class="small muted">Your public projects count as skills next to your CV. Each job shows which ones to mention.</p>
    <label class="field-label">GitHub name<input class="field" name="user" value="${esc(g.user || "")}" placeholder="github.com/yourname" autocapitalize="off" spellcheck="false"></label>
    ${list.length ? `<div class="chips">${list.map(p => `<a class="tag" href="${esc(p.url)}" target="_blank" rel="noopener" title="${esc(p.description)}">${esc(p.name)}</a>`).join("")}</div>` : ""}
    <div class="row-actions">${g.user ? `<button class="btn btn-secondary" type="button" data-github-refresh>Read again</button>` : ""}<button class="btn btn-primary" type="submit">Save</button></div></form>`;
}

async function saveGithub(user, b) {
  if (b) { b.disabled = true; b.classList.add("busy"); }
  try {
    const r = user === null ? await api("/api/github/refresh", { method: "POST" }) : await api("/api/github", { method: "PUT", json: { user } });
    toast(r.user ? `Read ${plural(r.projects.length, "project")}. Updated the fit of ${plural(r.rescored, "job")}.` : "GitHub removed");
    loadJobs();
    await renderYouKeep("f-github");
  } catch (ex) { toast(ex.message, { ms: 6000 }); if (b) { b.disabled = false; b.classList.remove("busy"); } }
}

const LEVEL_NAMES = [["intern", "Internship or student job"], ["junior", "Junior or graduate"], ["mid", "Mid level"], ["senior", "Senior"]];

function profileBody(st) {
  const p = st.profile || {};
  return `<form class="form" id="profile-form">
    <label class="field-label">Job titles you want<input class="field" name="roles" value="${esc((p.roles || []).join(", "))}" placeholder="Data Scientist, Data Analyst" autocapitalize="words">
      <span class="hint">Sift searches for these and scores every job against them.</span></label>
    <fieldset class="checks-row"><legend>Level</legend>${LEVEL_NAMES.map(([k, l]) =>
      `<label class="check"><input type="checkbox" name="levels" value="${k}" ${p.levels?.includes(k) ? "checked" : ""}><span>${l}</span></label>`).join("")}</fieldset>
    <div class="grid-2">
      <label class="field-label">Where to look<input class="field" name="where" value="${esc((p.where || []).join(", "))}" placeholder="Luxembourg"></label>
      <label class="field-label">Work setup<select class="field" name="setup">${[["", "No preference"], ["Hybrid", "Hybrid"], ["Remote", "Remote"], ["On site", "On site"]].map(([v, l]) =>
        `<option value="${v}" ${(p.setup || "") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    </div>
    <div class="grid-2">
      <label class="field-label">Years of work experience<input class="field num" name="years" type="number" min="0" max="40" inputmode="numeric" value="${p.years || 0}"></label>
      <label class="field-label">Languages you speak<input class="field" name="languages" value="${esc(st.languages || "")}" placeholder="English, French, German"></label>
    </div>
    <label class="field-label">Home address<input class="field" name="home" value="${esc(st.home || "")}" placeholder="Street, town" autocomplete="street-address"></label>
    ${p.degrees?.length ? `<p class="small muted">Your degrees, read from your CV: ${esc(p.degrees.join(", "))}.</p>` : ""}
    <button class="btn btn-primary" type="submit">Save</button></form>`;
}

const joinLink = token => `${state.status?.publicUrl || location.origin}/#/join/${token}`;
const localOnly = () => !state.status?.publicUrl && /^(localhost|127\.|192\.168\.|10\.)/.test(location.hostname);

function familyBody(people) {
  const others = people.filter(p => p.id !== state.user.id);
  return `<p class="small muted" style="margin-bottom:12px">They can send you jobs and see how well they fit. Nothing else.</p>
    ${localOnly() ? `<p class="callout small" style="margin-bottom:12px">Sift runs only on this computer for now, so their link works only here. Put it online first (see the README).</p>` : ""}
    ${others.length ? `<ul class="stack" style="margin-bottom:14px">${others.map(p => `<li class="setting-row" data-uid="${p.id}">
      <span><b>${esc(p.name)}</b><span class="tiny muted" style="display:block">${p.lastSeen ? `Last here ${fmt(p.lastSeen)}` : "Not joined yet"}</span></span>
      <span style="display:flex;gap:4px"><button class="btn btn-sm btn-secondary" type="button" data-relink>New link</button>
      <button class="icon-btn" type="button" data-remove-person aria-label="Remove ${esc(p.name)}">${icon("trash")}</button></span></li>`).join("")}</ul>` : ""}
    <form class="form" id="invite-form">
      <label class="field-label">Invite someone<input class="field" name="name" placeholder="Their name, for example Mama" required></label>
      <button class="btn btn-primary" type="submit">Create invite link</button>
    </form>`;
}

function shareLinkSheet(name, token, existing) {
  const link = joinLink(token);
  openSheet(`<h2 id="sheet-title" class="title-lg">${existing ? `New sign in link for ${esc(name)}` : `Invite ${esc(name)}`}</h2>
    <p class="muted" style="margin-top:-8px">Send this link to ${esc(name)}, for example on WhatsApp. Opening it signs them in. It works once, for 14 days.</p>
    <div class="copybox"><code>${esc(link)}</code><button class="btn btn-sm btn-secondary" type="button" data-copy>${icon("copy")}Copy</button></div>
    <div class="row-actions">${navigator.share ? `<button class="btn btn-primary btn-lg" type="button" data-share>${icon("share")}Send link</button>` : ""}
      <button class="btn btn-secondary btn-lg" type="button" data-close>Done</button></div>`, s => {
    $("[data-copy]", s).addEventListener("click", async () => { try { await navigator.clipboard.writeText(link); toast("Link copied"); } catch { toast("Select the link and copy it."); } });
    $("[data-share]", s)?.addEventListener("click", () => navigator.share({ title: "Sift", text: `Hi ${name}, with this link you can send me jobs you find:`, url: link }).catch(() => {}));
  });
}

function pushBody(on) {
  const supported = "serviceWorker" in navigator && "PushManager" in window;
  return `<div class="setting-row"><span>Replies, interviews and new jobs on this device.</span>
      <input type="checkbox" class="switch" data-push ${on ? "checked" : ""} ${supported ? "" : "disabled"} aria-label="Notifications"></div>
    ${!supported && isIOS() && !standalone() ? `<p class="callout small" style="margin-top:10px">On an iPhone: tap Share, then Add to Home Screen. Open Sift from there and turn this on.</p>`
      : !supported ? `<p class="hint">This browser cannot show notifications.</p>` : ""}`;
}

function mailBody(st) {
  const m = st.mail || {}, last = m.last || {};
  const state_ = !m.ready ? "" : last.ok === false ? last.message : m.lastCheck ? `Connected, checked ${new Date(m.lastCheck).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "Connected";
  return `<form class="form" id="mail-form">
    <p class="small muted">Sift reads your job Gmail and tells you when a company answers. It only reads, it never sends or deletes.</p>
    <label class="field-label">Gmail address<input class="field" type="email" name="mail_address" value="${esc(m.address || "")}" placeholder="you@gmail.com"></label>
    <label class="field-label">App password<input class="field" type="password" name="mail_password" autocomplete="new-password" placeholder="${m.ready ? "Saved" : "16 letters from Google"}"></label>
    <p class="hint">Not your normal password: make one at <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener" style="color:var(--accent)">myaccount.google.com/apppasswords</a>.</p>
    ${state_ ? `<p class="small ${last.ok === false ? "error" : "muted"}" id="mail-state" role="status">${esc(state_)}</p>` : `<p id="mail-state" hidden></p>`}
    <div class="row-actions">${m.ready ? `<button class="btn btn-secondary" type="button" data-check-mail>Check now</button>` : ""}<button class="btn btn-primary" type="submit">Save</button></div></form>`;
}

function aiBody(st) {
  const l = st.llm || {};
  return `<form class="form" id="ai-form">
    <p class="small ${l.online ? "muted" : "error"}">${l.online ? `Letters are written by ${esc(l.label)}.` : l.provider === "claude" ? "The Claude key does not work. Check it below." : "Ollama is not running on this computer, so letters cannot be written."}</p>
    <label class="field-label">Claude key, for better letters<input class="field" type="password" name="anthropic_key" autocomplete="off" placeholder="${l.claudeKey ? "Saved" : "sk-ant-…"}"></label>
    <p class="hint">Optional, a few cents per letter. Make one at <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener" style="color:var(--accent)">console.anthropic.com</a>.</p>
    <button class="btn btn-primary" type="submit">Save</button></form>`;
}

function accountBody(me, owner) {
  return `<form class="form" id="account-form">
    <label class="field-label">Name<input class="field" name="name" value="${esc(me.name || "")}" autocomplete="name"></label>
    <label class="field-label">${me.hasPassword ? "New password" : "Password, for your phone"}<input class="field" type="password" name="password" autocomplete="new-password" placeholder="At least 8 characters"></label>
    <div class="row-actions"><button class="btn btn-secondary" type="button" data-logout>Sign out</button><button class="btn btn-primary" type="submit">Save</button></div>
    ${owner ? `<p class="hint">Everything is saved in shortlist.db, with a copy every day. <a href="/api/export" download style="color:var(--accent)">Download a copy</a></p>` : ""}</form>`;
}

async function uploadCv(e) {
  const f = e.target.files[0]; e.target.value = "";
  if (!f) return;
  toast("Reading your CV");
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api("/api/cv", { method: "POST", body: fd });
    await loadStatus();
    toast(`CV saved. Score ${r.review.score}. Updated the fit of ${plural(r.rescored, "job")}.`);
    loadJobs();
    if (parseRoute().name === "you") { await renderYou(); $("#f-cv")?.setAttribute("open", ""); } else renderJobs();
  } catch (ex) { toast(ex.message); }
}

function bindYou() {
  const root = $("#root"), on = { signal: state.ctl.signal };
  $("[data-cv]", root)?.addEventListener("change", uploadCv);
  $("[data-deep-review]", root)?.addEventListener("click", async e => {
    const b = e.currentTarget; b.disabled = true; b.textContent = "Reading your CV";
    try { await api("/api/cv/review", { method: "POST", json: { deep: true } }); await renderYou(); $("#f-cv").setAttribute("open", ""); }
    catch (ex) { toast(ex.message, { ms: 6000 }); b.disabled = false; b.textContent = "Try again"; }
  }, on);
  const saveSettings = async (form, msg) => {
    const data = Object.fromEntries(new FormData(form));
    for (const k of ["mail_password", "anthropic_key"]) if (k in data && !data[k]) delete data[k];
    const b = $("[type=submit]", form); b.disabled = true;
    try { state.status = await api("/api/settings", { method: "PUT", json: data }); toast(msg); loadJobs(); }
    catch (ex) { toast(ex.message); }
    b.disabled = false;
  };
  root.addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target;
    if (f.id === "profile-form") {
      const fd = new FormData(f), b = $("[type=submit]", f);
      b.disabled = true;
      try {
        state.status = await api("/api/settings", { method: "PUT", json: { home: fd.get("home"), languages: fd.get("languages"),
          profile: { roles: fd.get("roles"), levels: fd.getAll("levels"), where: fd.get("where"), setup: fd.get("setup"), years: fd.get("years") } } });
        toast("Saved. Every score is updated.", { action: "Find jobs", onAction: () => go("#/find") });
        loadJobs();
      } catch (ex) { toast(ex.message); }
      b.disabled = false;
    }
    if (f.id === "github-form") saveGithub(f.user.value.trim(), $("[type=submit]", f));
    if (f.id === "ai-form") { await saveSettings(f, "Saved"); renderYou().then(() => $("#f-ai").setAttribute("open", "")); }
    if (f.id === "mail-form") { await saveSettings(f, "Saved. Checking your mail"); checkMail(); }
    if (f.id === "invite-form") {
      const name = f.name.value.trim();
      try { const { token } = await api("/api/people/invite", { method: "POST", json: { name } }); f.reset(); shareLinkSheet(name, token, false); renderYouKeep("f-family"); }
      catch (ex) { toast(ex.message); }
    }
    if (f.id === "account-form") {
      const data = Object.fromEntries(new FormData(f));
      try { const u = await api("/api/me", { method: "PUT", json: data }); state.user = { ...state.user, ...u }; f.password.value = ""; toast("Saved"); }
      catch (ex) { toast(ex.message); }
    }
  }, on);
  root.addEventListener("click", async e => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.matches("[data-logout]")) { await api("/api/auth/logout", { method: "POST" }).catch(() => {}); state.user = null; state.jobs = []; state.loaded = false; go("#/"); }
    if (b.matches("[data-relink]")) {
      const li = b.closest("[data-uid]"), name = $("b", li).textContent;
      try { const { token } = await api(`/api/people/${li.dataset.uid}/link`, { method: "POST" }); shareLinkSheet(name, token, true); } catch (ex) { toast(ex.message); }
    }
    if (b.matches("[data-remove-person]")) {
      const li = b.closest("[data-uid]"), name = $("b", li).textContent;
      if (!confirm(`Remove ${name}? They are signed out and cannot send jobs any more. The jobs they sent stay.`)) return;
      try { await api(`/api/people/${li.dataset.uid}`, { method: "DELETE" }); li.remove(); toast(`${name} removed`); } catch (ex) { toast(ex.message); }
    }
    if (b.matches("[data-push-test]")) api("/api/push/test", { method: "POST" }).then(() => toast("Sent. It should arrive in a few seconds.")).catch(ex => toast(ex.message));
    if (b.matches("[data-check-mail]")) checkMail();
    if (b.matches("[data-github-refresh]")) saveGithub(null, b);
    if (b.matches("[data-copy-share]")) { try { await navigator.clipboard.writeText(b.dataset.copyShare); toast("Address copied"); } catch { toast("Select the address and copy it."); } }
  }, on);
  root.addEventListener("change", async e => {
    if (e.target.matches("[data-push]")) {
      const on = e.target.checked;
      try { on ? await enablePush() : await disablePush(); renderYouKeep("f-push"); }
      catch (ex) { e.target.checked = !on; toast(ex.message, { ms: 6000 }); }
    }
    if (e.target.matches("[data-import]")) {
      const fd = new FormData(); fd.append("file", e.target.files[0]); e.target.value = "";
      try { const r = await api("/api/import/json", { method: "POST", body: fd }); toast(`Added ${r.added}, updated ${r.updated}`); loadJobs(); } catch (ex) { toast(ex.message); }
    }
  }, on);
}

async function renderYouKeep(openId) { await renderYou(); $(`#${openId}`)?.setAttribute("open", ""); }

async function checkMail() {
  const done = () => loadInbox().catch(() => {});
  const s = $("#mail-state");
  if (s) s.textContent = "Checking your mail";
  try {
    const r = await api("/api/mail/check", { method: "POST" });
    toast(r.ok ? (r.added || r.applied || r.replies ? `Mail: ${plural(r.added, "new job")}, ${plural(r.applied, "application")}, ${plural(r.replies, "reply", "replies")}` : "Mail checked. Nothing new.") : r.message, { ms: 5000 });
    loadJobs();
  } catch (ex) { toast(ex.message); }
  await done();
  if (parseRoute().name === "you") renderYouKeep("f-mail");
}

// Notifications

const b64ToBytes = s => Uint8Array.from(atob((s + "=".repeat((4 - s.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));

async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("Add Sift to your Home Screen first, then turn this on there.");
  if (!state.status?.vapidKey) throw new Error("The server cannot send notifications yet.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notifications are blocked. Allow them for Sift in your phone's settings.");
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription() || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(state.status.vapidKey) });
  await api("/api/push/subscribe", { method: "POST", json: sub.toJSON() });
  toast("Notifications are on");
}

async function disablePush() {
  const reg = await navigator.serviceWorker?.ready;
  const sub = await reg?.pushManager.getSubscription();
  if (sub) { await api("/api/push/subscribe", { method: "DELETE", json: { endpoint: sub.endpoint } }); await sub.unsubscribe(); }
  toast("Notifications are off");
}

// Sign in, first start, invitations

function gate(html) {
  state.ctl.abort(); state.ctl = new AbortController();
  $("#root").innerHTML = `<main class="gate"><div class="gate-card">${html}</div></main>`;
}
const brandBig = `<span class="brand" style="font-size:22px">${BRAND_MARK}Sift</span>`;

function renderSetup() {
  gate(`${brandBig}
    <div><h1 class="title-xl">Your job search, in one place</h1>
      <p class="muted" style="margin-top:8px">Save jobs from any link, see how well each one fits, write letters, and let your family send you jobs they find.</p></div>
    <form class="form" id="setup-form">
      <label class="field-label">Your name<input class="field" name="name" autocomplete="name" required></label>
      <label class="field-label">Password<input class="field" type="password" name="password" autocomplete="new-password" minlength="8" required placeholder="At least 8 characters"></label>
      <p class="error" data-error role="alert"></p>
      <button class="btn btn-primary btn-lg" type="submit">Start</button></form>`);
  authForm("#setup-form", "/api/auth/setup");
}

function renderLogin() {
  gate(`${brandBig}<div><h1 class="title-xl">Welcome back</h1></div>
    <form class="form" id="login-form">
      <label class="field-label">Name<input class="field" name="name" autocomplete="username" required></label>
      <label class="field-label">Password<input class="field" type="password" name="password" autocomplete="current-password" required></label>
      <p class="error" data-error role="alert"></p>
      <button class="btn btn-primary btn-lg" type="submit">Sign in</button></form>
    <p class="hint">Forgot your password? On your computer, open Sift from its icon: it signs you in, and you can set a new password under You. Family members: ask for a new sign in link.</p>`);
  authForm("#login-form", "/api/auth/login");
}

function authForm(sel, path) {
  $(sel).addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target, b = $("[type=submit]", f);
    b.disabled = true;
    try { const { user } = await api(path, { method: "POST", json: Object.fromEntries(new FormData(f)) }); await signedIn(user); }
    catch (ex) {
      if (ex.status === 409 && path.endsWith("/setup")) {  // the account exists already: sign in instead
        state.needsSetup = false; renderLogin();
        $("#login-form [data-error]").textContent = "Your account exists already. Sign in with it.";
        return;
      }
      $("[data-error]", f).textContent = ex.message; b.disabled = false;
    }
  });
}

async function renderJoin(token, auto = false) {
  gate(`<div class="skeleton" style="height:240px"></div>`);
  let info;
  try { info = await api(`/api/auth/invite/${encodeURIComponent(token)}`); }
  catch (ex) {
    if (auto) { history.replaceState(null, "", "#/"); return route(); }
    gate(`${brandBig}<h1 class="title-lg">This link no longer works</h1><p class="muted">${esc(ex.message)}</p><a class="btn btn-secondary" href="#/">Open Sift</a>`); return;
  }
  if (auto && info.existing) {
    try { const { user } = await api("/api/auth/join", { method: "POST", json: { token } }); history.replaceState(null, "", "#/"); return signedIn(user); }
    catch { history.replaceState(null, "", "#/"); return route(); }
  }
  gate(`${brandBig}
    <div><h1 class="title-xl">Hello ${esc(info.name)}</h1>
      <p class="muted" style="margin-top:8px">${info.existing ? "Tap below to sign in on this device." : `${esc(info.for)} invited you to help with the job search. When you find a job, send it here. You see right away how well it fits.`}</p></div>
    <form class="form" id="join-form">
      ${info.existing ? "" : `<label class="field-label">Your name<input class="field" name="name" value="${esc(info.name)}" required></label>`}
      <p class="error" data-error role="alert"></p>
      <button class="btn btn-primary btn-lg" type="submit">${info.existing ? "Sign in" : "Join"}</button></form>`);
  $("#join-form").addEventListener("submit", async e => {
    e.preventDefault();
    try {
      const { user } = await api("/api/auth/join", { method: "POST", json: { token, name: e.target.name?.value } });
      history.replaceState(null, "", "#/");
      await signedIn(user);
      if (isIOS() && !standalone()) toast("Tip: tap Share, then Add to Home Screen", { ms: 6000 });
    } catch (ex) { $("[data-error]", e.target).textContent = ex.message; }
  });
}

async function signedIn(user) {
  state.user = user; state.loaded = false; state.painted = false;
  await loadStatus().catch(() => {});
  if (location.hash.startsWith("#/join")) history.replaceState(null, "", "#/");
  route();
  loadJobs().catch(ex => toast(ex.message));
  loadInbox().then(() => { if (parseRoute().name === "jobs") renderList(); }).catch(() => {});
}

// Start

async function start() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  // Shared from another app (Android share target) or opened as /?text=...: start adding right away.
  const q = new URLSearchParams(location.search);
  const shared = [q.get("title"), q.get("text"), q.get("url")].filter(Boolean).join("\n");
  if (shared) history.replaceState(null, "", "/#/add");
  try {
    const s = await api("/api/auth/state");
    state.user = s.user; state.needsSetup = s.needsSetup;
  } catch { gate(`${brandBig}<p class="muted">Sift is not reachable. Check your connection and reload.</p>`); return; }
  if (!state.user) return route();
  const status = loadStatus().catch(() => {});
  await route();
  loadJobs().catch(ex => toast(ex.message));
  loadInbox().then(() => { if (parseRoute().name === "jobs") renderList(); }).catch(() => {});
  status.then(() => {
    if (parseRoute().name !== "jobs") return;
    if (isOwner() && !state.status?.cv) return renderJobs();
    const line = $("#summary");
    if (line && state.loaded) line.innerHTML = summaryLine();
  });
  if (shared) openAdd(shared);
}

// Jobs that arrive by mail or from helpers show up when you come back to the app.
document.addEventListener("visibilitychange", () => {
  if (document.hidden || !state.user) return;
  loadJobs().catch(() => {});
  loadInbox().then(() => { if (parseRoute().name === "jobs") renderList(); }).catch(() => {});
  if (parseRoute().name === "job" && !parseRoute().sub && state.job) reloadJob().catch(() => {});
});

start();
