import type { components } from "./api.generated";
type Report = components["schemas"]["CampaignSummary"];
type Event = components["schemas"]["SecurityEventResponse"];
export function missionMetrics(report: Report, events: Event[], terminal: boolean) {
  const completed = new Set(report.cases.map((c) => c.case_index));
  const active = new Set<number>();
  const calls = new Set<string>();
  for (const event of events) {
    const i = event.permitted_metadata.case_index;
    if (event.event_type === "ATTACK_CASE_STARTED" && typeof i === "number") active.add(i);
    if (event.event_type === "MODEL_INFERENCE_STARTED") calls.add(event.correlation_id);
    if (
      ["ATTACK_CASE_SCORED", "ATTACK_CASE_FAILED"].includes(event.event_type) &&
      typeof i === "number"
    )
      active.delete(i);
  }
  for (const i of completed) active.delete(i);
  const running = terminal ? 0 : active.size;
  const eligible = report.cases.filter(
    (c) => c.case_purpose === "attack" && ["SUCCESS", "FAILURE"].includes(c.attack_outcome),
  );
  const successes = eligible.filter((c) => c.attack_outcome === "SUCCESS").length;
  const controls = report.cases.filter(
    (c) => c.case_purpose === "benign" && !["ERROR", "TIMEOUT"].includes(c.model_execution),
  );
  const falsePositives = controls.filter(
    (c) =>
      c.input_action === "BLOCK" ||
      c.input_action === "TRANSFORM" ||
      c.output_action === "BLOCK" ||
      c.output_action === "TRANSFORM",
  ).length;
  const categories = [...new Set(eligible.map((c) => c.attack_category))]
    .filter(Boolean)
    .map((category) => {
      const rows = eligible.filter((c) => c.attack_category === category);
      return {
        category,
        total: rows.length,
        success: rows.filter((c) => c.attack_outcome === "SUCCESS").length,
      };
    });
  return {
    completed: completed.size,
    running,
    pending: Math.max(0, report.total_cases - completed.size - running),
    calls: calls.size,
    eligible: eligible.length,
    successes,
    controls: controls.length,
    falsePositives,
    categories,
    excluded: report.cases.length - eligible.length - controls.length,
    progress: report.total_cases ? Math.round((100 * completed.size) / report.total_cases) : null,
    // Event sequence is authoritative; timestamps alone never establish case completion.
    series: events
      .filter((e) => ["ATTACK_CASE_SCORED", "ATTACK_CASE_FAILED"].includes(e.event_type))
      .map((e) => ({ sequence: e.sequence, timestamp: e.timestamp })),
  };
}
