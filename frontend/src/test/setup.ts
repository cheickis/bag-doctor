import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { FakeEventSource } from "./fakeEventSource";

afterEach(() => {
  cleanup();
  FakeEventSource.reset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
