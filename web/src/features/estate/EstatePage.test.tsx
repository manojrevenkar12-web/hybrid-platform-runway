import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EstatePage } from "./EstatePage";

afterEach(() => vi.unstubAllGlobals());

const vm = { name: "hq-plm-db-02", app: "plm-db", site: "hq", owner: "engineering-it", guest: "linux", cpus: 16, memoryGib: 128, diskGib: 2500, verdict: "blocked", findings: ["rdm-disk"], wave: null, node: null, unplaced: null, outcome: null };

describe("EstatePage", () => {
  it("shows a skeleton, then the VMs with plain-language reasons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([vm]))));
    render(<EstatePage initialVerdict="blocked" />);
    expect(screen.getByRole("status", { name: "Loading the estate" })).toBeInTheDocument();
    expect(await screen.findByText("hq-plm-db-02")).toBeInTheDocument();
    expect(screen.getByText("Raw device mapping")).toBeInTheDocument();
    expect(screen.getByText("Headquarters")).toBeInTheDocument();
    expect((vi.mocked(fetch).mock.calls[0][0] as string)).toContain("verdict=blocked");
  });

  it("offers a retry when runway does not answer, and an empty state when nothing matches", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new TypeError("down")).mockResolvedValue(new Response("[]")));
    render(<EstatePage />);
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No VMs match")).toBeInTheDocument();
  });

  it("opens a VM with its findings, sources and generated Terraform", async () => {
    const detail = { ...vm, findingsDetail: [{ rule: "rdm-disk", verdict: "blocked", why: "A raw device mapping is a LUN.", action: "Storage team maps it.", source: "https://pve.proxmox.com/wiki/Migrate_to_Proxmox_VE" }], terraformHcl: null, ansible: null, steps: [] };
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url.includes("/vms/") ? detail : [vm])))));
    render(<EstatePage />);
    await userEvent.click(await screen.findByRole("button", { name: "hq-plm-db-02" }));
    expect(await screen.findByRole("dialog", { name: "hq-plm-db-02" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Source" })).toHaveAttribute("href", "https://pve.proxmox.com/wiki/Migrate_to_Proxmox_VE");
  });
});
