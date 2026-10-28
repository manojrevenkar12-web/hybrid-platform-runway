import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { CapacityPage } from "../features/capacity/CapacityPage";
import { DriftPage } from "../features/drift/DriftPage";
import { EstatePage } from "../features/estate/EstatePage";
import { PlanPage } from "../features/plan/PlanPage";
import type { Verdict } from "../shared/api/types";
import { motion as m } from "../theme/tokens";
import styles from "./App.module.css";

const TABS = [
  { id: "plan", name: "Plan" },
  { id: "estate", name: "Estate" },
  { id: "capacity", name: "Capacity" },
  { id: "drift", name: "Drift" },
] as const;
type Tab = (typeof TABS)[number]["id"];

function fromHash(): Tab {
  const t = window.location.hash.slice(1);
  return (TABS.find((x) => x.id === t)?.id ?? "plan") as Tab;
}

export function App() {
  const [tab, setTab] = useState<Tab>(fromHash);
  const [verdict, setVerdict] = useState<Verdict | "">("");

  useEffect(() => {
    window.history.replaceState(null, "", `#${tab}`);
  }, [tab]);

  return (
    <div className={styles.shell}>
      <header className={styles.top}>
        <p className={styles.brand}>
          <strong>Runway</strong>
          <span>VMware to Proxmox VE, clear of every launch</span>
        </p>
        <nav aria-label="Sections">
          <ul className={styles.tabs}>
            {TABS.map((t) => (
              <li key={t.id}>
                <button type="button" aria-current={tab === t.id ? "page" : undefined} className={tab === t.id ? styles.on : undefined} onClick={() => setTab(t.id)}>
                  {t.name}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main className={styles.main}>
        <AnimatePresence mode="wait">
          <motion.div key={tab} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={m.swap}>
            {tab === "plan" && (
              <PlanPage
                onShowBlocked={() => {
                  setVerdict("blocked");
                  setTab("estate");
                }}
              />
            )}
            {tab === "estate" && <EstatePage initialVerdict={verdict} />}
            {tab === "capacity" && <CapacityPage />}
            {tab === "drift" && <DriftPage />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
