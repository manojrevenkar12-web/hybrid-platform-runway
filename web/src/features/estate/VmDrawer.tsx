import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { api } from "../../shared/api/client";
import { useResource } from "../../shared/hooks/useResource";
import { ruleName, site } from "../../shared/format";
import { ErrorState, Skeleton } from "../../shared/ui/states";
import { motion as m } from "../../theme/tokens";
import styles from "./VmDrawer.module.css";

/** Everything about one VM: why it moves or not, what code runway generated for it, and its cutover log. */
export function VmDrawer({ name, onClose }: { name: string; onClose: () => void }) {
  const vm = useResource(() => api.vm(name), [name], null);
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <motion.aside
      className={styles.drawer}
      role="dialog"
      aria-modal="true"
      aria-label={name}
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={m.enter}
    >
      <header className={styles.head}>
        <h2>{name}</h2>
        <button ref={close} type="button" onClick={onClose} className={styles.close}>
          Close
        </button>
      </header>
      {vm.state === "loading" && <Skeleton rows={6} label={`Loading ${name}`} />}
      {vm.state === "error" && <ErrorState title="This VM did not load" detail={vm.error.message} onRetry={vm.retry} />}
      {vm.state === "ready" && (
        <div className={styles.body}>
          <p className={styles.lead}>
            {vm.data.app ? `${vm.data.app}, ` : ""}
            {site(vm.data.site)}, owner {vm.data.owner || "unknown"}.{" "}
            {vm.data.wave ? `Moves in wave ${vm.data.wave} to ${vm.data.node}.` : vm.data.unplaced ? `Not placed: ${vm.data.unplaced}.` : "Stays on vSphere for now."}
          </p>
          <h3>Findings</h3>
          {vm.data.findingsDetail.length === 0 ? (
            <p className={styles.muted}>No findings: runway moves this VM as it is.</p>
          ) : (
            <ul className={styles.findings}>
              {vm.data.findingsDetail.map((f) => (
                <li key={f.rule} className={styles[f.verdict]}>
                  <strong>{ruleName[f.rule] ?? f.rule}</strong>
                  <p>{f.why}</p>
                  <p className={styles.action}>{f.action}</p>
                  {f.source.startsWith("http") && (
                    <a href={f.source} target="_blank" rel="noreferrer">
                      Source
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
          {vm.data.terraformHcl && (
            <>
              <h3>Generated Terraform</h3>
              <pre className={styles.code}>{vm.data.terraformHcl}</pre>
            </>
          )}
          {vm.data.steps.length > 0 && (
            <>
              <h3>Cutover log</h3>
              <ol className={styles.steps}>
                {vm.data.steps.map((s, i) => (
                  <li key={i}>
                    {s.step} <span className={s.status === "failed" ? styles.failed : undefined}>{s.status}</span>
                    {s.detail && <span className={styles.muted}> {s.detail}</span>}
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}
    </motion.aside>
  );
}
