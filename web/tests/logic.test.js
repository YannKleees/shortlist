import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addDays, normalizeJob, parseImport, mergeJobs, setStatus,
  isFollowUpDue, filterJobs, sortJobs, summarize,
} from "../logic.js";

const NOW = "2026-11-08T12:00:00.000Z";
const TODAY = "2026-11-08";

test("addDays crosses month boundaries", () => {
  assert.equal(addDays("2026-11-25", 10), "2026-12-05");
  assert.equal(addDays("2026-12-31", 1), "2027-01-01");
});

test("normalizeJob trims fields and fills defaults", () => {
  const j = normalizeJob({ company: "  Acme ", role: " Data Intern ", score: "72" }, NOW);
  assert.equal(j.company, "Acme");
  assert.equal(j.role, "Data Intern");
  assert.equal(j.status, "To apply");
  assert.equal(j.workSetup, "Unknown");
  assert.equal(j.score, 72);
  assert.equal(j.createdAt, NOW);
  assert.equal(j.addedBy, "you");
  assert.equal(normalizeJob({ company: "B", addedBy: "pipeline" }, NOW).addedBy, "pipeline");
  assert.ok(j.id.startsWith("acme-data-intern"));
});

test("normalizeJob rejects rows without a company", () => {
  assert.equal(normalizeJob({ role: "Intern" }, NOW), null);
});

test("normalizeJob drops unknown statuses, fits and bad links", () => {
  const j = normalizeJob({ company: "A", status: "Ghosted", fit: "Great", link: "javascript:alert(1)", score: 140 }, NOW);
  assert.equal(j.status, "To apply");
  assert.equal(j.fit, "");
  assert.equal(j.link, "");
  assert.equal(j.score, 100);
});

test("parseImport accepts an array or a {jobs} object and counts skipped rows", () => {
  const a = parseImport(JSON.stringify([{ company: "A" }, { role: "no company" }]), NOW);
  assert.equal(a.jobs.length, 1);
  assert.equal(a.skipped, 1);
  const b = parseImport(JSON.stringify({ jobs: [{ company: "B" }] }), NOW);
  assert.equal(b.jobs[0].company, "B");
});

test("parseImport throws a readable error on invalid JSON", () => {
  assert.throws(() => parseImport("{nope", NOW), /not valid JSON/);
  assert.throws(() => parseImport("42", NOW), /list of jobs/);
});

test("mergeJobs updates by id, dedupes by company and role, keeps the rest", () => {
  const existing = [
    normalizeJob({ id: "x", company: "Acme", role: "Analyst", notes: "mine" }, NOW),
    normalizeJob({ id: "y", company: "Beta", role: "Intern" }, NOW),
  ];
  const incoming = [
    normalizeJob({ id: "x", company: "Acme", role: "Analyst", score: 80 }, NOW),
    normalizeJob({ id: "z", company: "beta", role: "intern", score: 60 }, NOW),
    normalizeJob({ id: "w", company: "Gamma", role: "DS" }, NOW),
  ];
  const { jobs, added, updated } = mergeJobs(existing, incoming);
  assert.equal(jobs.length, 3);
  assert.equal(added, 1);
  assert.equal(updated, 2);
  assert.equal(jobs.find(j => j.id === "x").score, 80);
  assert.equal(jobs.find(j => j.id === "x").notes, "mine", "empty incoming fields keep existing values");
  assert.equal(jobs.find(j => j.id === "y").score, 60);
});

test("setStatus to Applied records the date and a follow up in 10 days", () => {
  const j = setStatus(normalizeJob({ company: "A" }, NOW), "Applied", TODAY);
  assert.equal(j.appliedOn, TODAY);
  assert.equal(j.followUp, "2026-11-18");
  const again = setStatus({ ...j, appliedOn: "2026-11-01", followUp: "" }, "Applied", TODAY);
  assert.equal(again.appliedOn, "2026-11-01");
  assert.equal(again.followUp, "2026-11-11");
});

