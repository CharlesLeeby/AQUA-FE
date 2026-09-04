# A08 read-only NO-GO handoff

Date: 2026-08-14  
Classification: **NON-AUTHORIZING · NON-EXECUTABLE · INFORMATIONAL NO-GO**

> **NON-AUTHORIZING READ-ONLY NOTE; NO EXPERIMENT STARTED; DOES NOT
> SUPERSEDE, RESERVE, RELEASE, ADOPT, OR AUTHORIZE ANY QUEUE SLOT, REVISION,
> EXPORT, REPLAY, OR EVALUATION.** It has no machine schema, self-hash, seal,
> lock, freeze, or preregistration semantics.

## Decision

Do not start an A08 matched-birth experiment under the current XFeat-birth
revision or under an alias of the existing P07 namespace.

The closest already-materialized candidate is the P07 window
`aqualoc_archaeology:A08:0002`, raw frames `[1800,2700)` / `90–135 s`, labeled
`normal / STRICT_NORMAL`. Its every-second-image frontend schedule contains
450 feature messages. It therefore cannot inherit the A02 `formal900`
contract. The observed schedule has 450 feature messages; no future contract
is implied.

## Blocking facts

1. **The current learned-birth revision is stopped.** The XFeat-birth
   preregistration requires an A07 prefix failure to stop before full export,
   VINS, and G0. The frozen A07 prefix failed five physical gates. The later
   comparison note explicitly closes broad expansion of this XFeat-birth
   revision. Threshold relaxation or a rescue retry is not authorized.
2. **The completed A02 result is one-window evidence.** Its formal POST marks
   `cross_window_generalization=false`; the published report labels the result
   as post-result exploratory evidence for one frozen A02 window. It does not
   authorize an A08 continuation.
3. **A08:0002 already belongs to P07.** Backend queue indices `157–168` are
   twelve pre-existing `PLANNED` rows: B1, P, B0, and M, each at slots
   `b01–b03`. The corresponding twelve registry rows are also `PLANNED`.
   Their twelve expected run directories and twelve expected attempt
   directories were all absent at this snapshot.
4. **P07 backend execution is not authorized.** The queue lock status is
   `FROZEN_BACKEND_QUEUE_AWAITING_EXECUTION_LOCK`, while
   `backend_replay_execution_lock_v1.json` is absent. The recorded backend
   formalization incident is explicitly non-authorizing and requires a
   separate additive adoption decision. The higher-level 2026-08-08 redirect
   also prohibits further backend governance construction for the frozen
   queue.
5. **A new matched-birth namespace would not cure these conflicts.** A scan
   found no A08 matched-birth/formal namespace, but absence is not permission
   to create one. A parallel namespace would bypass both the scientific STOP
   and the existing P07 allocation.

## Existing A08 evidence is not a new matched-birth endpoint

The P07 frontend exports for A08:0002 remain useful pre-existing evidence:

| Arm | Feature bag | Bytes | SHA-256 | Scope |
|---|---|---:|---|---|
| B1 | `logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a08_0002_b1_attempt01/features.bag` | 13,729,057 | `29c5740ae1351201e4c1c0d25736766a81ee48d982df650f772469c1b4ee42d5` | 450-frame P07 frontend export |
| P | `logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a08_0002_p_attempt01_klt_safe_fallback/features.bag` | 13,729,057 | `29c5740ae1351201e4c1c0d25736766a81ee48d982df650f772469c1b4ee42d5` | `ZERO_ACTION`; byte-identical to B1 |
| M | `logs/aqualoc_archaeo_vins/external_xfeat_every2_isj_p07_aqualoc_archaeology_a08_0002_m_attempt01/features.bag` | 12,777,965 | `99aad4e45307e51b646f8e665518964f9631cad72bc0089bc7f4638bd06fd04d` | distinct P07 XFeat frontend export |

