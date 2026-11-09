// Pure functions for Shortlist. No DOM access, so they run in the browser and in Node tests.

export const STATUSES = ["To apply", "Applied", "Waiting", "Interview", "Accepted", "Rejected", "Not interested"];
export const FITS = ["Top pick", "Good", "Maybe", "Stretch"];
export const WORK_SETUPS = ["Hybrid", "Remote", "On site", "Unknown"];
export const TYPES = ["Internship", "Working student", "Job", "Programme"];

export const GROUPS = {
  active: ["To apply"],
  progress: ["Applied", "Waiting", "Interview"],
  done: ["Accepted", "Rejected", "Not interested"],
};

const TEXT_FIELDS = ["company", "role", "location", "source", "pros", "cons", "nextStep", "notes"];
const DATE_FIELDS = ["deadline", "appliedOn", "followUp"];
const FIT_RANK = Object.fromEntries(FITS.map((f, i) => [f, i]));

export const todayISO = (d = new Date()) => d.toISOString().slice(0, 10);

export function addDays(iso, n) {
  const d = new Date(iso + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function slug(s) {
  return String(s || "")
    .toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
    .slice(0, 48) || "job";
}

const keyOf = j => `${(j.company || "").trim().toLowerCase()}|${(j.role || "").trim().toLowerCase()}`;
const str = v => (v == null ? "" : String(v).trim());
const isDate = v => /^\d{4}-\d{2}-\d{2}$/.test(v);
const pick = (v, allowed, fallback) => (allowed.includes(v) ? v : fallback);

export function normalizeJob(raw, now = new Date().toISOString()) {
  if (!raw || typeof raw !== "object") return null;
  const company = str(raw.company);
  if (!company) return null;

  const job = { company };
  for (const f of TEXT_FIELDS) if (f !== "company") job[f] = str(raw[f]);
  for (const f of DATE_FIELDS) job[f] = isDate(str(raw[f])) ? str(raw[f]) : "";

  const link = str(raw.link ?? raw.applyLink);
  job.link = /^https?:\/\/\S+$/i.test(link) ? link : "";

  const score = raw.score === "" || raw.score == null ? NaN : Number(raw.score);
  job.score = Number.isFinite(score) ? Math.min(100, Math.max(0, Math.round(score))) : null;

  job.status = pick(str(raw.status), STATUSES, "To apply");
  job.fit = pick(str(raw.fit), FITS, "");
  job.workSetup = pick(str(raw.workSetup ?? raw.remote).replace(/^Fully remote$/, "Remote"), WORK_SETUPS, "Unknown");
  job.type = pick(str(raw.type), TYPES, "");
  job.addedBy = pick(str(raw.addedBy), ["you", "pipeline"], "you");

  job.createdAt = str(raw.createdAt) || now;
  job.updatedAt = str(raw.updatedAt) || now;
  job.id = str(raw.id) || `${slug(company + " " + job.role)}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  return job;
}

export function parseImport(text, now) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("This file is not valid JSON. Export it again from Shortlist or check the format in the README.");
  }
  const rows = Array.isArray(data) ? data : Array.isArray(data?.jobs) ? data.jobs : null;
  if (!rows) throw new Error("The file should contain a list of jobs, or an object with a jobs list.");
  const jobs = rows.map(r => normalizeJob(r, now)).filter(Boolean);
  return { jobs, skipped: rows.length - jobs.length };
}

// Incoming jobs update existing ones (matched by id, then by company and role).
// Empty incoming fields never erase existing values.
export function mergeJobs(existing, incoming) {
  const jobs = existing.map(j => ({ ...j }));
  let added = 0, updated = 0;
  for (const inc of incoming) {
    const i = jobs.findIndex(j => j.id === inc.id || keyOf(j) === keyOf(inc));
    if (i === -1) { jobs.push({ ...inc }); added++; continue; }
    const merged = { ...jobs[i] };
    for (const [k, v] of Object.entries(inc)) {
      if (k === "id" || k === "createdAt") continue;
      if (v !== "" && v != null) merged[k] = v;
    }
    jobs[i] = merged;
    updated++;
  }
  return { jobs, added, updated };
}

export function setStatus(job, status, today = todayISO()) {
  const next = { ...job, status, updatedAt: new Date().toISOString() };
  if (status === "Applied") {
    next.appliedOn = job.appliedOn || today;
    next.followUp = job.followUp || addDays(next.appliedOn, 10);
  }
  return next;
}

export const RELATIONS = ["Recruiter", "Hiring manager", "Employee", "Alumni", "Friend", "Referral", "Other"];
export const EVENT_KINDS = ["Note", "Applied", "Email sent", "Message sent", "Reply", "Call", "Interview", "Offer", "Rejection"];

// Due when you applied, nobody has replied yet and the follow up date has passed.
export const isFollowUpDue = (job, today = todayISO()) =>
  ["Applied", "Waiting"].includes(job.status) && !job.repliedOn && isDate(job.followUp || "") && job.followUp <= today;

export const isWaiting = job => !!job.cvSent && !job.repliedOn && GROUPS.progress.includes(job.status);

export function filterJobs(jobs, { group = "active", query = "", hybridOnly = false } = {}) {
  const statuses = GROUPS[group] || GROUPS.active;
  const q = query.trim().toLowerCase();
  return jobs.filter(j =>
    statuses.includes(j.status) &&
    (!hybridOnly || j.workSetup === "Hybrid") &&
    (!q || `${j.company} ${j.role} ${j.location} ${j.summary || ""}`.toLowerCase().includes(q)));
}

export function sortJobs(jobs, today = todayISO()) {
  const urgent = j => (isFollowUpDue(j, today) ? 0 : 1);
  const fit = j => FIT_RANK[j.fit] ?? FITS.length;
  const score = j => (typeof j.score === "number" ? j.score : -1);
  const due = j => j.deadline || "9999-12-31";
  return [...jobs].sort((a, b) =>
    urgent(a) - urgent(b) || fit(a) - fit(b) || score(b) - score(a) || due(a).localeCompare(due(b)) || String(a.id).localeCompare(String(b.id)));
}

export function summarize(jobs, today = todayISO()) {
  return {
    toApply: jobs.filter(j => j.status === "To apply").length,
    applied: jobs.filter(j => j.cvSent).length,
    waiting: jobs.filter(isWaiting).length,
    due: jobs.filter(j => isFollowUpDue(j, today)).length,
  };
}
