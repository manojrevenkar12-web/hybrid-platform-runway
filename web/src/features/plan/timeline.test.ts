import type { Calendar, Wave } from "../../shared/api/types";
import { timeline as T } from "../../theme/tokens";
import { layout, load } from "./timeline";

const wave = (index: number, site: string, start: string, hours = 8): Wave => ({
  index,
  site,
  start,
  end: new Date(Date.parse(start) + hours * 3600_000).toISOString(),
  groups: ["app"],
  vms: 3,
  minutes: 120,
  budgetMinutes: 360,
  status: "planned",
  outcomes: { done: 0, rolled_back: 0, needs_person: 0, skipped: 0 },
});

const cal: Calendar = {
  timezone: "Europe/Berlin",
  freezes: [
    { name: "flight-3", t0: "2026-12-10T10:00:00Z", start: "2026-11-26T10:00:00Z", end: "2026-12-12T10:00:00Z", sites: ["hq"] },
    { name: "year-end", t0: "2026-12-20T23:00:00Z", start: "2026-12-20T23:00:00Z", end: "2027-01-05T23:00:00Z", sites: [] },
  ],
  slots: [],
  skipped: [{ start: "2026-12-01T17:00:00Z", site: "hq", campaign: "flight-3" }],
};

describe("runway timeline layout", () => {
  const waves = [wave(1, "factory", "2026-11-17T17:00:00Z"), wave(2, "hq", "2026-11-17T17:00:00Z"), wave(3, "hq", "2026-12-15T17:00:00Z")];
  const L = layout(cal, waves, Date.parse("2026-11-01T00:00:00Z"));

  it("has a lane per site and places waves of the same window at the same x", () => {
    expect(L.lanes).toEqual(["factory", "hq"]);
    expect(L.waves[0].x).toBe(L.waves[1].x);
    expect(L.waves[0].lane).not.toBe(L.waves[1].lane);
  });

  it("draws a site's freeze only on its lane, and a sitewide blackout on every lane", () => {
    const f3 = L.freezes.filter((f) => f.name === "flight-3");
    expect(f3.map((f) => L.lanes[f.lane])).toEqual(["hq"]);
    expect(L.freezes.filter((f) => f.name === "year-end")).toHaveLength(0); // after the last wave: outside the view
    expect(f3[0].t0x).toBeGreaterThan(f3[0].x);
    expect(f3[0].t0x).toBeLessThan(f3[0].x + f3[0].w);
  });

  it("keeps short windows clickable and measures days evenly", () => {
    expect(Math.min(...L.waves.map((w) => w.w))).toBeGreaterThanOrEqual(T.minWaveWidth);
    const days = (L.waves[2].x - L.waves[1].x) / T.pxPerDay;
    expect(days).toBeCloseTo(28);
    expect(L.today).toBeNull(); // 1 Nov is before the view
  });

  it("marks the windows a freeze took", () => {
    expect(L.skipped).toEqual([expect.objectContaining({ campaign: "flight-3", lane: 1 })]);
  });

  it("measures a wave's share of its budget", () => {
    expect(load(waves[0])).toBeCloseTo(1 / 3);
  });
});
