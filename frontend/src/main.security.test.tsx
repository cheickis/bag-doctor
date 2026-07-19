import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import mainSource from "./main.tsx?raw";
import uiSource from "./components/ui.tsx?raw";
import { AnalysisDashboard, type Analysis } from "./main";

describe("frontend security", () => {
  it("renders model-generated HTML-like payloads literally", () => {
    const payload = '<img src=x onerror=alert(1)><script>alert(1)</script>';
    const fixture: Analysis = { summary: { duration_seconds: 1, total_messages: 1, topic_count: 1 }, topics: [{ topic: payload, message_count: 1 }], incidents: [] };
    render(<AnalysisDashboard analysis={fixture} jobId={null} />);
    expect(screen.getByText(payload)).toBeInTheDocument(); expect(document.querySelector("script")).toBeNull(); expect(document.querySelector("img")).toBeNull();
  });
  it("does not use raw HTML injection in production React source", () => {
    expect(`${mainSource}\n${uiSource}`).not.toContain("dangerouslySetInnerHTML");
  });
});
