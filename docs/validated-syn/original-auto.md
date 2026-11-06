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

Unlike the earlier prefix-comparison experiment, the initial run enables
`flags=syn,dxy` from the start of the native auto command, after the
unchanged reset. The default controller has no row-count threshold and does not schedule a
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

The completed auto-only phases of `.runs/cw49-native-auto-20261106` were:

| Command | Original switches | Rounds to fixed point | Checked targets | Native log boundary | Binary prefix / C++ source |
| --- | --- | ---: | ---: | ---: | --- |
| `auto-001` | `syn,dxy` | 8 | 197/201 | 2,481,321 | `04c7…` / `d77d420` |
| `auto-002` | `syn,dxy,zero` | 6 | 200/201 | 2,521,033 | `3236…` / `2bc93b0` |

The second command used the executable-adoption controller at `f27e542`.
Its final physical log contained 2,521,043 rows: ten additional acceptance
trial rows were beyond the native checkpoint boundary. T010 remained
missing; errors and forbidden outputs were zero. These auto-only phases
did not reach 201/201. A separate read-only rescan of already-known inputs
returned 622 distinct new program candidates on checkpoint 17, round 4,
log boundary 2,521,011. Those diagnostic candidates were not inserted into
the run; this count does not describe the final checkpoint 32.

An explicit, one-time continuation may call the upstream standalone
`deduce synthetic` command before the next `deduce auto` command:

```sh
python validation/auto_run.py EXISTING_RUN_DIRECTORY \
  --seed ORIGINAL_E2_MAP_SEED --binary SAME_FIXED_BINARY \
  --resume --synthetic-before-auto --flags syn,dxy,zero \
  --native-rounds 100 --check-seconds 600 --checkpoint-seconds 300
```

This option requires a complete checkpoint whose native command has
successfully exited, with no live controller or child. It records one stable
intent in `status.json`, for example `synthetic-003` followed by `auto-003`,
and restores the preceding state and log boundary. The standalone command
uses its original fixed flags and internally repeats its all-object scan
until no change remains. SynCs and SynCsIn remain disabled. Its successful
save and process exit are required before auto starts with the requested
original switches. This schedule does not enable `pullback`, alter the auto
loop or finite rules, or add mathematical inputs.

Resume an interrupted continuation with the same pinned executable,
switches and round limit. The intent survives independently of the
diagnostic `command` field, which predecessor restoration can overwrite.
Partial checkpoints resume their own command. A complete checkpoint
published before ordinary tables finished saving is resumed to finish
saving. After synthetic has successfully exited, auto startup may repeat
that complete-checkpoint save without rerunning the scan. After auto exits,
verification and notification retries do not repeat synthetic. Repeating
the option is an idempotent retry of the same one-time request; it does not
request a second scan. A positive checkpoint interval is required, and
binary or search-option changes are rejected while the continuation is
active. The existing C++ binary hash/source pin is preserved; the controller
revision is recorded separately as `controller_source_commit`.

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
When an explicit synthetic continuation was used, the successful
notification names that schedule rather than describing an auto-only run.

The native monitor regression deliberately removes all saved S0 staircase
rows after a checkpoint was published. It verifies 201 distinct fixture
equations from the checkpoint and checks that neither the producer log nor
the deliberately stale saved table was changed:

```sh
python validation/test_auto_monitor.py ORIGINAL_E2_MAP_SEED
```
