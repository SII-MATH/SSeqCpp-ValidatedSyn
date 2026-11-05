# Staged fresh rerun

The failed mixed-rule run is preserved at `.runs/cw49-initial`. Its first
ordinary command enabled `validated_syn,zero,pullback` immediately, so its
6,484,854 log rows do not reproduce the published ordinary prefix. The
subsequent standalone synthetic scan terminated with SIGSEGV before the
201-target check.

The standalone scanner retained a reference to a mutable staircase while
rule conclusions could rewrite or relocate its rows. It now copies each
degree before iterating its known differential rows, keeping both the
iteration and rule arguments alive across mutations. The three existing
manual reset inputs now also produce explicit `M` records, as in the
published log; the mathematical initial inputs have not changed.

The old version was reproduced under AddressSanitizer. It reported
`heap-use-after-free` in `Category::DeduceDiffBySynthetic`, at the loop's
read of `sc.levels.size()` (old `deduce.cpp:260`). The freeing allocation
was `std::vector<Staircase>::_M_default_append`: a propagated conclusion
resized the containing staircase array. This confirms the dangling
reference rather than merely inferring it from the original SIGSEGV.

A full standalone scan on a private copy of this run's saved checkpoint
completed with exit code 0 after this change (258.69 seconds). This is a
crash regression, not the required fresh staged rerun or a 201-target pass.
The native C2 rule tests and seven comparison/controller tests also pass.

`validation/run.py` now performs these stages:

1. Reset from raw E2/product/map/d2 files prepared by `prepare.py`.
2. Run the upstream ordinary SS/cofiber search, with no synthetic,
   zero-expansion or pullback flags. Upstream `auto num=10` stops earlier
   when a complete iteration changes nothing.
3. Compare the retained ordinary mathematical event stream against the
   published log, including proof descriptions. The reference omits its
   first 5431 records; event alignment is explicit. IDs, command metadata
   and anonymous input hints are not mathematical deductions. The reference
   has 2,406,018 non-anonymous events before its first Syn, record 2411455.
   Any discrepancy or early synthetic output stops the controller before
   the new rules are enabled. The small `ordinary-comparison.json` records
   the count and first discrepancy, if any.
4. Enable the new sufficient-condition rules, interleave further ordinary
   propagation, and run the immutable 201-target verifier. Old Syn,
   SynCs and SynCsIn outputs remain forbidden. Negative verifier trials do
   not publish exclusions that a later inference round could consume.

The reference database is opened read-only by the comparison process only.
It is never passed to the native inference engine. Terminal line counts
and committed SQLite row counts are separate fields in `status.json`.
The native engine publishes real committed counts every 30 seconds at the
next outer degree boundary. WAL mode permits ordinary read-only queries
during deduction. Full terminal
transcripts are not retained; failures keep the final 80 lines.

```sh
python validation/prepare.py RAW_E2_DIRECTORY NEW_RUN_DIRECTORY
SS_VALIDATED_CACHE_STATS=1 python validation/run.py NEW_RUN_DIRECTORY \
  --binary FIXED_BINARY --official-log OFFICIAL_PROOFS_DB
```

The fixed-map and read-only-frame caches remain enabled. The old handoff
script is retained for the earlier run's provenance; mixed-rule checkpoints
cannot enter this new controller's staged fresh-run path.

## Periodic recovery

The default `checkpoint_seconds=300` also saves at iteration boundaries.
The interval is a safe-point target: a single unusually long degree or
initialization step can delay the next save. The checkpoint is one reusable
`recovery.sqlite3`, containing both SS layers, cofiber layers, synchronization
flags, array shapes, scan degrees, exclusion caches, iteration start log ID,
accumulated change state and the last completed scan step. It contains no
external historical proof inputs and does not replace the fixed E2/maps.

Only the outer state is saved. Completed log transactions are committed
first; the state and its log boundary are then replaced in one SQLite
transaction. An exception rolls back that transaction explicitly. If a
process dies before the new state is committed, the previous checkpoint
remains usable. Recovery discards any log/exclusion tail after that
checkpoint and skips already completed scan operations. Preserving the
in-memory exclusion cache, rather than eagerly loading all recorded
exclusions, is necessary to preserve the original proof-search order.

The checkpoint is marked complete before updating the ordinary SS database
files. Recovery can load its complete layers directly and rewrite those
tables if a process dies partway through that final multi-file save.
Fixed E2 map caches stay warm during periodic saves; they may be recomputed
on restart. State-dependent rule memoization still ends with its read frame.

Native regression tests forcibly kill a private C2-triangle calculation at
a degree checkpoint, a later iteration boundary, the final save boundary,
and during the standalone synthetic scan. Every resumed run has exactly
the same ordered mathematical events (including proof text) and final
SS/cofiber rows as the uninterrupted pre-checkpoint binary `64bc97c`.
Separate native tests check exact layer/flag/cache serialization, log-tail
truncation, rollback after a failed checkpoint write, and rejection of trial
state saves, including a first checkpoint that was never published. Ten
controller/comparison tests cover the prefix gate, resuming after a normally
saved ordinary command, and resuming the first synthetic command after its
log has advanced beyond the already verified ordinary prefix.

