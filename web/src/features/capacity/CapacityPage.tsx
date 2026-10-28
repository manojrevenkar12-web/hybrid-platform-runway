import { motion } from "framer-motion";
import { api } from "../../shared/api/client";
import { useResource } from "../../shared/hooks/useResource";
import { gib, site } from "../../shared/format";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";
import { motion as m } from "../../theme/tokens";
import styles from "./CapacityPage.module.css";

/** Planned memory per node, and the line each cluster must stay under to survive losing its largest node. */
export function CapacityPage() {
  const cap = useResource(() => api.capacity(), [], null);
  if (cap.state === "loading") return <Skeleton rows={6} label="Loading capacity" />;
  if (cap.state === "error") return <ErrorState title="Capacity did not load" onRetry={cap.retry} />;
  if (!cap.data.length) return <EmptyState title="No Proxmox clusters configured">Add them to config/target.yaml.</EmptyState>;
  return (
    <div className={styles.grid}>
      {cap.data.map((c) => {
        const planned = c.nodes.reduce((a, n) => a + n.plannedGib, 0);
        const headroom = c.memoryAfterNodeLossGib - planned;
        return (
          <section key={c.cluster} className={styles.cluster} aria-labelledby={`c-${c.cluster}`}>
            <h2 id={`c-${c.cluster}`}>
              {c.cluster} <span>{site(c.site)}</span>
            </h2>
            <p className={headroom < c.nodes[0].memoryGib * 0.1 ? styles.tight : styles.fine}>
              {gib(planned)} planned. It can lose its largest node with {gib(Math.max(0, headroom))} to spare.
            </p>
            <ul className={styles.nodes}>
              {c.nodes.map((n) => (
                <li key={n.name}>
                  <span className={styles.name}>
                    {n.name}
                    {n.devices.length > 0 && <em>{n.devices.join(", ")}</em>}
                  </span>
                  <span className={styles.track} aria-label={`${Math.round((n.plannedGib / n.memoryGib) * 100)} percent of memory planned`}>
                    <motion.span className={styles.fill} initial={{ scaleX: 0 }} animate={{ scaleX: n.plannedGib / n.memoryGib }} transition={m.sweep} />
                  </span>
                  <span className={styles.num}>
                    {gib(n.plannedGib)} / {gib(n.memoryGib)}
                  </span>
                </li>
              ))}
            </ul>
            <p className={styles.storage}>
              {c.storage.name}: {gib(c.storage.usedGib)} of {gib(c.storage.capacityGib)}
            </p>
          </section>
        );
      })}
    </div>
  );
}
