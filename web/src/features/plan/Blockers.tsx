import type { Summary } from "../../shared/api/types";
import { ruleName } from "../../shared/format";
import { EmptyState } from "../../shared/ui/states";
import styles from "./Blockers.module.css";

/** What keeps VMs on vSphere, biggest first: the list a platform team works down. */
export function Blockers({ summary, onOpen }: { summary: Summary; onOpen: () => void }) {
  if (!summary.blockers.length) return <EmptyState title="Nothing is blocked">Every VM in the estate can move.</EmptyState>;
  const max = Math.max(...summary.blockers.map((b) => b.vms));
  return (
    <section className={styles.blockers} aria-labelledby="blockers-title">
      <h2 id="blockers-title">What keeps VMs on vSphere</h2>
      <ul>
        {summary.blockers.map((b) => (
          <li key={b.rule}>
            <span className={styles.name}>{ruleName[b.rule] ?? b.rule}</span>
            <span className={styles.bar} style={{ width: `${(b.vms / max) * 100}%` }} aria-hidden="true" />
            <span className={styles.count}>{b.vms}</span>
          </li>
        ))}
      </ul>
      <button type="button" className={styles.link} onClick={onOpen}>
        See the blocked VMs and what to do
      </button>
    </section>
  );
}
