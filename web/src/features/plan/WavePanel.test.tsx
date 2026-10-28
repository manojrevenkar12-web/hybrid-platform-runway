import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Wave } from "../../shared/api/types";
import { WavePanel } from "./WavePanel";

const wave: Wave = {
  index: 4,
  site: "hq",
  start: "2026-11-19T17:00:00Z",
  end: "2026-11-20T01:00:00Z",
  groups: ["git"],
  vms: 2,
  minutes: 200,
  budgetMinutes: 360,
  status: "planned",
  outcomes: { done: 0, rolled_back: 0, needs_person: 0, skipped: 0 },
};

const row = (name: string) => ({ name, app: "git", site: "hq", owner: "devops", guest: "linux", cpus: 8, memoryGib: 32, diskGib: 1500, verdict: "auto", findings: [], wave: 4, node: "pve-hq-01", unplaced: null, outcome: null });

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => vi.unstubAllGlobals());

describe("WavePanel", () => {
  it("asks for a wave when none is picked", () => {
    render(<WavePanel wave={null} onRan={() => {}} />);
    expect(screen.getByText("Pick a wave on the runway")).toBeInTheDocument();
  });

  it("cuts a wave over and shows each VM's outcome", async () => {
    const fetch = vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith("/run")
          ? json({ wave: 4, outcomes: [{ vm: "hq-git-01", result: "done", step: "verify", reason: "", downtime_s: 1 }, { vm: "hq-git-02", result: "rolled_back", step: "import", reason: "import failed", downtime_s: 1 }] })
          : json([row("hq-git-01"), row("hq-git-02"), { ...row("other"), wave: 5 }]),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const onRan = vi.fn();
    render(<WavePanel wave={wave} onRan={onRan} />);
    expect(await screen.findByText("hq-git-01")).toBeInTheDocument();
    expect(screen.queryByText("other")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cut over 2 VMs" }));
    expect(await screen.findByText("Moved")).toBeInTheDocument();
    expect(screen.getByText("Rolled back")).toHaveAttribute("title", "import failed");
    expect(onRan).toHaveBeenCalled();
  });

  it("says nothing changed when the API does not answer", async () => {
    const fetch = vi.fn((url: string) => (url.endsWith("/run") ? Promise.reject(new TypeError("down")) : Promise.resolve(json([row("hq-git-01")]))));
    vi.stubGlobal("fetch", fetch);
    render(<WavePanel wave={wave} onRan={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cut over 2 VMs" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was changed");
  });
});
