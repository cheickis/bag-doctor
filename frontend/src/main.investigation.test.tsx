import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnalysisDashboard, evidenceTargetId, type Analysis } from "./main";
import { analysis, evidenceId, investigation } from "./test/fixtures";

const response = (body: unknown, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 503, json: () => Promise.resolve(body) } as Response);

describe("GPT-5.6 investigation and evidence", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });

  it("renders a successful investigation and navigates valid citations", async () => {
    fetchMock.mockImplementationOnce(() => response(investigation)); render(<AnalysisDashboard analysis={analysis} jobId="completed-1" />);
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Investigate with GPT-5.6" }));
    expect(await screen.findByText("A timing disruption is visible.")).toBeInTheDocument();
    expect(screen.getByText(/Possible scheduler delay/)).toBeInTheDocument();
    expect(screen.getAllByText(/Timing measurements alone do not establish a physical root cause/)).toHaveLength(2);
    const citation = screen.getByRole("button", { name: evidenceId }); await userEvent.click(citation);
    expect(citation).not.toHaveClass("print-hidden");
    expect(citation.closest("[data-report='bag-doctor-analysis']")).not.toBeNull();
    const target = document.getElementById(evidenceTargetId(evidenceId))!;
    expect(target).toHaveFocus(); expect(target).toHaveClass("selected");
    expect(screen.getByText("Investigation completed.")).toBeInTheDocument();
  });

  it("distinguishes missing job IDs and completed jobs with zero bounded evidence", () => {
    const noEvidence: Analysis = { ...analysis, topics: analysis.topics.map(topic => ({ ...topic, silence_windows: [] })), incidents: [], incident_count: 0 };
    const first = render(<AnalysisDashboard analysis={analysis} jobId={null} />);
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText(/direct Upload results do not have a registered completed analysis job/i)).toBeInTheDocument();
    expect(screen.queryByText("No bounded evidence is available for this recording.")).not.toBeInTheDocument();
    first.unmount();

    render(<AnalysisDashboard analysis={noEvidence} jobId="completed-empty" />);
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText("No bounded evidence is available for this recording.")).toBeInTheDocument();
    expect(screen.getByText("GPT-5.6 only investigates evidence produced by deterministic analysis.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/healthy/i);
  });

  it("disables investigation while a request is running", async () => {
    fetchMock.mockImplementationOnce(() => new Promise<Response>(() => undefined));
    render(<AnalysisDashboard analysis={analysis} jobId="completed-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Investigate with GPT-5.6" }));
    expect(screen.getByRole("button", { name: "Investigating…" })).toBeDisabled();
    expect(screen.getByText("Investigation is currently running.")).toBeInTheDocument();
  });

  it("reports citations outside bounded evidence as unavailable", async () => {
    fetchMock.mockImplementationOnce(() => response({ ...investigation, hypotheses: [{ ...investigation.hypotheses[0], evidence_ids: ["ev_missing"] }] }));
    render(<AnalysisDashboard analysis={analysis} jobId="completed-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Investigate with GPT-5.6" }));
    await userEvent.click(await screen.findByRole("button", { name: "ev_missing" }));
    expect(screen.getByText(/Evidence unavailable/)).toBeInTheDocument();
  });

  it("normalizes unsafe IDs and cannot focus an unrelated colliding target", async () => {
    const unsafe = "x'] #unrelated"; const unsafeAnalysis: Analysis = { ...analysis, incidents: [{ evidence_id: unsafe, topic: "/safe", duration_seconds: 1 }] };
    fetchMock.mockImplementationOnce(() => response({ ...investigation, hypotheses: [{ ...investigation.hypotheses[0], evidence_ids: [unsafe] }] }));
    render(<AnalysisDashboard analysis={unsafeAnalysis} jobId="job" />);
    expect(evidenceTargetId(unsafe)).toMatch(/^evidence-[a-zA-Z0-9_-]+$/);
    const actual = document.getElementById(evidenceTargetId(unsafe))!; actual.dataset.evidenceId = "different";
    await userEvent.click(screen.getByRole("button", { name: "Investigate with GPT-5.6" }));
    await userEvent.click(await screen.findByRole("button", { name: unsafe }));
    expect(screen.getByText(/Evidence unavailable/)).toBeInTheDocument(); expect(actual).not.toHaveFocus();
  });

  it("shows a safe provider-unavailable message without backend details", async () => {
    fetchMock.mockImplementationOnce(() => response({ detail: "OPENAI_API_KEY=secret\nTraceback stderr /home/private" }, false));
    render(<AnalysisDashboard analysis={analysis} jobId="job" />); fireEvent.click(screen.getByRole("button", { name: "Investigate with GPT-5.6" }));
    await waitFor(() => expect(screen.getByText(/provider is available/)).toBeInTheDocument());
    expect(document.body).not.toHaveTextContent(/OPENAI_API_KEY|Traceback|stderr|\/home\/private/);
  });
});
