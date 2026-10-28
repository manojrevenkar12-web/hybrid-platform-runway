# Runbook: a migration wave

**Before the day** (T-3 working days)
1. Merge request with `runway plan` and `runway generate` output reviewed by the app owners in the wave.
2. People steps from the plan done: snapshots consolidated, BitLocker keys escrowed and protection
   suspended for vTPM VMs, VirtIO drivers staged on Windows.
3. `ansible-playbook site.yml -l wave -e guest_cutover_phase=pre` on the wave's Linux guests.
4. `runway freeze check --site <site>`: the window is not in a freeze.

**In the window**
1. Announce start in the change channel.
2. Run the wave (console, or `POST /api/waves/<n>/run`). Watch outcomes; rolled-back VMs are
   running on vSphere again and need no action tonight.
3. `ansible-playbook site.yml -l wave -e guest_cutover_phase=post` on the VMs that moved.
4. Application smoke tests by the owners; drift page shows no drift.
5. Leave the source VMs powered off for 14 days; delete them only after the owner signs off.

**If something goes wrong**
- A VM marked `needs_person`: it is running nowhere. Start the source in vCenter first, then
  investigate. Never start both.
- More than three rollbacks in a wave: stop the wave, keep the window's reserve for rolling back.
