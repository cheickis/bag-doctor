import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalysisDashboard } from "./main";
import { analysis, legacyAnalysis } from "./test/fixtures";

describe("shared dashboard", () => {
  it("shows exact summary counts and all topic classifications", () => {
    render(<AnalysisDashboard analysis={analysis} jobId="job" />);
    expect(screen.getByText("12.5s")).toBeInTheDocument(); expect(screen.getByText("42")).toBeInTheDocument(); expect(screen.getByText("7")).toBeInTheDocument();
    for (const classification of ["periodic", "event-driven", "unknown", "user-configured"]) expect(screen.getByText(classification)).toBeInTheDocument();
  });
  it("falls back to returned array lengths and topic message sums", () => {
    render(<AnalysisDashboard analysis={legacyAnalysis} jobId={null} />);
    expect(screen.getAllByText("6")).toHaveLength(2); expect(screen.getAllByText("1")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Investigate with GPT-5.6" })).toBeDisabled();
  });
});
