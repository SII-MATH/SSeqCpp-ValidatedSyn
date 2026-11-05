# Implemented sufficient-condition rules

The mathematical source is `docs/ss-program-claims/SS-claims.tex` in
Kervaire126Main (the statements are also in its Blueprint and
`KIP126/ProofTools/SyntheticCoverage`). The rules below are conditional on the
same fixed geometric triangles, compatible completed Adams realizations,
finite lambda-quotient comparisons, E2 labels, products and maps. Those
identifications remain initial mathematical premises; a C++ pass is not
a proof of their realization or a Lean certificate.

The executable does not use the historical coverage classification, event
IDs, old recorded outputs or the 201 acceptance targets to make deductions.
Each candidate is obtained by finite linear algebra in the current state.

Let the triangle's E2 maps be F:X->Y, G:Y->Z, H:Z->X. Their filtration
increments are nonnegative and sum to one; their internal-degree increments
sum to zero. All statements below use the fixed normalized triangle.
`Z_<q` means continuation through the differentials strictly below q;
`B_<q` means actual boundaries strictly before q. A value 9000 is a
permanence tag and is never included as an early boundary.

## Ordinary source and finite bottom lift

Sources: `prop:two-layer-differential`, `prop:page-differential`,
`prop:selective-differential`.

Given d_r(x)=u, solve the whole affine system

    H z = u modulo B_<r(X),   d_K z = G v modulo B_<K(Z).

The variable z ranges over a known differential graph, and v ranges over
an upper bound P on all permanent representatives in its complete E2 degree.
Check F_r(x)=y, F_r(u)=0, y in Z_<r, all intermediate inclusions

    Z_<K-j+1(X) subset B_<j+2(X) + H Z_<K-j+1(Z)

or the corresponding full inverse-image restriction by F and P_j, and
the whole terminal condition `ker(G|P) subset B_<D(Y)`, where D=r+K-1.
Only then conclude d_D(y)=v. The output representative is retained even
when its page class is zero.

## Source finite lift

Source: `prop:source-finite-differential`.

For F x=0, solve H z1=x and d_K1(z1)=G y. Require r>K1>=2,
the complete top intermediate inclusions, and the *whole* F-image at
the correction degree to lie in Z_<D+1(Y). For K2=1 use v=F u;
otherwise solve H z2=u and d_K2(z2)=G v with all bottom intermediate
conditions and the whole terminal kernel condition. D=r+K2-K1.

## Early d2 corrections

Sources: `prop:early-boundary-differential`,
`prop:source-early-boundary-differential`.

The target correction solves simultaneously

    d2(c)=F u,   G c=z,   d_L(z)=G v modulo B_<L(Z).

The full H-image at the specified degree must lie in B_<3(X).
Check the intermediate conditions of length L-1 and the terminal
kernel condition before concluding d_(r+L-2)(F x)=v.

The source correction instead starts with d2(c)=F x, requires r>=L>=3,
the whole H-image condition, the complete source intermediate conditions
and the whole correction image in Z_<D+1(Y). Its output is
d_D(y)=F u, D=r-L+2. These two propositions are checked separately.

## Independently known output-source survival

Source: `prop:known-source-survival`.

If y already belongs to Z_<D in the state preceding the candidate,
the intermediate candidate bounds may be intersected with a proven
upper bound on B_<r-K1+1+j(Y). This upper bound scans *all* possible
earlier source degrees and their complete differential domains. If
any domain is incomplete it returns the full target E2 space. Merely
collecting known boundary rows is not an upper bound.

## Conservative state interpretation and remaining scope

- Missing degrees beyond the supplied E2/map ranges cause rejection.
- Exact d2 and d3-quotient calculations require all relevant columns.
  Unknown columns enlarge upper bounds; they are never silently set to zero.
- Every kernel, inverse image and inclusion uses complete subspaces,
  including linear combinations of basis vectors.
- Genuine current boundary rows and independently known cycle spaces
  supply lower bounds. Permanence tags supply no early boundaries.
- Candidates are read before committing any output, including during
  a contradiction trial. A target cannot justify its own premises.
- The first implementation searches finite lift lengths 2..12. Other
  sufficient-condition families (including the general higher-early and
  longer recursive-relation criteria) are not silently replaced with an
  old heuristic. They must be implemented if the 201 targets require them.

The current native tests exercise complete kernels, affine consistency,
the d3 kernel modulo the full d2 image, unknown/range rejection, the 9000
boundary cutoff, and both disabled synthetic entry routes. They do not
constitute a full independent mathematical audit of this implementation.

## Cache boundaries

Fixed E2 map columns are cached per Category (at most 65536 columns).
These maps depend only on the fixed E2 bases, relations and map data, not
on SS deductions or trial assumptions. Their linear extension is compared
against the direct native evaluator on real basis vectors and sums.

Staircase rank, d2, the d3 quotient kernel, cycle/boundary spaces and
differential graphs are memoized only inside one read-only State frame.
The frame ends before a candidate conclusion is committed. A later call,
including one after AddNode/PopNode, always builds a new frame. Thus trial
knowledge cannot survive rollback through these caches. Gaussian basis
factorizations are reused for multiple right-hand sides without changing
their solution or missing-data checks.

`SS_VALIDATED_CACHE=off` selects the uncached reference path.
`SS_VALIDATED_CACHE_STATS=1` prints counts and the time spent in rule frames
once the Category is destroyed. This measures the rule layer; it is not
an estimate of the speedup of the entire ordinary search.
