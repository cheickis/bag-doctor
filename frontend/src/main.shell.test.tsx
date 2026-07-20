import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import sourceHtml from "../index.html?raw";
import productionHtml from "../../src/bag_doctor/web/dist/index.html?raw";
import App, { AnalysisDashboard } from "./main";
import { analysis, investigation } from "./test/fixtures";

const response = (body: unknown) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) } as Response);

describe("application shell", () => {
  beforeEach(() => localStorage.clear());

  it("collapses, restores, and preserves usable navigation", async () => {
    const first = render(<App />);
    expect(screen.getByRole("link", { name: "Overview" })).toHaveTextContent("Overview");
    expect(screen.getAllByRole("link").filter(link => link.hasAttribute("aria-current"))).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "location");
    await userEvent.click(screen.getByRole("link", { name: "Topics" }));
    expect(screen.getByRole("link", { name: "Topics" })).toHaveAttribute("aria-current", "location");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    await userEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(screen.getByRole("button", { name: "Expand navigation" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "Evidence" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Topics" })).toHaveAttribute("aria-current", "location");
    expect(localStorage.getItem("bag-doctor-sidebar-collapsed")).toBe("true");
    first.unmount(); render(<App />);
    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeInTheDocument();
  });

  it("includes mobile viewport metadata in source and production entries", () => {
    for (const html of [sourceHtml, productionHtml]) {
      expect(html).toMatch(/<meta[^>]+name=["']viewport["'][^>]+width=device-width/i);
    }
  });

  it("tracks intersecting sections and disconnects the observer", () => {
    let callback!: IntersectionObserverCallback;
    const disconnect = vi.fn();
    class Observer {
      constructor(cb: IntersectionObserverCallback) { callback = cb; }
      observe = vi.fn(); disconnect = disconnect; unobserve = vi.fn(); takeRecords = () => [];
      root = null; rootMargin = ""; thresholds = [];
    }
    vi.stubGlobal("IntersectionObserver", Observer);
    const view = render(<App />);
    const investigator = document.getElementById("gpt-5.6")!;
    act(() => callback([{ target: investigator, isIntersecting: true, intersectionRatio: 1 } as unknown as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(screen.getByRole("link", { name: "Investigator" })).toHaveAttribute("aria-current", "location");
    view.unmount(); expect(disconnect).toHaveBeenCalledOnce();
  });

  it("supports persisted light and dark themes and rejects invalid preferences", async () => {
    render(<App />); const select = screen.getByRole("combobox", { name: "Theme" });
    await userEvent.selectOptions(select, "light"); expect(document.documentElement).toHaveAttribute("data-theme", "light");
    await userEvent.selectOptions(select, "dark"); expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("bag-doctor-theme")).toBe("dark");
    localStorage.setItem("bag-doctor-theme", "broken");
    expect(select).toHaveValue("dark");
  });

  it("system theme follows and reacts to media changes", () => {
    let listener = () => {};
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: (_: string, fn: () => void) => { listener = fn; }, removeEventListener: vi.fn() })));
    render(<App />); expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    vi.mocked(matchMedia).mock.results[0].value.matches = false; listener();
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });

  it("collapses and reopens the desktop investigator without losing output", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(investigation)));
    render(<AnalysisDashboard analysis={analysis} jobId="job" />);
    await userEvent.click(screen.getByRole("button", { name: "Investigate with GPT-5.6" }));
    expect(await screen.findByText("A timing disruption is visible.")).toBeInTheDocument();
    expect(screen.getByText("Codex CLI · gpt-5.6-terra")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Collapse GPT-5.6 Investigator" }));
    expect(screen.getByRole("button", { name: "Open GPT-5.6 Investigator" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open GPT-5.6 Investigator" })).toHaveClass("icon-button");
    await userEvent.click(screen.getByRole("button", { name: "Open GPT-5.6 Investigator" }));
    expect(screen.getByText("A timing disruption is visible.")).toBeInTheDocument();
  });
});
