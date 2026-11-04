# Validated Syn replacement

Fork: https://github.com/WayneLin92/SSeqCpp. The CW49 baseline is upstream commit f3407e365063c7e0beb1edc677540519a6c1b336; the published source also fixes DeduceTrivialCofDiffs to iterate over cofseqs_, not rings_.

The acceptance collection is 201 inputs to the selected Moore proof, exported from the publication checkout at 2532b3c8. It contains 194 finite SS coordinate inputs, two actual Moore-route equations, three direct d2 inputs and two staircase inputs. The earlier 163-row list counted historical locators with duplicates. 132 mathematical claims overlap; the remaining 69 belong to the pre-synthetic ordinary background under its retained premises. This historical observation does not license importing those results in a fresh rerun.

The mathematical rule sources are Kervaire126Main/docs/ss-program-claims/SS-claims.tex and the general sufficient-condition declarations in KIP126/ProofTools/SyntheticCoverage. Each implemented rule must identify its proposition and test the complete hypotheses in the current state. The existing coverage of 572/573 Syn records is a classification of conditional mathematical routes, not permission to accept a record by ID.

Old synthetic producers are disabled. New inference does not read the acceptance file or historical logs. SynCs/SynCsIn outputs are forbidden. Eight negative targets must have fresh exclusion witnesses. The fixed E2/model/map identifications and ordinary input assumptions remain explicit; passing this program is not a completed Lean certificate.
