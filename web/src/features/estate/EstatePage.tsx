import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { api } from "../../shared/api/client";
import type { Verdict } from "../../shared/api/types";
import { useResource } from "../../shared/hooks/useResource";
import { gib, ruleName, site } from "../../shared/format";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";
import { motion as m } from "../../theme/tokens";
import styles from "./EstatePage.module.css";
import { VmDrawer } from "./VmDrawer";

const VERDICTS: { id: Verdict | ""; name: string }[] = [
  { id: "", name: "All" },
  { id: "blocked", name: "Blocked" },
  { id: "attention", name: "Need preparation" },
  { id: "auto", name: "Move by themselves" },
];

export function EstatePage({ initialVerdict = "" }: { initialVerdict?: Verdict | "" }) {
  const [verdict, setVerdict] = useState<Verdict | "">(initialVerdict);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const vms = useResource(() => api.vms({ verdict, q }), [verdict, q]);

  return (
    <div className={styles.page}>
      <div className={styles.filters}>
        <div role="radiogroup" aria-label="Verdict" className={styles.segments}>
          {VERDICTS.map((v) => (
            <button key={v.id} type="button" role="radio" aria-checked={verdict === v.id} className={verdict === v.id ? styles.on : undefined} onClick={() => setVerdict(v.id)}>
              {v.name}
            </button>
          ))}
        </div>
        <label className={styles.search}>
          <span>Find a VM or application</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="plm, ad, factory-mes" />
        </label>
      </div>
      {vms.state === "loading" && <Skeleton rows={8} label="Loading the estate" />}
      {vms.state === "error" && <ErrorState title="The estate did not load" onRetry={vms.retry} />}
      {vms.state === "ready" && vms.data.length === 0 && <EmptyState title="No VMs match">Clear the search or pick another verdict.</EmptyState>}
      {vms.state === "ready" && vms.data.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>{vms.data.length} VMs</caption>
            <thead>
              <tr>
                <th scope="col">VM</th>
                <th scope="col">Application</th>
                <th scope="col">Site</th>
                <th scope="col">Size</th>
                <th scope="col">Verdict</th>
                <th scope="col">Why</th>
                <th scope="col">Wave</th>
              </tr>
            </thead>
            <tbody>
              {vms.data.map((v, i) => (
                <motion.tr key={v.name} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ ...m.enter, delay: Math.min(i, 15) * m.rowStagger }}>
                  <th scope="row">
                    <button type="button" className={styles.vmLink} onClick={() => setOpen(v.name)}>
                      {v.name}
                    </button>
                  </th>
                  <td>{v.app || "none"}</td>
                  <td>{site(v.site)}</td>
                  <td>
                    {v.cpus} vCPU, {gib(v.memoryGib)}, {gib(v.diskGib)} disk
                  </td>
                  <td>
                    <span className={`${styles.verdict} ${styles[v.verdict]}`}>{VERDICTS.find((x) => x.id === v.verdict)?.name}</span>
                  </td>
                  <td className={styles.why}>{v.findings.map((f) => ruleName[f] ?? f).join(", ") || "nothing to prepare"}</td>
                  <td>{v.wave ?? (v.unplaced ? "no room" : "stays")}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AnimatePresence>{open && <VmDrawer key={open} name={open} onClose={() => setOpen(null)} />}</AnimatePresence>
    </div>
  );
}
