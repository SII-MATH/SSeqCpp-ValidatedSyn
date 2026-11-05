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
and committed SQLite row counts are separate fields in `status.json`;
SQLite counts are updated after each completed command. Full terminal
transcripts are not retained; failures keep the final 80 lines.

```sh
python validation/prepare.py RAW_E2_DIRECTORY NEW_RUN_DIRECTORY
SS_VALIDATED_CACHE_STATS=1 python validation/run.py NEW_RUN_DIRECTORY \
  --binary FIXED_BINARY --official-log OFFICIAL_PROOFS_DB
```

The fixed-map and read-only-frame caches remain enabled. The old handoff
script is retained for the earlier run's provenance; mixed-rule checkpoints
cannot enter this new controller's staged fresh-run path.
