import React, { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, FileUp, Brain, Printer, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, LayoutDashboard, ListTree, Search, FileText } from "lucide-react";
import { Alert, Badge, Button, Card, CardContent, CardHeader, Table } from "./components/ui";
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
const investigatorIdentity = (model: string) => `${model.endsWith("-terra") ? "Codex CLI" : "Responses API"} · ${model}`;

const question = "What most likely happened during the largest timing disruption?";
type Theme = "system" | "light" | "dark";
const storedBoolean = (key: string) => { try { return localStorage.getItem(key) === "true"; } catch { return false; } };
const storedTheme = (): Theme => { try { const value = localStorage.getItem("bag-doctor-theme"); return value === "light" || value === "dark" ? value : "system"; } catch { return "system"; } };
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
  return <Card className="progress-shell print-hidden" aria-live="polite" aria-atomic="true">
    <h2>Local analysis: {state}</h2>
    {state === "cancelling" && <strong>Cancellation requested</strong>}
    <p>{message}</p>
    <p><strong>{job?.processed_messages ?? 0}</strong> processed messages{job?.total_messages == null ? ". Total message count is not yet known." : ` of ${job.total_messages}`}</p>
    {job?.percent_complete != null && <><progress max="100" value={job.percent_complete} aria-label="Analysis progress" /><span> {job.percent_complete}%</span></>}
    {job?.elapsed_seconds != null && <p>Elapsed: {job.elapsed_seconds.toFixed(1)}s{job.estimated_remaining_seconds == null ? "" : ` · ETA ${job.estimated_remaining_seconds.toFixed(1)}s`}</p>}
    <Button variant="danger" type="button" disabled={state === "cancelling" || !job?.job_id} onClick={onCancel}>Cancel analysis</Button>
  </Card>;
}

function InvestigatorUnavailable({ analysisPending }: { analysisPending: boolean }) {
  return <Card id="gpt-5.6" className="investigator-section print-hidden">
    <CardHeader><h2><Brain /> GPT-5.6 Investigator</h2></CardHeader>
    <CardContent>
      <Button type="button" disabled>Investigate with GPT-5.6</Button>
      <Alert variant="warning">{analysisPending
        ? "Analysis is still running. GPT-5.6 investigation will be available after deterministic analysis completes."
        : "Complete deterministic analysis before GPT-5.6 investigation is available."}</Alert>
    </CardContent>
  </Card>;
}