Historical, non-queue B1/M replay evidence also exists. B1 produced a valid
single-arm endpoint (`38/45` matched grid poses, 37 RPE pairs, APE/RPE RMSE
`0.759644/0.106004 m`), while M failed initialization and produced a zero-byte
trajectory. Those values are `B1_ONLY_NOT_PAIRWISE_COMMON_SUPPORT`; they are
not a matched-birth comparison and do not authorize another A08 run. The
separate historical A08 `4500–4660` strict-G0 result has only 6 common poses
and 5 RPE pairs, with both APE and RPE invalid, so it is not a substitute.

The P07 raw cache `datasets/aqualoc/rosbags/archaeo08_1800_2700.bag` is absent
after its recorded reclamation. This note did not rematerialize it.

## Snapshot records

| Record | Bytes | SHA-256 |
|---|---:|---|
| `papers/2026-08-11--xfeat-lk-comparison-preregistration.md` | 13,264 | `ad571ca867ff29d144f9bf98ac8d8e8d9bb2e1ba1c5cfab33f7345df606662a5` |
| `papers/2026-08-10--literature-learned-frontend-comparison.md` | 33,987 | `830153b7a431c8051b661c077973c34f0a851996fb3db09ab441b03390404fa3` |
| `papers/2026-08-08--codex-STOP-and-redirect.md` | 4,381 | `4c11f338ad99fa1c3d4e89a2f3953d8e4d701b5bc53bddb89b7065782e891dae` |
| `papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v3.json` | 5,970 | `6f2e5c3c5cbf33ce4d3a431a4e609ef8e2940b09e32cbef57cbd888c1e4ae5af` |
| `papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv` | 471,028 | `2f6c71393e0b88de04ea750b99e7cb6c88e08e0906e1f55a2401b8ccdd554e11` |
| `papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json` | 968,437 | `479ea50333a70d6682c0afcc9cabc1c7a0c97404c817b4e19643fdc69f78580f` |
| `papers/ieee_sensors_journal_experiments/p07/backend_formalization_incident_v1.json` | 17,771 | `d282d51ca299a4fda18b8553b8ccf75cb5a47848a14146b410e1ea54ba97435c` |
| `papers/ieee_sensors_journal_experiments/run_registry.csv` | 456,776 | `aed0a758efb4e02d8484d8ba22bbb7a58cfb25f598c77222d5ad3a2e66fd5381` |
| `papers/p07_noharm_byte_identity.csv` | 40,803 | `8e082529076fb242aa10ddc1c96d0f072382e47c745f03b97b39be3b19d32524` |
| `papers/b1_vs_m_results.csv` | 29,801 | `61ac31343ab7ac0bb278c8a4a4feb98d3d7e2367e8cc207da77d3eeacdee5c3e` |
| `papers/e3_g0_common_support/a08_4500_4660/common_support_summary.json` | 4,846 | `47a275b027478e3f2341e5920a9750832d9c824a98dd994ab8e661b01a7c74bf` |

The three P07 frontend audits for queues 40/41/42 have SHA-256
`b1e579144f8db00432e79c0c07d17d21c9f0e0a9d51957094561d2e4d3d58165`,
`7709ca0bd889edaba2269a97a865728bfe5e40352872efa8b65610da89676507`,
and `81b65d2c1975a5cc141382e8b6f0db3b058f478d16fb63cf0aed3f4a66abb13b`.

## No unlock semantics

This note defines no unlock condition or future execution path. Only a later
explicit user instruction that separately and expressly supersedes the
2026-08-08 redirect could cause a new scope to be assessed; this note neither
authorizes that assessment nor releases, retires, or consumes any P07
allocation, and the A07 STOP remains historical.

## Claim boundary

This note records why no A08 matched-birth experiment was started. It reports
no new APE/RPE, method ranking, cross-window generalization, confirmatory
result, or scientific adoption. It does not alter any existing A08 replay or
trajectory evidence, and it does not consume a P07 backend allocation.
