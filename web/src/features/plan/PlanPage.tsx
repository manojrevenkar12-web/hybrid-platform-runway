import { useState } from "react";
import { api } from "../../shared/api/client";
import { useResource } from "../../shared/hooks/useResource";
import { short } from "../../shared/format";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";
import { Blockers } from "./Blockers";
import styles from "./PlanPage.module.css";
import { Timeline } from "./Timeline";
import { WavePanel } from "./WavePanel";

export function PlanPage({ onShowBlocked }: { onShowBlocked: () => void }) {
  const summary = useResource(() => api.summary(), []);
  const waves = useResource(() => api.waves(), []);
  const calendar = useResource(() => api.calendar(), [], null);
  const [selected, setSelected] = useState<number | null>(null);

  const refresh = () => {
    if (summary.state === "ready") summary.refresh();
    if (waves.state === "ready") waves.refresh();
  };

  return (
    <div className={styles.page}>
      {summary.state === "loading" && <Skeleton rows={2} label="Loading the programme" />}
      {summary.state === "error" && <ErrorState title="runway did not answer" detail="The plan could not be loaded. Nothing has changed." onRetry={summary.retry} />}
      {summary.state === "ready" && (
        <section className={styles.status} aria-label="Programme">
          <h1>
            {summary.data.plan.placed} of {summary.data.estate.vms} VMs planned onto Proxmox VE
          </h1>
          <dl>
            <div>
              <dt>Waves</dt>
              <dd>{summary.data.plan.waves}</dd>
            </div>
            <div>
              <dt>Last wave ends</dt>
              <dd>{summary.data.plan.lastWave ? short(summary.data.plan.lastWave) : "none"}</dd>
            </div>
            <div className={styles.blocked}>
              <dt>Blocked</dt>
              <dd>{summary.data.verdicts.blocked}</dd>
            </div>
            <div className={styles.attention}>
              <dt>Need preparation</dt>
              <dd>{summary.data.verdicts.attention}</dd>
            </div>
            <div className={styles.freeze}>
              <dt>Windows given up to freezes</dt>
              <dd>{summary.data.plan.windowsSkippedForFreezes}</dd>
            </div>
            <div>
              <dt>Moved so far</dt>
              <dd>{summary.data.cutover.done}</dd>
            </div>
          </dl>
        </section>
      )}

      {(waves.state === "loading" || calendar.state === "loading") && <Skeleton rows={3} label="Loading the runway" />}
      {waves.state === "error" && <ErrorState title="The waves did not load" onRetry={waves.retry} />}
      {calendar.state === "error" && <ErrorState title="The calendar did not load" onRetry={calendar.retry} />}
      {waves.state === "ready" && calendar.state === "ready" &&
        (waves.data.length === 0 ? (
          <EmptyState title="No waves yet">Nothing in the estate can move before the plan's end date, or the inventory is empty.</EmptyState>
        ) : (
          <Timeline calendar={calendar.data} waves={waves.data} selected={selected} onSelect={setSelected} />
        ))}

      <div className={styles.below}>
        <WavePanel wave={waves.state === "ready" ? (waves.data.find((w) => w.index === selected) ?? null) : null} onRan={refresh} />
        {summary.state === "ready" && <Blockers summary={summary.data} onOpen={onShowBlocked} />}
      </div>
    </div>
  );
}
