import React, { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, FileUp, Brain, Printer } from "lucide-react";
import "./style.css";

type JobState = "idle" | "starting" | "running" | "cancelling" | "completed" | "cancelled" | "failed";
export type Job = {
  job_id: string;
  state: string;
  result?: Analysis | null;
  stage?: string;
  processed_messages?: number;
  total_messages?: number | null;
  percent_complete?: number | null;
  elapsed_seconds?: number | null;
  estimated_remaining_seconds?: number | null;
};
type Evidence = { evidence_id?: string | null; topic: string; duration_seconds: number };
type Topic = { topic: string; message_count: number; timing_classification?: string; silence_windows?: Evidence[]; silence_window_count?: number };
export type Analysis = {
  summary: { duration_seconds: number; topic_count?: number; total_messages?: number };
  topics: Topic[];
  incidents?: Evidence[];
  incident_count?: number;
};
type Hypothesis = { rank: number; hypothesis: string; reasoning: string; evidence_ids?: string[] };
type Investigation = { model: string; summary: string; hypotheses?: Hypothesis[]; limitations?: string[] };

const question = "What most likely happened during the largest timing disruption?";
async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(response.status === 404 ? "The analysis job is no longer available." : "The request could not be completed.");
  return response.json() as Promise<T>;
}

export const evidenceTargetId = (id: string) => `evidence-${id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;

function LocalProgress({ job, state, onCancel }: { job: Job | null; state: JobState; onCancel: () => void }) {
  const message = state === "starting"
    ? "Bag Doctor is validating the ROS 2 bag and preparing the analysis job."
    : state === "cancelling"
      ? "Bag Doctor is stopping at the next safe analysis checkpoint."
      : job?.stage || "Analyzing local ROS 2 bag";
  return <section className="panel progress-shell" aria-live="polite" aria-atomic="true">
    <h2>Local analysis: {state}</h2>
    {state === "cancelling" && <strong>Cancellation requested</strong>}
    <p>{message}</p>
    <p><strong>{job?.processed_messages ?? 0}</strong> processed messages{job?.total_messages == null ? ". Total message count is not yet known." : ` of ${job.total_messages}`}</p>
    {job?.percent_complete != null && <><progress max="100" value={job.percent_complete} aria-label="Analysis progress" /><span> {job.percent_complete}%</span></>}
    {job?.elapsed_seconds != null && <p>Elapsed: {job.elapsed_seconds.toFixed(1)}s{job.estimated_remaining_seconds == null ? "" : ` · ETA ${job.estimated_remaining_seconds.toFixed(1)}s`}</p>}
    <button type="button" disabled={state === "cancelling" || !job?.job_id} onClick={onCancel}>Cancel analysis</button>
  </section>;
}

export function AnalysisDashboard({ analysis, jobId }: { analysis: Analysis; jobId: string | null }) {
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const totalMessages = analysis.summary.total_messages ?? analysis.topics.reduce((sum, topic) => sum + topic.message_count, 0);
  const topicCount = analysis.summary.topic_count ?? analysis.topics.length;
  const incidentCount = analysis.incident_count ?? analysis.incidents?.length ?? 0;
  const evidence = analysis.incidents ?? [];

  const investigate = async () => {
    if (!jobId || evidence.length === 0) return;
    setBusy(true); setNotice("");
    try {
      setInvestigation(await api<Investigation>(`/api/analyze/jobs/${jobId}/investigate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question, max_tool_calls: 6 }) }));
    } catch {
      setNotice("GPT-5.6 investigation is unavailable. Try again when the provider is available.");
    } finally { setBusy(false); }
  };
  const navigateEvidence = (id: string) => {
    const target = document.getElementById(evidenceTargetId(id));
    if (!target || target.dataset.evidenceId !== id) {
      setNotice("Evidence unavailable in this bounded analysis view.");
      return;
    }
    setNotice(""); setSelectedEvidence(id); target.focus(); target.scrollIntoView?.({ block: "center" });
  };

  return <section id="overview" data-testid="analysis-dashboard">
    <div className="cards">{[["Duration", `${analysis.summary.duration_seconds}s`], ["Topics", topicCount], ["Messages", totalMessages], ["Incidents", incidentCount]].map(([label, value]) => <div className="card" key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div>
    <section id="topics" className="panel"><h2>Topics</h2><table><tbody>{analysis.topics.map(topic => <tr key={topic.topic}><td>{topic.topic}</td><td><b className="badge">{topic.timing_classification ?? "unknown"}</b></td><td>{topic.message_count}</td></tr>)}</tbody></table></section>
    <section id="evidence" className="panel"><h2>Evidence</h2>{evidence.map(item => item.evidence_id && <article className={`evidence-card${selectedEvidence === item.evidence_id ? " selected" : ""}`} id={evidenceTargetId(item.evidence_id)} data-evidence-id={item.evidence_id} tabIndex={-1} key={item.evidence_id}><code>{item.evidence_id}</code><p>{item.topic} · {item.duration_seconds}s</p></article>)}</section>
    <section id="gpt-5.6" className="panel"><h2><Brain /> GPT-5.6 Investigator</h2><p>Bounded deterministic evidence only. Timing measurements alone do not establish a physical root cause.</p>
      <button type="button" disabled={!jobId || evidence.length === 0 || busy} onClick={investigate}>{busy ? "Investigating…" : "Investigate with GPT-5.6"}</button>
      {notice && <p className="notice" role="status">{notice}</p>}
      {investigation && <div><h3>{investigation.model}</h3><p>{investigation.summary}</p>{investigation.hypotheses?.map(h => <article className="hypothesis" key={h.rank}><div><h3>#{h.rank} {h.hypothesis}</h3><p>{h.reasoning}</p><div>{h.evidence_ids?.map(id => <button type="button" className="citation" onClick={() => navigateEvidence(id)} key={id}>{id}</button>)}</div></div></article>)}</div>}
    </section>
    <button className="secondary" type="button" onClick={() => print()}><Printer /> Print report</button>
  </section>;
}

export default function App() {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [status, setStatus] = useState<JobState>("idle");
  const [error, setError] = useState("");
  const [localPath, setLocalPath] = useState("");
  const sourceRef = useRef<EventSource | null>(null);
  const workflowToken = useRef(0);
  const cancelSent = useRef(false);
  const file = useRef<HTMLInputElement>(null);

  const closeSource = useCallback(() => { sourceRef.current?.close(); sourceRef.current = null; }, []);
  const beginWorkflow = useCallback(() => { workflowToken.current += 1; closeSource(); cancelSent.current = false; setError(""); }, [closeSource]);
  useEffect(() => () => { workflowToken.current += 1; closeSource(); }, [closeSource]);

  const demo = async () => {
    beginWorkflow(); const token = workflowToken.current; setStatus("idle");
    try {
      const created = await api<{ job_id: string }>("/api/analyze/demo/job");
      const completed = await api<Job>(`/api/analyze/jobs/${created.job_id}`);
      if (workflowToken.current !== token) return;
      setJob(completed); setAnalysis(completed.result ?? null); setStatus("completed");
    } catch { if (workflowToken.current === token) setError("Analysis failed."); }
  };
  const upload = async (uploadFile: File) => {
    beginWorkflow(); const token = workflowToken.current; setStatus("idle"); setJob(null);
    const data = new FormData(); data.append("file", uploadFile);
    try { const result = await api<Analysis>("/api/analyze/upload", { method: "POST", body: data }); if (workflowToken.current === token) setAnalysis(result); }
    catch { if (workflowToken.current === token) setError("Upload failed."); }
  };
  const local = async (path: string) => {
    beginWorkflow(); const token = workflowToken.current; setAnalysis(null); setJob(null); setStatus("starting");
    if (!path.trim()) { setStatus("idle"); setError("Enter an absolute local bag directory path."); return; }
    try {
      const created = await api<Job>("/api/analyze/local", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ path }) });
      if (workflowToken.current !== token) return;
      setJob(created); setStatus("running");
      const stream = new EventSource(`/api/analyze/jobs/${created.job_id}/events`); sourceRef.current = stream;
      const terminal = async (state: "completed" | "cancelled" | "failed") => {
        if (workflowToken.current !== token || sourceRef.current !== stream) return;
        closeSource();
        if (state === "completed") {
          try {
            const completed = await api<Job>(`/api/analyze/jobs/${created.job_id}`);
            if (workflowToken.current !== token) return;
            setJob(completed); setAnalysis(completed.result ?? null); setStatus("completed");
          } catch { if (workflowToken.current === token) { setStatus("failed"); setError("The completed analysis result could not be loaded."); } }
        } else if (state === "cancelled") { setStatus("cancelled"); setError(""); }
        else { setStatus("failed"); setError("The local analysis failed safely. You can start another analysis."); }
      };
      const handler = (event: MessageEvent) => {
        if (workflowToken.current !== token || sourceRef.current !== stream) return;
        let payload: Partial<Job>; try { payload = JSON.parse(event.data) as Partial<Job>; } catch { return; }
        setJob(previous => previous ? { ...previous, ...payload, job_id: created.job_id } : { ...created, ...payload });
        if (event.type === "completed") void terminal("completed");
        else if (event.type === "cancelled") void terminal("cancelled");
        else if (event.type === "job-error") void terminal("failed");
      };
      ["progress", "completed", "cancelled", "job-error"].forEach(name => stream.addEventListener(name, handler));
      stream.onerror = () => { if (workflowToken.current === token && sourceRef.current === stream) void terminal("failed"); };
    } catch { if (workflowToken.current === token) { closeSource(); setStatus("failed"); setError("The local analysis could not be started."); } }
  };
  const cancel = async () => {
    if (!job || !["starting", "running"].includes(status) || cancelSent.current) return;
    cancelSent.current = true; setStatus("cancelling");
    try { await api(`/api/analyze/jobs/${job.job_id}/cancel`, { method: "POST" }); }
    catch { setError("Cancellation could not be requested. Waiting for the analysis stream."); }
  };
  const submitLocal = (event: FormEvent) => { event.preventDefault(); void local(localPath); };
  const activeLocal = ["starting", "running", "cancelling"].includes(status) && !analysis;

  let body: React.ReactNode;
  if (activeLocal) body = <LocalProgress job={job} state={status} onCancel={cancel} />;
  else if (analysis) body = <AnalysisDashboard analysis={analysis} jobId={job?.job_id ?? null} />;
  else if (status === "cancelled") body = <section className="panel"><h2>Analysis cancelled</h2><p>Partial results were not cached.</p></section>;
  else if (status === "failed") body = <section className="panel"><h2>Analysis failed</h2><p>The request ended without exposing internal details. Choose a workflow above to try again.</p></section>;
  else body = <section className="empty"><Brain size={42} /><h2>Load a recording to begin</h2><button type="button" onClick={demo}>Analyze failed robot demo</button></section>;

  return <div className="app"><aside><div className="brand"><Activity /> BAG DOCTOR</div><p className="muted">ROS 2 Evidence-Driven Failure Investigator</p><a href="#overview">Overview</a><a href="#topics">Topics</a><a href="#evidence">Evidence</a><a href="#gpt-5.6">GPT-5.6 Investigator</a></aside><main><header><h1>Bag Doctor</h1><div className="actions"><button type="button" onClick={demo}>Run bundled demo</button><button className="secondary" type="button" onClick={() => file.current?.click()}><FileUp /> Upload bag</button><input ref={file} hidden type="file" aria-label="Upload bag file" accept=".mcap,.db3,.zip" onChange={event => event.target.files?.[0] && void upload(event.target.files[0])} /></div></header>
    <form className="local-launcher" onSubmit={submitLocal}><label htmlFor="local-path">Local bag path</label><input id="local-path" value={localPath} onChange={event => setLocalPath(event.target.value)} placeholder="/absolute/path/to/bag-directory" /><button type="submit">Analyze local path</button></form>
    {error && <div className="alert" role="alert">{error}</div>}{body}</main></div>;
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
