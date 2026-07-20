import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App, { type Analysis } from "./main";
import { analysis } from "./test/fixtures";

const response = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);

describe("browser upload workflow", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });

  it("explains supported uploads and shows the selected file while processing", async () => {
    let resolve!: (value: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
    render(<App />);

    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText(/Complete deterministic analysis before GPT-5.6 investigation is available/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload & analyze bag" })).toBeEnabled();
    const guidance = screen.getByRole("heading", { name: "Browser upload" }).closest("section");
    expect(guidance).toHaveTextContent(/standalone \.mcap or \.db3/i);
    expect(guidance).toHaveTextContent(/does not require selecting metadata\.yaml separately/i);
    expect(guidance).toHaveTextContent(/split bag.*\.zip.*metadata\.yaml.*every/i);
    expect(guidance).toHaveTextContent(/Local bag path workflow for large complete bags/i);
    expect(guidance).toHaveTextContent(/limited to 512 MiB/i);

    await userEvent.upload(screen.getByLabelText("Upload bag file"), new File(["bag"], "field-run.db3"));
    expect(screen.getByText("field-run.db3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Uploading and analyzing field-run.db3" })).toBeInTheDocument();
    expect(screen.getByText(/analyzes it automatically after the transfer completes/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText("Analysis is still running. GPT-5.6 investigation will be available after deterministic analysis completes.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload & analyze bag" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledWith("/api/analyze/upload", expect.objectContaining({ method: "POST", body: expect.any(FormData) }));

    await act(async () => resolve(await response(analysis)));
    expect(await screen.findByTestId("analysis-dashboard")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText(/direct Upload results do not have a registered completed analysis job/i)).toBeInTheDocument();
    expect(screen.queryByText("No bounded evidence is available for this recording.")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ranked incidents and bounded evidence" })).toBeInTheDocument();
  });

  it("shows both independent availability reasons for a zero-evidence Upload result", async () => {
    const noEvidence: Analysis = { ...analysis, topics: analysis.topics.map(topic => ({ ...topic, silence_windows: [] })), incidents: [], incident_count: 0 };
    fetchMock.mockImplementationOnce(() => response(noEvidence));
    render(<App />);

    await userEvent.upload(screen.getByLabelText("Upload bag file"), new File(["bag"], "quiet.db3"));
    expect(await screen.findByTestId("analysis-dashboard")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText("No bounded evidence is available for this recording.")).toBeInTheDocument();
    expect(screen.getByText("GPT-5.6 only investigates evidence produced by deterministic analysis.")).toBeInTheDocument();
    expect(screen.getByText(/direct Upload results do not have a registered completed analysis job/i)).toBeInTheDocument();
    expect(screen.getByText("0 evidence records returned")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/healthy/i);
  });

  it("keeps investigation unavailable while the bundled Demo is running", async () => {
    fetchMock.mockImplementationOnce(() => new Promise<Response>(() => undefined));
    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Run bundled demo" }));
    expect(screen.getByRole("heading", { name: "Analyzing bundled demo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText("Analysis is still running. GPT-5.6 investigation will be available after deterministic analysis completes.")).toBeInTheDocument();
  });
});
