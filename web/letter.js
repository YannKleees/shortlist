// The motivation letter for one job, in its own tab: /letter.html?job=<id>

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = iso => iso ? new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
const dot = " · ";
const jobId = new URLSearchParams(location.search).get("job");

let job = null, status = null, letters = [], current = null, dirty = false;

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

function say(msg) { $("#letter-state").textContent = msg; $("#letter-state-m").textContent = msg; }

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
  if (l) $("#letter-lang").value = l.language;
  say(l ? `Written with ${l.model}` : "");
}

async function load() {
  if (!jobId) { say("No job chosen. Open a letter from a job in Shortlist."); return; }
  [job, status, letters] = await Promise.all([api(`/api/jobs/${encodeURIComponent(jobId)}`), api("/api/status"), api(`/api/jobs/${encodeURIComponent(jobId)}/letters`)]);
  const title = `${job.company || "Company unknown"}${job.role ? dot + job.role : ""}`;
  document.title = `Letter · ${job.company || "Shortlist"}`;
  $("#letter-job").textContent = title;
  $("#job-title").textContent = title;
  $("#job-summary").textContent = job.summary || (job.hasText ? "" : "The posting text is missing. Paste it in Shortlist first, so the letter can use it.");
  $("#job-link").hidden = !job.link; $("#job-link").href = job.link || "#";
  $("#job-reasons").innerHTML = (job.reasons || []).map(r =>
    `<li class="grid grid-cols-[1rem_1fr] gap-2"><span class="${r.tone === "ok" ? "warn" : r.tone}">${r.tone === "good" ? "✓" : r.tone === "bad" ? "✕" : "•"}</span><span>${esc(r.note)}</span></li>`).join("");
  showLetter(letters[0] || null);
}

$("#letter-text").addEventListener("input", () => { dirty = true; say("Unsaved changes"); });
$("#letter-version").addEventListener("change", e => {
  if (dirty && !confirm("Discard your unsaved edits?")) { e.target.value = current.id; return; }
  showLetter(letters.find(x => String(x.id) === e.target.value));
});
$("#letter-generate").addEventListener("click", async () => {
  if (!status?.cv) { say("Upload your CV in Shortlist settings first."); return; }
  if (dirty && !confirm("Write a new draft? Unsaved edits to this version are lost.")) return;
  const btn = $("#letter-generate");
  btn.disabled = true; btn.textContent = "Writing";
  say(`Writing with ${status.llm.model}. This can take a minute on a laptop.`);
  try {
    const l = await api(`/api/jobs/${encodeURIComponent(jobId)}/letters`, { method: "POST", json: { language: $("#letter-lang").value, notes: $("#letter-notes").value } });
    letters = [l, ...letters]; showLetter(l);
  } catch (ex) { say(ex.message); }
  btn.disabled = false; btn.textContent = "Write draft";
});
$("#letter-save").addEventListener("click", async () => {
  const l = await api(`/api/letters/${current.id}`, { method: "PUT", json: { text: $("#letter-text").value } });
  letters = letters.map(x => (x.id === l.id ? l : x)); showLetter(l); say("Saved");
});
async function revise(instruction) {
  if (!current || !instruction.trim()) return;
  const bar = $("#revise-bar");
  bar.querySelectorAll("button, input").forEach(el => (el.disabled = true));
  say("Revising. This can take a minute on a laptop.");
  try {
    const l = await api(`/api/letters/${current.id}/revise`, { method: "POST", json: { instruction, text: $("#letter-text").value } });
    letters = [l, ...letters]; showLetter(l); say("Saved as a new version");
  } catch (ex) { say(ex.message); }
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
window.addEventListener("beforeunload", e => { if (dirty) e.preventDefault(); });
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "s" && current) { e.preventDefault(); $("#letter-save").click(); }
});

load().catch(ex => say(ex.message));
