# Runbook: an emergency change during a launch freeze

1. The change owner writes down what breaks if the change waits until the freeze ends.
2. The head of IT operations (or deputy, as listed in the on-call schedule) approves in writing.
3. Set `EMERGENCY_CHANGE_APPROVED_BY=<name>` on the pipeline run (protected variable). The freeze
   gate passes and records the name in the job log.
4. Argo CD's deny window still holds (manual syncs are denied too). An Argo CD admin applies the
   AppProject without that window, syncs the one application, and re-applies the committed project
   at once; the change ticket records both times.
5. After the launch, review the change in the next platform retro.
