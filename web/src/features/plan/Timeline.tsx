import { motion } from "framer-motion";
import type { Calendar, Wave } from "../../shared/api/types";
import { day, site, time } from "../../shared/format";
import { motion as m, timeline as T } from "../../theme/tokens";
import styles from "./Timeline.module.css";
import { layout } from "./timeline";

/**
 * The runway: every wave in its maintenance window, on the lane of its site, with launch freezes
 * drawn across the lanes they hold. The one view that answers "are we on track, and are we clear
 * of the launches?"
 */
export function Timeline({ calendar, waves, selected, onSelect }: { calendar: Calendar; waves: Wave[]; selected: number | null; onSelect: (i: number) => void }) {
  const L = layout(calendar, waves);
  const height = T.axisHeight + L.lanes.length * T.laneHeight;
  return (
    <div className={styles.frame}>
      <div className={styles.labels} style={{ paddingTop: T.axisHeight }}>
        {L.lanes.map((l) => (
          <div key={l} className={styles.laneLabel} style={{ height: T.laneHeight }}>
            {site(l)}
          </div>
        ))}
      </div>
      <div className={styles.scroll} role="region" aria-label="Migration timeline" tabIndex={0}>
        <div className={styles.canvas} style={{ width: L.width, height }}>
          {L.ticks.map((t) => (
            <div key={t.x} className={styles.tick} style={{ left: t.x, height }}>
              <span>{t.label}</span>
            </div>
          ))}
          {L.lanes.map((l, i) => (
            <div key={l} className={styles.lane} style={{ top: T.axisHeight + i * T.laneHeight, height: T.laneHeight }} />
          ))}
          {L.freezes.map((f) => (
            <motion.div
              key={`${f.name}-${f.lane}`}
              className={styles.freeze}
              style={{ left: f.x, width: f.w, top: T.axisHeight + f.lane * T.laneHeight, height: T.laneHeight, transformOrigin: "left" }}
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={m.sweep}
              title={`${f.name}: nothing changes at this site`}
            >
              <span className={styles.freezeName}>{f.name}</span>
              {f.t0x >= f.x && f.t0x <= f.x + f.w && <span className={styles.t0} style={{ left: f.t0x - f.x }} aria-label={`${f.name} launch`} />}
            </motion.div>
          ))}
          {L.skipped.map((s, i) => (
            <span key={i} className={styles.skipped} style={{ left: s.x, top: T.axisHeight + s.lane * T.laneHeight + T.laneHeight - 10 }} title={`window skipped for ${s.campaign}`} />
          ))}
          {L.waves.map((w, i) => (
            <motion.button
              key={w.wave.index}
              type="button"
              className={`${styles.wave} ${w.wave.status === "done" ? styles.done : ""} ${selected === w.wave.index ? styles.selected : ""}`}
              style={{ left: w.x, width: w.w, top: T.axisHeight + w.lane * T.laneHeight + 8, height: T.laneHeight - 16 }}
              initial={{ opacity: 0, y: m.rowRise }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...m.enter, delay: 0.3 + i * m.rowStagger }}
              onClick={() => onSelect(w.wave.index)}
              aria-pressed={selected === w.wave.index}
              aria-label={`Wave ${w.wave.index}, ${site(w.wave.site)}, ${day(w.wave.start)} ${time(w.wave.start)}, ${w.wave.vms} VMs`}
            >
              {w.wave.index}
            </motion.button>
          ))}
          {L.today !== null && <div className={styles.today} style={{ left: L.today, height }} aria-hidden="true" />}
        </div>
      </div>
      <p className={styles.legend}>
        <span className={styles.keyWave} /> wave in a maintenance window <span className={styles.keyFreeze} /> launch freeze or blackout
        <span className={styles.keySkip} /> window skipped for a freeze
      </p>
    </div>
  );
}