export function AnalysisDashboard({ analysis, jobId }: { analysis: Analysis; jobId: string | null }) {
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [investigatorCollapsed, setInvestigatorCollapsed] = useState(() => storedBoolean("bag-doctor-investigator-collapsed"));
  const totalMessages = analysis.summary.total_messages ?? analysis.topics.reduce((sum, topic) => sum + topic.message_count, 0);
  const topicCount = analysis.summary.topic_count ?? analysis.topics.length;
  const incidentCount = analysis.incident_count ?? analysis.incidents?.length ?? 0;
  const evidence = [...analysis.topics.flatMap(topic => topic.silence_windows ?? []), ...(analysis.incidents ?? [])]
    .filter((item, index, items) => item.evidence_id && items.findIndex(candidate => candidate.evidence_id === item.evidence_id) === index);

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

  const toggleInvestigator = () => setInvestigatorCollapsed(value => { try { localStorage.setItem("bag-doctor-investigator-collapsed", String(!value)); } catch {} return !value; });
  return <section id="overview" className={`report${investigatorCollapsed ? " investigator-collapsed" : ""}`} aria-labelledby="report-title" data-testid="analysis-dashboard" data-report="bag-doctor-analysis">
    <header className="report-header"><p className="eyebrow">Evidence-driven analysis report</p><h1 id="report-title">Bag Doctor Report</h1>{jobId && <p className="report-job">Completed job <code>{jobId}</code></p>}</header>
    <div className="cards">{[["Duration", `${analysis.summary.duration_seconds}s`], ["Topics", topicCount], ["Messages", totalMessages], ["Incidents", incidentCount]].map(([label, value]) => <Card className="summary-card" key={String(label)}><CardContent><span>{label}</span><strong>{value}</strong></CardContent></Card>)}</div>
    <Card id="topics" className="report-section"><CardHeader><h2>Topic classifications</h2></CardHeader><CardContent><Table><thead><tr><th scope="col">Topic</th><th scope="col">Classification</th><th scope="col">Messages</th></tr></thead><tbody>{analysis.topics.map(topic => <tr key={topic.topic}><td>{topic.topic}</td><td><Badge>{topic.timing_classification ?? "unknown"}</Badge></td><td>{topic.message_count}</td></tr>)}</tbody></Table></CardContent></Card>
    <Card id="evidence" className="report-section"><CardHeader><h2>Ranked incidents and bounded evidence</h2><p>{evidence.length} evidence record{evidence.length === 1 ? "" : "s"} returned</p></CardHeader><CardContent>{evidence.map((item, index) => item.evidence_id && <article className={`evidence-card${selectedEvidence === item.evidence_id ? " selected" : ""}`} id={evidenceTargetId(item.evidence_id)} data-evidence-id={item.evidence_id} tabIndex={-1} key={item.evidence_id}><h3>Incident #{index + 1}</h3><code>{item.evidence_id}</code><p>{item.topic} · {item.duration_seconds}s</p></article>)}</CardContent></Card>
    {investigatorCollapsed && <Button className="investigator-reopen print-hidden icon-button" variant="secondary" type="button" aria-expanded="false" aria-label="Open GPT-5.6 Investigator" title="Open GPT-5.6 Investigator" onClick={toggleInvestigator}><PanelRightOpen /></Button>}
    <Card id="gpt-5.6" className="report-section investigator-section"><CardHeader><div className="panel-heading"><h2><Brain /> GPT-5.6 Investigator</h2><Button className="print-hidden icon-button" variant="ghost" type="button" aria-expanded={!investigatorCollapsed} aria-label="Collapse GPT-5.6 Investigator" onClick={toggleInvestigator}><PanelRightClose /></Button></div></CardHeader><CardContent><p className="safety-limitation">Bounded deterministic evidence only. Timing measurements alone do not establish a physical root cause.</p>
      <Button className="print-hidden" type="button" disabled={!jobId || evidence.length === 0 || busy} onClick={investigate}>{busy ? "Investigating…" : "Investigate with GPT-5.6"}</Button>
      {!jobId && <Alert className="print-hidden" variant="warning">Investigation is unavailable because direct Upload results do not have a registered completed analysis job.</Alert>}
      {evidence.length === 0 && <Alert variant="warning"><p>No bounded evidence is available for this recording.</p><p>GPT-5.6 only investigates evidence produced by deterministic analysis.</p></Alert>}
      {jobId && evidence.length > 0 && !busy && !investigation && !notice && <Alert className="print-hidden">{evidence.length} bounded evidence record{evidence.length === 1 ? " is" : "s are"} available for investigation.</Alert>}
      {busy && <Alert className="print-hidden" aria-live="polite">Investigation is currently running.</Alert>}
      {notice && <Alert className="print-hidden" variant="warning">{notice}</Alert>}
      {investigation && <div className="investigation-result"><p className="investigation-status">Investigation completed.</p><h3>{investigatorIdentity(investigation.model)}</h3><p>{investigation.summary}</p>{investigation.hypotheses?.map(h => <article className="hypothesis" key={h.rank}><div><h3>#{h.rank} {h.hypothesis}</h3><p>{h.reasoning}</p><div className="citations" aria-label={`Evidence citations for hypothesis ${h.rank}`}>{h.evidence_ids?.map(id => <Button type="button" variant="ghost" className="citation" onClick={() => navigateEvidence(id)} key={id}>{id}</Button>)}</div></div></article>)}{investigation.limitations && investigation.limitations.length > 0 && <section className="limitations" aria-labelledby="limitations-title"><h3 id="limitations-title">Limitations</h3><ul>{investigation.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul></section>}</div>}
    </CardContent></Card>
    <Button className="print-hidden print-report" variant="secondary" type="button" onClick={() => print()}><Printer /> Print report</Button>
  </section>;
}

export default function App() {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [status, setStatus] = useState<JobState>("idle");
  const [error, setError] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [uploadFileName, setUploadFileName] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => storedBoolean("bag-doctor-sidebar-collapsed"));
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const [activeSection, setActiveSection] = useState("overview");
  const sourceRef = useRef<EventSource | null>(null);
  const workflowToken = useRef(0);
  const cancelSent = useRef(false);
  const file = useRef<HTMLInputElement>(null);

  const closeSource = useCallback(() => { sourceRef.current?.close(); sourceRef.current = null; }, []);
  const beginWorkflow = useCallback(() => { workflowToken.current += 1; closeSource(); cancelSent.current = false; setError(""); }, [closeSource]);
  useEffect(() => () => { workflowToken.current += 1; closeSource(); }, [closeSource]);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)") ?? { matches: false, addEventListener: (_event: string, _handler: () => void) => {}, removeEventListener: (_event: string, _handler: () => void) => {} };
    const apply = () => document.documentElement.dataset.theme = theme === "system" ? (media.matches ? "dark" : "light") : theme;
    apply(); if (theme === "system") media.addEventListener("change", apply);
    try { localStorage.setItem("bag-doctor-theme", theme); } catch {}
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const targets = ["overview", "topics", "evidence", "gpt-5.6", "report-title"].map(id => document.getElementById(id)).filter((value): value is HTMLElement => Boolean(value));
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) setActiveSection(visible.target.id === "report-title" ? "report" : visible.target.id);
    }, { rootMargin: "-15% 0px -65%", threshold: [0, .25, .5] });
    targets.forEach(target => observer.observe(target));
    return () => observer.disconnect();
  }, [analysis]);
  const toggleSidebar = () => setSidebarCollapsed(value => { try { localStorage.setItem("bag-doctor-sidebar-collapsed", String(!value)); } catch {} return !value; });

  const demo = async () => {
    beginWorkflow(); const token = workflowToken.current; setStatus("idle"); setJob(null); setAnalysis(null); setUploadBusy(false); setUploadFileName(""); setDemoBusy(true);
    try {
      const created = await api<{ job_id: string }>("/api/analyze/demo/job");
      const completed = await api<Job>(`/api/analyze/jobs/${created.job_id}`);
      if (workflowToken.current !== token) return;
      setJob(completed); setAnalysis(completed.result ?? null); setStatus("completed");
    } catch { if (workflowToken.current === token) setError("Analysis failed."); }
    finally { if (workflowToken.current === token) setDemoBusy(false); }
  };
  const upload = async (uploadFile: File) => {
    beginWorkflow(); const token = workflowToken.current; setStatus("idle"); setJob(null); setAnalysis(null); setUploadFileName(uploadFile.name); setDemoBusy(false); setUploadBusy(true);
    const data = new FormData(); data.append("file", uploadFile);
    try { const result = await api<Analysis>("/api/analyze/upload", { method: "POST", body: data }); if (workflowToken.current === token) setAnalysis(result); }
    catch { if (workflowToken.current === token) setError("Upload failed."); }
    finally { if (workflowToken.current === token) setUploadBusy(false); }
  };
  const local = async (path: string) => {
    beginWorkflow(); const token = workflowToken.current; setAnalysis(null); setJob(null); setStatus("starting"); setUploadBusy(false); setUploadFileName(""); setDemoBusy(false);
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
  if (demoBusy) body = <Alert className="upload-progress print-hidden" aria-live="polite"><h2>Analyzing bundled demo</h2><p>Deterministic analysis is still running.</p></Alert>;
  else if (uploadBusy) body = <Alert className="upload-progress print-hidden" aria-live="polite"><h2>Uploading and analyzing {uploadFileName}</h2><p>The browser is uploading this file. Bag Doctor analyzes it automatically after the transfer completes.</p></Alert>;
  else if (activeLocal) body = <LocalProgress job={job} state={status} onCancel={cancel} />;
  else if (analysis) body = <AnalysisDashboard analysis={analysis} jobId={job?.job_id ?? null} />;
  else if (status === "cancelled") body = <Alert className="print-hidden" variant="warning"><h2>Analysis cancelled</h2><p>Partial results were not cached.</p></Alert>;
  else if (status === "failed") body = <Alert className="print-hidden" variant="destructive"><h2>Analysis failed</h2><p>The request ended without exposing internal details. Choose a workflow above to try again.</p></Alert>;
  else body = <section className="empty print-hidden"><Brain size={42} /><h2>Load a recording to begin</h2><Button type="button" onClick={demo}>Analyze failed robot demo</Button></section>;

  const navItems = [["overview", "#overview", "Overview", LayoutDashboard], ["topics", "#topics", "Topics", ListTree], ["evidence", "#evidence", "Evidence", Search], ["gpt-5.6", "#gpt-5.6", "Investigator", Brain], ["report", "#report-title", "Report", FileText]] as const;
  return <div className={`app${sidebarCollapsed ? " sidebar-collapsed" : ""}`}><aside className="print-hidden"><div className="sidebar-top"><div className="brand"><Activity /><span>BAG DOCTOR</span></div><Button className="icon-button" variant="ghost" type="button" aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"} onClick={toggleSidebar}>{sidebarCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}</Button></div>{!sidebarCollapsed && <p className="muted">ROS 2 Evidence-Driven Failure Investigator</p>}<nav aria-label="Report sections">{navItems.map(([section,href,label,Icon]) => <a href={href} aria-label={label} aria-current={activeSection === section ? "location" : undefined} title={sidebarCollapsed ? label : undefined} onClick={() => setActiveSection(section)} key={label}><Icon /><span>{label}</span></a>)}</nav></aside><main><header className="app-header print-hidden"><h1>Bag Doctor</h1><div className="actions"><label className="theme-control">Theme<select aria-label="Theme" value={theme} onChange={event => setTheme(event.target.value as Theme)}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><Button type="button" onClick={demo}>Run bundled demo</Button><Button variant="secondary" type="button" disabled={uploadBusy} onClick={() => file.current?.click()}><FileUp /> Upload &amp; analyze bag</Button><input ref={file} hidden type="file" aria-label="Upload bag file" accept=".mcap,.db3,.zip" onChange={event => event.target.files?.[0] && void upload(event.target.files[0])} /></div></header>
    <Card className="upload-guidance print-hidden"><CardHeader><h2>Browser upload</h2></CardHeader><CardContent>{uploadFileName && <p className="selected-file">Selected file: <strong>{uploadFileName}</strong></p>}<ul><li>Upload a standalone <code>.mcap</code> or <code>.db3</code> file. A standalone <code>.db3</code> does not require selecting <code>metadata.yaml</code> separately.</li><li>For a split bag, upload one <code>.zip</code> containing <code>metadata.yaml</code> and every <code>.db3</code> or <code>.mcap</code> segment.</li><li>Use the Local bag path workflow for large complete bags.</li><li>Browser uploads are limited to 512 MiB.</li></ul></CardContent></Card>
    <form className="local-launcher print-hidden" onSubmit={submitLocal}><label htmlFor="local-path">Local bag path</label><input id="local-path" value={localPath} onChange={event => setLocalPath(event.target.value)} placeholder="/absolute/path/to/bag-directory" /><Button type="submit">Analyze local path</Button></form>
    {error && <Alert className="print-hidden" variant="destructive" role="alert">{error}</Alert>}{body}{!analysis && <InvestigatorUnavailable analysisPending={demoBusy || uploadBusy || activeLocal} />}</main></div>;
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
