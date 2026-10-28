import { api } from "../../shared/api/client";
import { useResource } from "../../shared/hooks/useResource";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";
import styles from "./DriftPage.module.css";

/** Where Proxmox differs from the code runway generated. Manual configuration is a bug. */
export function DriftPage() {
  const d = useResource(() => api.drift(), []);
  if (d.state === "loading") return <Skeleton rows={4} label="Comparing Proxmox with the code" />;
  if (d.state === "error") return <ErrorState title="The drift check did not run" detail="runway could not reach Proxmox." onRetry={d.retry} />;
  const { drift, missingAfterCutover, notYetOnProxmox } = d.data;
  return (
    <div className={styles.page}>
      {drift.length === 0 && missingAfterCutover.length === 0 ? (
        <EmptyState title="No drift">
          Every migrated VM matches its generated Terraform. {notYetOnProxmox.length} VMs in the plan have not moved yet.
        </EmptyState>
      ) : (
        <>
          <p className={styles.lead}>Fix these in code, or apply the code again. Do not change the VM in the Proxmox web UI.</p>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">VM</th>
                <th scope="col">Setting</th>
                <th scope="col">In code</th>
                <th scope="col">On Proxmox</th>
              </tr>
            </thead>
            <tbody>
              {drift.map((x) => (
                <tr key={`${x.vm}-${x.field}`}>
                  <th scope="row">{x.vm}</th>
                  <td>{x.field}</td>
                  <td>{x.want || "absent"}</td>
                  <td className={styles.have}>{x.have || "absent"}</td>
                </tr>
              ))}
              {missingAfterCutover.map((vm) => (
                <tr key={vm}>
                  <th scope="row">{vm}</th>
                  <td>the VM</td>
                  <td>exists</td>
                  <td className={styles.have}>missing after a completed cutover</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