```sh
python validation/test_checkpoints.py RAW_E2_DIRECTORY --reference PREVIOUS_FIXED_SS_BINARY
python -m unittest discover -s validation/tests -p test_prefix.py
```

```sh
python validation/run.py EXISTING_RUN_DIRECTORY --resume \
  --binary SAME_OR_APPROVED_UPDATED_BINARY --official-log OFFICIAL_PROOFS_DB
```

`status.json` distinguishes `saved_log_rows` from
`recovery.recoverable_log_rows`. Logs published since the latest state
checkpoint are visible, but are trimmed on recovery so that the proof log
and the restored mathematical state stay consistent. The immutable 201
targets are not inference inputs, including during a resumed calculation.

## Stronger ordinary searches after the verified prefix

The first staged calculation reached 198/201. Rounds 7--10 produced no
additional mathematical events with `post_flags=validated_syn`; repeating
that same configuration is therefore not an effective next step. The three
remaining requirements are survival through pages 16, 14 and 6, respectively.

`--post-flags pullback`, `--post-flags zero`, or `--post-flags dxy` can enable the original
program's stronger ordinary contradiction search after the prefix gate.
These options never change the initial ordinary calculation. The separate
synthetic scan still uses only the validated sufficient-condition rules;
SynCs and SynCsIn remain disabled. They are general searches over the full
configured range, not rules selected from the acceptance targets.

The historical record for the next missing step of T026 uses `XY`, the
ordinary Leibniz rule with an uncertain input differential. That search
is selected by `dxy`; its absence is a separate issue from the unimplemented
sufficient-condition families in the synthetic producer.

```sh
python validation/run.py EXISTING_RUN_DIRECTORY --resume --rounds 12 \
  --post-flags pullback --binary FIXED_BINARY --official-log OFFICIAL_PROOFS_DB
```

The existing ordinary prefix is rechecked, completed commands are skipped,
and only the new rounds are run. The configured post-prefix flags are saved
in `status.json` and reused on later resumes unless explicitly changed.

### Completed 201-target continuation

The staged fresh calculation passed **201/201**, with no verifier errors and
**zero** `Syn`, `SynCs` or `SynCsIn` outputs. The immutable target file has
SHA-256 `8c5af390415fc9250d0289bf6ca40a90d95177bf30c4e1d552c3914bbdef2299`.
The ordinary prefix still matches all **2,406,018** reference mathematical
events, including proof descriptions.

The initial ten post-prefix rounds with `post_flags=validated_syn` stopped
at 198/201. Repeating their unchanged configuration produced no new facts.
Enabling the original ordinary `dxy` search gave 200/201 after its first
round and 201/201 after its second round. The successful continuation used
only `post_flags=dxy`; the validated synthetic scan ran separately between
rounds. The completed run is `.runs/cw49-dxy-continuation-20261106`, whose
`status.json`, `ordinary-comparison.json` and `acceptance.json` contain the
local results and provenance.

This continuation started from the staged fresh run's own completed
`validated-011` state and its matching own proof-log boundary. The native
computation uses its own E2/maps and saved calculation state. Historical SS
states and historical inference records are never loaded. The historical
log is used only by the separate prefix comparison. The 201 predicates are
used only by the separate verifier, including its rollback-only negative
checks; they are not inference inputs.

The three previously missing survival conditions were recovered as follows:

| Target | Object and `(s,t)` | New ordinary steps | Required page |
| --- | --- | --- | --- |
| T026 | S0 `(3,130)` | `d_7[0]=0` by uncertain-differential Leibniz, followed by naturality and ordinary propagation | 14 |
| T049 | S0 `(8,130)` | `d_5[0]=0` | 6 |
| T010 | Cnu `(9,135)` | `d_5[1]=d_6[1]=d_7[1]=0`, followed by degree-gap propagation | 16 |

Thus the earlier shortfall was a search-configuration issue. After `dxy`
was enabled, another propagation round was also needed. The passing run
retains the same finite sufficient-condition implementation; it establishes
the requested 201-target computational acceptance, rather than completeness
of every certified synthetic theorem family.

The equivalent staged schedule is:

```sh
python validation/run.py NEW_RUN_DIRECTORY --rounds 10 \
  --binary FIXED_BINARY --official-log OFFICIAL_PROOFS_DB
python validation/run.py NEW_RUN_DIRECTORY --resume --rounds 12 \
  --post-flags dxy --binary FIXED_BINARY --official-log OFFICIAL_PROOFS_DB
```

An additional diagnostic examined a different historical route to T010.
At `CW_2_A_eta (s,t)=(11,145)`, assuming `d_3[6]=0` forces next-page
choices. Both `d_4[6]=0` and `d_4[6]=[0]` contradict known information
(historical records 2528669--2528671). A rollback-only native probe on this
run's saved state returned `ordinary_contradiction=0` and
`expanded_zero_contradiction=1`, confirming that the original `zero` search
can exclude that assumption. This probe inserted no production conclusion
or exclusion. The completed 201/201 continuation used `dxy` without `zero`
or `pullback`; those alternative diagnostic calculations were stopped once
the successful verification was available, retaining their recovery states.
