import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { api } from "../../shared/api/client";
import type { Outcome, Wave } from "../../shared/api/types";
import { useResource } from "../../shared/hooks/useResource";
import { day, hours, resultName, site, time } from "../../shared/format";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";
import { motion as m } from "../../theme/tokens";
import styles from "./WavePanel.module.css";
import { load } from "./timeline";

export function WavePanel({ wave, onRan }: { wave: Wave | null; onRan: () => void }) {
  if (!wave)
    return (
      <section className={styles.panel} aria-label="Wave">
        <EmptyState title="Pick a wave on the runway">Each block is one maintenance window at one site. Its number is the order waves run in.</EmptyState>
      </section>
    );
  return <Loaded key={wave.index} wave={wave} onRan={onRan} />;
}

function Loaded({ wave, onRan }: { wave: Wave; onRan: () => void }) {
  const vms = useResource(() => api.vms(), [], null);
  const [running, setRunning] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<Outcome[] | null>(null);
  const share = load(wave);

  async function run() {
    setRunning(true);
    setProblem(null);
    try {
      const r = await api.runWave(wave.index);
      setOutcomes(r.outcomes);
      onRan();
      if (vms.state === "ready") vms.refresh();
    } catch {
      setProblem("The cutover did not start: runway did not answer. Nothing was changed; try again.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className={styles.panel} aria-label={`Wave ${wave.index}`}>
      <header className={styles.head}>
        <h2>
          Wave {wave.index} <span>{site(wave.site)}</span>
        </h2>
        <p>
          {day(wave.start)}, {time(wave.start)} to {time(wave.end)}
        </p>
      </header>
      <div className={styles.budget} aria-label={`Uses ${Math.round(share * 100)} percent of the window budget`}>
        <div className={styles.bar}>
          <motion.span className={styles.used} initial={{ scaleX: 0 }} animate={{ scaleX: share }} transition={m.sweep} />
        </div>
        <p>
          {hours(wave.minutes)} of {hours(wave.budgetMinutes)} planned. A quarter of the window stays free for rolling back.
        </p>
      </div>
      <p className={styles.groups}>Applications: {wave.groups.join(", ")}</p>
      {wave.status === "planned" && !outcomes && (
        <button type="button" className={styles.run} onClick={() => void run()} disabled={running}>
          {running ? "Cutting over" : `Cut over ${wave.vms} VMs`}
        </button>
      )}
      {problem && (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      )}
      {vms.state === "loading" && <Skeleton rows={4} label="Loading the wave's VMs" />}
      {vms.state === "error" && <ErrorState title="The wave's VMs did not load" onRetry={vms.retry} />}
      {vms.state === "ready" && (
        <ol className={styles.vms}>
          <AnimatePresence initial={false}>
            {vms.data
              .filter((v) => v.wave === wave.index)
              .map((v, i) => {
                const o = outcomes?.find((x) => x.vm === v.name);
                const result = o?.result ?? v.outcome;
                return (
                  <motion.li key={v.name} layout="position" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ ...m.enter, delay: o ? i * m.rowStagger * 2 : 0 }}>
                    <span className={styles.vm}>{v.name}</span>
                    <span className={styles.node}>{v.node}</span>
                    {result && <span className={`${styles.result} ${styles[result]}`} title={o?.reason || undefined}>{resultName[result]}</span>}
                  </motion.li>
                );
              })}
          </AnimatePresence>
        </ol>
      )}
    </section>
  );
}
