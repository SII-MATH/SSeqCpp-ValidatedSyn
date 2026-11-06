# Fresh run with the original auto and switch mechanism

This experiment keeps the upstream `deduce auto` traversal and its ordinary
SS/cofiber search. The original `syn` switch calls `SetCwDiffSynthetic` at
its existing automatic trigger; that entry now checks the finite
sufficient-condition rules described in [rules.md](rules.md). The old
recursive `GetSynImage`, SynCs and SynCsIn producers remain disabled.
Ordinary cofiber deduction remains enabled. The implemented conditions
correspond to proved conditional declarations in
`KIP126/ProofTools/SyntheticCoverage`; the C++/fixed-model realization is
not itself a Lean certificate.

Unlike the earlier prefix-comparison experiment, this run enables
`flags=syn,dxy` from the start of the native auto command, after the
unchanged reset. It has no row-count threshold and does not schedule a
separate synthetic sweep between auto iterations. `dxy` is the original
optional uncertain-differential Leibniz search. No rule reads the target
file or historical computation output. The same 201 fixed targets are used
only by the independent checker.

Upstream auto reads `syn` before its loop; it never enables that switch
after ordinary deductions stop. Once enabled, the existing inline trigger
requires depth at most one, an input page at most six, and nonempty source
and known nonempty target. A late first `Syn` log records the first emitted
conclusion, not the time the switch was enabled. The old log alone does not
recover its original launch options.

`num=100` is an upper bound for the upstream native loop. Its existing
no-change test may stop it earlier; the final status records whether it
actually reached that fixed point. A fixed point that misses targets is
reported as incomplete, rather than replacing the fixed target collection.

```sh
python validation/auto_run.py NEW_RUN_DIRECTORY \
  --seed ORIGINAL_E2_MAP_SEED --binary FIXED_BINARY \
  --flags syn,dxy --native-rounds 100 \
  --check-seconds 600 --checkpoint-seconds 300
```

Use `--resume` to continue this run's own saved state. Search switches can
change only after a native command has completed. To adopt a replacement
executable at that boundary, also pass `--adopt-binary`; a missing or
unfinished checkpoint, a live controller/native child, or an unacknowledged
binary change is rejected. The status retains the previous executable hash
and source commit, pins the new executable, and starts a new native command
after restoring the preceding saved state and log boundary. This does not
import a historical computation or change the fixed acceptance targets.

The controller preserves the mathematical SQLite log and the native
recovery state. It drains terminal output without keeping a redundant full
transcript. The first available checkpoint is checked after about 30
seconds, then every ten minutes. `progress.json` is the current result;
`progress.tsv` keeps compact time/count observations. Counts distinguish
current committed logs from the checked checkpoint's log boundary.

A check uses SQLite backup to copy one consistent recovery database into a
temporary private directory. The verifier's `checkpoint=1` option reads
that copy's SS/cofiber layers instead of the ordinary saved tables, which
may be stale while auto is running. E2 basis/product/map inputs are shared
read-only. Its log and negative-target trials are private; no acceptance
result or target-directed exclusion is written into the inference run.
The monitor also checks the producer's real log for forbidden outputs up
to the checkpoint boundary. Temporary check copies are removed afterward.
After native auto returns, the ordinary saved output receives the final
independent verification.

Fixed-map and read-frame caches remain enabled. The upstream native auto
command is single-threaded; `T/id_thread` partitions work but does not
create workers or merge their mathematical states. This experiment keeps
the native execution single-threaded rather than adding a new parallel
inference/merge mechanism. The log-reading thread and isolated checker are
monitoring, not parallel inference.

`--notify-user OPEN_ID` sends the final successful result to that user with
`lark-cli im +messages-send --as bot`. It uses an idempotency key and saves
the successful receipt in `notification.json`. A notification failure
leaves the mathematical result intact and can be retried with `--resume`.
No message is sent for an incomplete target collection.

The native monitor regression deliberately removes all saved S0 staircase
rows after a checkpoint was published. It verifies 201 distinct fixture
equations from the checkpoint and checks that neither the producer log nor
the deliberately stale saved table was changed:

```sh
python validation/test_auto_monitor.py ORIGINAL_E2_MAP_SEED
```
