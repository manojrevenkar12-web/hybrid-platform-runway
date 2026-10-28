const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Berlin" });
const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });
const shortFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Europe/Berlin" });

export const day = (iso: string) => dayFmt.format(new Date(iso));
export const time = (iso: string) => timeFmt.format(new Date(iso));
export const short = (iso: string) => shortFmt.format(new Date(iso));

export function hours(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
}

export function gib(n: number): string {
  return n >= 1024 ? `${(n / 1024).toFixed(1)} TiB` : `${Math.round(n)} GiB`;
}

/** Plain-language names for rule ids, as the console shows them. */
export const ruleName: Record<string, string> = {
  "vsan-disk": "Disk on vSAN",
  "encrypted-disk": "Encrypted disk",
  "rdm-disk": "Raw device mapping",
  "datastore-plus": "Datastore name with +",
  "unmapped-network": "Network not mapped",
  "device-not-on-target": "Device missing on Proxmox",
  "no-target-cluster": "No cluster at the site",
  "pci-passthrough": "Device passthrough",
  "independent-disk": "Independent disk",
  snapshots: "Snapshots to consolidate",
  "windows-virtio": "Windows needs VirtIO",
  vtpm: "vTPM and BitLocker",
  "no-disks": "No disks",
  "efi-firmware": "UEFI firmware",
  "linux-nic-rename": "Interface names pinned",
  "vmware-tools": "VMware Tools swapped",
};

export const resultName: Record<string, string> = {
  done: "Moved",
  rolled_back: "Rolled back",
  needs_person: "Needs a person",
  skipped: "Not started",
};

export const siteName: Record<string, string> = { hq: "Headquarters", factory: "Factory", launch: "Launch site" };
export const site = (s: string) => siteName[s] ?? s;
