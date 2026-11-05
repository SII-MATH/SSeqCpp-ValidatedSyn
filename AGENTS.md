# Validated Syn replacement

This project is the user-authorized fork of WayneLin92/SSeqCpp. Preserve upstream history and license.

- The fixed acceptance target is exactly validation/targets.json (201 mathematical claims). Never use it as an inference input or change it to obtain a pass.
- Replace old synthetic deductions with sufficient-condition rules, checking the full spaces, finite page bounds, fixed objects, maps and all premises before mutation. Never use historical record IDs or a whitelist as a proof rule.
- SynCs and SynCsIn producers are disabled at every entry point. The old GetSynImage implementation must never be used to establish a conclusion.
- Fresh runs start from E2 bases/products/maps and explicit initial d2/manual inputs. Never load historical proofs.db/log, the 480731-row prefix, or a computed SS/cofiber state.
- The starting-state restriction concerns external historical results. This fresh run may resume either a normally completed command or its own periodic recovery checkpoint, as authorized by the user. Periodic checkpoints must be taken outside trial branches, preserve traversal position and exclusion-cache state, and restore a matching log prefix; retain source/binary provenance. Fixed-model caches may persist, but state-dependent memoization must not survive a mutation or trial rollback.
- Negative targets require a fresh contradiction/exclusion witness. Absence of the corresponding positive equation is not a refutation.
- True boundaries use strict page bounds. Permanent marker 9000 is never an early boundary. Missing/out-of-range data causes rejection, not zero.
- Keep the original study repositories, sources and databases read only. Use independent writable run directories.
- Emit a small result summary and necessary individual rule witnesses; do not duplicate full historical audit snapshots.
- Do not report a full validated rerun until all 201 targets pass and forbidden-producer checks pass. Distinguish mathematical premises, program regression and Lean certification.
