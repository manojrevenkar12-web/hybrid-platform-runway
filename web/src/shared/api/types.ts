/** Shapes returned by the runway API (src/runway/api.py). */
export type Verdict = "auto" | "attention" | "blocked";
export type Result = "done" | "rolled_back" | "needs_person" | "skipped";

export interface Summary {
  estate: { vms: number; memoryGib: number; diskTib: number };
  verdicts: Record<Verdict, number>;
  plan: { start: string; until: string; waves: number; placed: number; unplaced: number; lastWave: string | null; windowsSkippedForFreezes: number };
  cutover: Record<Result, number>;
  blockers: { rule: string; vms: number }[];
}

export interface Wave {
  index: number;
  site: string;
  start: string;
  end: string;
  groups: string[];
  vms: number;
  minutes: number;
  budgetMinutes: number;
  status: "planned" | "done";
  outcomes: Record<Result, number>;
}

export interface Freeze {
  name: string;
  t0: string;
  start: string;
  end: string;
  sites: string[];
}

export interface Calendar {
  timezone: string;
  freezes: Freeze[];
  slots: { start: string; end: string }[];
  skipped: { start: string; site: string; campaign: string }[];
}

export interface VmRow {
  name: string;
  app: string;
  site: string;
  owner: string;
  guest: string;
  cpus: number;
  memoryGib: number;
  diskGib: number;
  verdict: Verdict;
  findings: string[];
  wave: number | null;
  node: string | null;
  unplaced: string | null;
  outcome: Result | null;
}

export interface Finding {
  rule: string;
  verdict: Verdict;
  why: string;
  action: string;
  source: string;
}

export interface VmDetail extends VmRow {
  findingsDetail: Finding[];
  terraformHcl: string | null;
  ansible: Record<string, unknown> | null;
  steps: { step: string; status: string; detail: string; at: string }[];
}

export interface Outcome {
  vm: string;
  result: Result;
  step: string;
  reason: string;
  downtime_s: number;
}

export interface ClusterCapacity {
  cluster: string;
  site: string;
  storage: { name: string; usedGib: number; capacityGib: number };
  memoryAfterNodeLossGib: number;
  nodes: { name: string; memoryGib: number; plannedGib: number; cores: number; plannedVcpus: number; devices: string[] }[];
}

export interface DriftReport {
  drift: { vm: string; field: string; want: string; have: string }[];
  notYetOnProxmox: string[];
  missingAfterCutover: string[];
}
