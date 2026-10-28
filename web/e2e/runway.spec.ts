import { expect, test } from "@playwright/test";

test("the plan keeps every wave clear of the launch freezes at its site", async ({ page }) => {
  await page.goto("/#plan");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/\d+ of \d+ VMs planned onto Proxmox VE/);
  const timeline = page.getByRole("region", { name: "Migration timeline" });
  await expect(timeline.getByText("flight-3")).toBeVisible();
  // geometry: no wave on the headquarters lane overlaps the flight-3 band on that lane
  const band = await timeline.locator('[title^="flight-3"]').first().boundingBox();
  const waves = timeline.getByRole("button", { name: /Headquarters/ });
  expect(await waves.count()).toBeGreaterThan(3);
  for (const box of await Promise.all((await waves.all()).map((w) => w.boundingBox()))) {
    const overlaps = box!.x < band!.x + band!.width && band!.x < box!.x + box!.width;
    expect(overlaps, "a headquarters wave sits inside the flight-3 freeze").toBe(false);
  }
});

test("a wave is cut over and every VM gets an outcome", async ({ page }, info) => {
  test.skip(info.project.name === "phone", "the cutover is run once, on desktop");
  await page.goto("/#plan");
  await page.getByRole("button", { name: /^Wave 3,/ }).click();
  const panel = page.getByRole("region", { name: "Wave 3" });
  const vms = Number((await panel.getByRole("button", { name: /Cut over \d+ VMs/ }).textContent())!.match(/\d+/)![0]);
  await panel.getByRole("button", { name: /Cut over/ }).click();
  await expect(panel.getByText(/Moved|Rolled back|Not started/)).toHaveCount(vms);
  await expect(page.getByRole("button", { name: /^Wave 3,/ })).toBeVisible();
});

test("blocked VMs explain themselves with a source", async ({ page }) => {
  await page.goto("/#plan");
  await page.getByRole("button", { name: "See the blocked VMs and what to do" }).click();
  await expect(page.getByRole("radio", { name: "Blocked" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "hq-plm-db-02" }).click();
  const drawer = page.getByRole("dialog", { name: "hq-plm-db-02" });
  await expect(drawer.getByText("Raw device mapping", { exact: true })).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Source" }).first()).toHaveAttribute("href", /^https:\/\//);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

test("capacity keeps every cluster able to lose a node, and migrated VMs show no drift", async ({ page }) => {
  await page.goto("/#capacity");
  for (const c of ["pve-hq", "pve-factory", "pve-gpu"]) await expect(page.getByRole("heading", { name: new RegExp(c) })).toBeVisible();
  await expect(page.getByText(/can lose its largest node/).first()).toBeVisible();
  await page.getByRole("button", { name: "Drift" }).click();
  await expect(page.getByText("No drift")).toBeVisible();
});

test("no horizontal page scroll; the timeline scrolls inside its frame", async ({ page }) => {
  await page.goto("/#plan");
  await expect(page.getByRole("region", { name: "Migration timeline" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