test("isFollowUpDue only for jobs that are waiting on a reply", () => {
  assert.equal(isFollowUpDue({ status: "Applied", followUp: "2026-11-08" }, TODAY), true);
  assert.equal(isFollowUpDue({ status: "Applied", followUp: "2026-11-09" }, TODAY), false);
  assert.equal(isFollowUpDue({ status: "Rejected", followUp: "2026-11-01" }, TODAY), false);
  assert.equal(isFollowUpDue({ status: "Applied", followUp: "2026-11-01", repliedOn: "2026-11-05" }, TODAY), false, "a reply clears it");
});

test("filterJobs by group, search text and hybrid only", () => {
  const jobs = [
    { company: "Acme", role: "DS intern", location: "Luxembourg", status: "To apply", workSetup: "Hybrid" },
    { company: "Beta", role: "Analyst", location: "Utrecht", status: "Applied", workSetup: "On site" },
    { company: "Gamma", role: "ML intern", location: "Remote", status: "To apply", workSetup: "Remote" },
  ];
  assert.equal(filterJobs(jobs, { group: "active" }).length, 2);
  assert.equal(filterJobs(jobs, { group: "progress" }).length, 1);
  assert.equal(filterJobs(jobs, { group: "active", hybridOnly: true }).length, 1);
  assert.equal(filterJobs(jobs, { group: "active", query: "luxem" })[0].company, "Acme");
});

test("sortJobs puts the best fit first, then score, then the nearest deadline", () => {
  const jobs = [
    { id: "a", fit: "Good", score: 70 },
    { id: "b", fit: "Top pick", score: 81 },
    { id: "c", fit: "Good", score: 75 },
    { id: "d", fit: "", score: null },
    { id: "e", fit: "Good", score: 70, deadline: "2026-12-01" },
  ];
  assert.deepEqual(sortJobs(jobs, TODAY).map(j => j.id), ["b", "c", "e", "a", "d"]);
  const due = { id: "z", fit: "", status: "Applied", followUp: "2026-11-01" };
  assert.equal(sortJobs([...jobs, due], TODAY)[0].id, "z", "overdue follow ups come first");
});

test("summarize counts what needs attention", () => {
  const s = summarize([
    { status: "To apply" },
    { status: "To apply" },
    { status: "Applied", cvSent: 1, followUp: "2026-11-01" },
    { status: "Interview", cvSent: 1, repliedOn: "2026-11-03" },
    { status: "Waiting", cvSent: 1 },
  ], TODAY);
  assert.deepEqual(s, { toApply: 2, applied: 3, waiting: 2, due: 1 });
});

import { searchJobs, nextAction } from "../logic.js";

test("searchJobs puts company matches first and ignores accents", () => {
  const jobs = [
    { id: "a", company: "Société Générale", role: "Data Analyst", location: "Luxembourg", score: 60 },
    { id: "b", company: "Northwind", role: "Senior Data Scientist", location: "Esch", score: 30 },
    { id: "c", company: "Data Corp", role: "Intern", location: "Belval", score: 50 },
  ];
  assert.deepEqual(searchJobs(jobs, "data").map(j => j.id), ["c", "a", "b"]);
  assert.deepEqual(searchJobs(jobs, "societe").map(j => j.id), ["a"]);
  assert.deepEqual(searchJobs(jobs, "  "), []);
});

test("nextAction names the one thing to do", () => {
  assert.equal(nextAction({ status: "To apply", hasText: false }, TODAY).text, "Paste the job text");
  assert.equal(nextAction({ status: "To apply", hasText: true, deadline: "2026-11-09" }, TODAY).tone, "low");
  assert.equal(nextAction({ status: "Applied", cvSent: 1, followUp: "2026-11-01" }, TODAY).text, "Follow up today");
  assert.equal(nextAction({ status: "Applied", cvSent: 1, followUp: "2026-12-01" }, TODAY).text, "Waiting");
});
