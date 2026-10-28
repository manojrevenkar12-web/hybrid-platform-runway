import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { motion as m } from "../../theme/tokens";
import styles from "./states.module.css";

/** Grey bars in the shape of what is loading, so the layout does not jump when it arrives. */
export function Skeleton({ rows = 6, label }: { rows?: number; label: string }) {
  return (
    <div className={styles.skeleton} role="status" aria-live="polite" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={styles.skeletonRow}>
          <span className={styles.bar} style={{ width: `${40 + ((i * 37) % 45)}%` }} />
          <span className={styles.bar} style={{ width: `${70 - ((i * 23) % 30)}%` }} />
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ title, detail, onRetry }: { title: string; detail?: string; onRetry: () => void }) {
  return (
    <motion.div className={styles.error} role="alert" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={m.enter}>
      <p className={styles.title}>{title}</p>
      {detail && <p className={styles.detail}>{detail}</p>}
      <button type="button" className={styles.retry} onClick={onRetry}>
        Try again
      </button>
    </motion.div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <motion.div className={styles.empty} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={m.enter}>
      <p className={styles.title}>{title}</p>
      {children && <div className={styles.detail}>{children}</div>}
    </motion.div>
  );
}
