import type { Calendar, Wave } from "../../shared/api/types";
import { timeline as T } from "../../theme/tokens";

const DAY = 86_400_000;

export interface Layout {
  width: number;
  lanes: string[];
  ticks: { x: number; label: string }[];
  freezes: { name: string; lane: number; x: number; w: number; t0x: number }[];
  waves: { wave: Wave; lane: number; x: number; w: number }[];
  skipped: { lane: number; x: number; campaign: string }[];
  today: number | null;
}

/**
 * Where everything sits on the runway: one lane per site, days along the x axis. Freezes are drawn
 * on the lanes of the sites they hold (a campaign without sites holds every lane).
 */
export function layout(cal: Calendar, waves: Wave[], now: number = Date.now()): Layout {
  const lanes = [...new Set(waves.map((w) => w.site))].sort();
  for (const s of cal.skipped) if (!lanes.includes(s.site)) lanes.push(s.site);
  const times = [...waves.map((w) => Date.parse(w.start)), ...waves.map((w) => Date.parse(w.end))];
  const first = times.length ? Math.min(...times) : now;
  const last = times.length ? Math.max(...times) : now + 30 * DAY;
  const start = Math.floor(first / DAY) * DAY - T.paddingDays * DAY;
  const end = Math.ceil(last / DAY) * DAY + T.paddingDays * DAY;
  const x = (t: number) => ((t - start) / DAY) * T.pxPerDay;
  const ticks = [];
  for (let t = start; t <= end; t += DAY) {
    const d = new Date(t);
    if (d.getUTCDay() === 1) ticks.push({ x: x(t), label: d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) });
  }
  const freezes = cal.freezes.flatMap((f) => {
    const s = Math.max(Date.parse(f.start), start);
    const e = Math.min(Date.parse(f.end), end);
    if (e <= s) return [];
    const on = f.sites.length ? f.sites : lanes;
    return on
      .filter((site) => lanes.includes(site))
      .map((site) => ({ name: f.name, lane: lanes.indexOf(site), x: x(s), w: x(e) - x(s), t0x: x(Date.parse(f.t0)) }));
  });
  return {
    width: x(end),
    lanes,
    ticks,
    freezes,
    waves: waves.map((w) => ({
      wave: w,
      lane: lanes.indexOf(w.site),
      x: x(Date.parse(w.start)),
      w: Math.max(T.minWaveWidth, x(Date.parse(w.end)) - x(Date.parse(w.start))),
    })),
    skipped: cal.skipped.filter((s) => lanes.includes(s.site)).map((s) => ({ lane: lanes.indexOf(s.site), x: x(Date.parse(s.start)), campaign: s.campaign })),
    today: now >= start && now <= end ? x(now) : null,
  };
}

/** Share of a wave's window budget its VMs use. */
export function load(w: Wave): number {
  return w.budgetMinutes ? Math.min(1, w.minutes / w.budgetMinutes) : 0;
}
