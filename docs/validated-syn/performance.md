# Current performance findings

The first full run used one native thread. At the resource check it had
used approximately one CPU continuously and about 1.9 GiB resident memory,
with no swap. The shared execution environment exposed 128 logical CPUs
but had a CPU quota equivalent to 54 cores and a memory limit of 300 GiB.
Total cgroup memory use was approximately 222 GiB at that measurement.
Those limits are shared with other jobs; they are not all free allocations
for this project. The CPU/elapsed-time ratio points to computation rather
than memory or I/O waiting as the current bottleneck.

The original CacheNullDiffs/CacheNullCofDiffs candidate caching remains
enabled. The initial implementation omitted memoization in the newly
added sufficient-condition checks. The added caches are described in
rules.md. They do not bypass any condition or change the 201 targets.

Tests compare cached fixed maps to direct native evaluation on 17 actual
map/degree combinations, exercise an exact d3 kernel modulo d2 boundaries,
and ensure temporary trial results disappear after rollback. In the small
repeated-check fixture, the uncached and cached checks took about 0.00169 s
and 0.000419 s respectively (roughly 4x). This very small fixture is not a
benchmark of the whole SS search and does not justify a 4x overall claim.

The old native process cannot be updated in place. validation/handoff.py
adopts its output and leaves that C++ process running unchanged. It retires
the old Python controller only after the native command exits normally and
saves its own run state. The next command uses a separate cache-enabled
executable; status.json records both binary versions. Isolated mock-process
tests check normal completion, recovery after a failed handoff and refusal
to control an unrelated job. This reuses this fresh run's own progress,
not a historical proof log or external computed starting state.

The native T/id_thread parameters provide a possible route to process-level
parallel search. Each worker would need private mutable state and a checked
merge of its newly derived facts. More RAM alone does not parallelize the
current search. Such a multi-worker production run is not yet enabled by
this cache change, and its end-to-end speedup has not been measured.
