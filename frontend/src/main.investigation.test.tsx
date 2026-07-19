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
    await userEvent.click(screen.getByRole("button", { name: "Investigate with GPT-5.6" }));
    expect(await screen.findByText("A timing disruption is visible.")).toBeInTheDocument();
    expect(screen.getByText(/Possible scheduler delay/)).toBeInTheDocument();
    expect(screen.getAllByText(/Timing measurements alone do not establish a physical root cause/)).toHaveLength(2);
    const citation = screen.getByRole("button", { name: evidenceId }); await userEvent.click(citation);
    expect(citation).not.toHaveClass("print-hidden");
    expect(citation.closest("[data-report='bag-doctor-analysis']")).not.toBeNull();
    const target = document.getElementById(evidenceTargetId(evidenceId))!;
    expect(target).toHaveFocus(); expect(target).toHaveClass("selected");
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
