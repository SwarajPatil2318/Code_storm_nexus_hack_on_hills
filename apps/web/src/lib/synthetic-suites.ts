import library from "../../../../packages/contracts/synthetic-suites.json";
import type { components } from "./api.generated";
export type SuiteName = keyof typeof library.suites;
export const suiteNames = Object.keys(library.suites) as SuiteName[];
export const suiteCases = (name: SuiteName): components["schemas"]["AttackCase"][] =>
  library.suites[name].map((id) =>
    library.cases.find((c) => c.case_id === id)!,
  ) as components["schemas"]["AttackCase"][];
export const libraryVersion = library.library_version;
