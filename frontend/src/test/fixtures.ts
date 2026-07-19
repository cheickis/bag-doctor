import type { Analysis } from "../main";

export const evidenceId = "ev_1234567890abcdef12345678";
export const analysis: Analysis = {
  summary: { duration_seconds: 12.5, topic_count: 4, total_messages: 42 },
  topics: [
    { topic: "/periodic", message_count: 10, timing_classification: "periodic" },
    { topic: "/event", message_count: 11, timing_classification: "event-driven" },
    { topic: "/unknown", message_count: 12, timing_classification: "unknown" },
    { topic: "/configured", message_count: 9, timing_classification: "user-configured" },
  ],
  incidents: [{ evidence_id: evidenceId, topic: "/periodic", duration_seconds: 2.5 }],
  incident_count: 7,
};
export const legacyAnalysis: Analysis = {
  summary: { duration_seconds: 3 },
  topics: [{ topic: "/legacy", message_count: 6, timing_classification: "unknown" }],
  incidents: [{ evidence_id: "legacy:id", topic: "/legacy", duration_seconds: 1 }],
};
export const investigation = {
  model: "gpt-5.6-terra", summary: "A timing disruption is visible.",
  hypotheses: [{ rank: 1, hypothesis: "Possible scheduler delay", reasoning: "The bounded gap is unusually long.", evidence_ids: [evidenceId] }],
  limitations: ["Timing measurements alone do not establish a physical root cause."],
};
