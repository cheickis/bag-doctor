import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./main";
import { analysis } from "./test/fixtures";
import { FakeEventSource } from "./test/fakeEventSource";

const response = (body: unknown, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) } as Response);
const startLocal = async (fetchMock: ReturnType<typeof vi.fn>, id = "local-1") => {
  const previousSourceCount = FakeEventSource.instances.length;
  fetchMock.mockImplementationOnce(() => response({ job_id: id, state: "queued" }));
  const user = userEvent.setup();
  await user.clear(screen.getByLabelText("Local bag path"));
  await user.type(screen.getByLabelText("Local bag path"), "/bags/example");
  await user.click(screen.getByRole("button", { name: "Analyze local path" }));
  expect(screen.getByRole("heading", { name: /Local analysis: (starting|running)/ })).toBeInTheDocument();
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(previousSourceCount + 1));
  return FakeEventSource.latest();
};

describe("Local workflow", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); vi.stubGlobal("EventSource", FakeEventSource); });

  it("shows the starting shell before the create-job response exists", async () => {
    let resolve!: (value: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
    render(<App />); fireEvent.change(screen.getByLabelText("Local bag path"), { target: { value: "/bags/slow" } });
    fireEvent.submit(screen.getByLabelText("Local bag path").closest("form")!);
    expect(screen.getByRole("heading", { name: "Local analysis: starting" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
    expect(screen.getByText(/Analysis is still running/i)).toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(0);
    await act(async () => resolve(await response({ job_id: "slow", state: "queued" })));
    expect(FakeEventSource.latest().url).toContain("slow");
  });

  it("renders truthful first-run progress and posts the entered path", async () => {
    render(<App />); const stream = await startLocal(fetchMock, "job one");
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/analyze/local", expect.objectContaining({ method: "POST", body: JSON.stringify({ path: "/bags/example" }) }));
    expect(stream.url).toBe("/api/analyze/jobs/job one/events");
    act(() => stream.emit("progress", { state: "running", processed_messages: 8, total_messages: null, percent_complete: null, elapsed_seconds: 2, estimated_remaining_seconds: null, stage: "Reading messages" }));
    expect(screen.getByText(/8/)).toBeInTheDocument(); expect(screen.getByText(/not yet known/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument(); expect(screen.queryByText(/ETA/)).not.toBeInTheDocument();
    expect(screen.getByText("Reading messages")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Local analysis/ }).closest("section")).toHaveAttribute("aria-live", "polite");
  });

  it("requests cancellation once, retains metrics, and reaches terminal cancellation", async () => {
    render(<App />); const stream = await startLocal(fetchMock);
    act(() => stream.emit("progress", { processed_messages: 8, total_messages: 20, percent_complete: 40, elapsed_seconds: 3, estimated_remaining_seconds: 4 }));
    fetchMock.mockImplementationOnce(() => response({ job_id: "local-1", state: "cancelling" }));
    const cancel = screen.getByRole("button", { name: "Cancel analysis" }); fireEvent.click(cancel); fireEvent.click(cancel);
    expect(cancel).toBeDisabled(); expect(screen.getByText("Cancellation requested")).toBeInTheDocument();
    expect(screen.getByText(/8/)).toBeInTheDocument(); expect(screen.getByText(/ETA 4.0s/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/cancel"))).toHaveLength(1);
    act(() => stream.emit("cancelled", { state: "cancelled" }));
    expect(stream.closed).toBe(true); expect(screen.getByRole("heading", { name: "Analysis cancelled" })).toBeInTheDocument();
    expect(screen.getByText("Partial results were not cached.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze local path" })).toBeEnabled();
    act(() => stream.emitError()); expect(screen.queryByText(/failed safely/)).not.toBeInTheDocument();
  });

  it("closes on completion, fetches the result, and enables the shared investigator", async () => {
    render(<App />); const stream = await startLocal(fetchMock, "done-1");
    fetchMock.mockImplementationOnce(() => response({ job_id: "done-1", state: "completed", result: analysis }));
    act(() => stream.emit("completed", { state: "completed", processed_messages: 42 }));
    await screen.findByTestId("analysis-dashboard");
    expect(stream.closed).toBe(true); expect(screen.queryByText(/Local analysis:/)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/analyze/jobs/done-1", undefined);
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeEnabled();
    act(() => stream.emitError()); expect(screen.getByTestId("analysis-dashboard")).toBeInTheDocument();
  });

  it("sanitizes failure, closes the stream, and permits another workflow", async () => {
    render(<App />); const stream = await startLocal(fetchMock);
    act(() => stream.emit("job-error", { error: "Traceback /secret token=abc stderr" }));
    expect(stream.closed).toBe(true); expect(screen.getByRole("heading", { name: "Analysis failed" })).toBeInTheDocument();
    expect(screen.queryByText(/Traceback|secret|stderr/)).not.toBeInTheDocument();
    fetchMock.mockImplementationOnce(() => response({ job_id: "demo-1" })).mockImplementationOnce(() => response({ job_id: "demo-1", result: analysis }));
    await userEvent.click(screen.getByRole("button", { name: "Run bundled demo" }));
    await screen.findByTestId("analysis-dashboard");
  });

  it("closes streams on replacement and ignores stale events", async () => {
    render(<App />); const first = await startLocal(fetchMock, "old");
    const second = await startLocal(fetchMock, "new"); expect(first.closed).toBe(true);
    act(() => first.emit("cancelled", { state: "cancelled" })); expect(screen.getByText(/Local analysis: running/)).toBeInTheDocument();
    fetchMock.mockImplementationOnce(() => response({ job_id: "demo" })).mockImplementationOnce(() => response({ job_id: "demo", result: analysis }));
    await userEvent.click(screen.getByRole("button", { name: "Run bundled demo" })); expect(second.closed).toBe(true);
  });

  it("closes an active source for Upload and on unmount", async () => {
    const view = render(<App />); const first = await startLocal(fetchMock);
    fetchMock.mockImplementationOnce(() => response(analysis));
    const input = screen.getByLabelText("Upload bag file");
    await userEvent.upload(input, new File(["bag"], "small.mcap")); expect(first.closed).toBe(true); expect(screen.getByTestId("analysis-dashboard")).toBeInTheDocument();
    const second = await startLocal(fetchMock, "unmount"); view.unmount(); expect(second.closed).toBe(true);
  });

  it("handles network EventSource errors as controlled failures", async () => {
    render(<App />); const stream = await startLocal(fetchMock); act(() => stream.emitError());
    expect(stream.closed).toBe(true); expect(screen.getByRole("heading", { name: "Analysis failed" })).toBeInTheDocument();
  });
});
