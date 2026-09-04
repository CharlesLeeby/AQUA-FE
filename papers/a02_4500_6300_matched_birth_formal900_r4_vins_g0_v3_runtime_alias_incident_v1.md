# A02 formal900 r4 G0 v2 runtime-alias incident adoption

## Scope

This record adopts the consumed v2 evaluation namespace after both evaluator
roles returned RC0 and wrote their staged artifacts, but the v2 governor
stopped before publication because its expected-versus-actual runtime module
comparison treated canonical aliases under `/lib` and `/usr/lib` as different
scientific files.

This is an additive infrastructure incident record. It does not publish the
staged v2 result, does not claim a v2 PASS, and does not authorize mutation,
completion, deletion, or retry inside any v1 or v2 namespace.

## Retained v2 authority

- Governor: `scripts/govern_matched_birth_r4_vins_g0_v2.py`, SHA-256
  `8c738362a7aee9adacd22c182a330a16df7c08ce253b36b2643e6451718c0fb9`,
  296051 bytes.
- Prior incident adoption: SHA-256
  `2e3bb54156a99efb79aa59e6f2f8c85f4fbc07f46fc1c326073e1fd71c38f2df`,
  23926 bytes, self-hash
  `791ce7d3736570806d74128485f6f211e9e8f3859ca4b88c9b38f7235eb1050e`.
- Freeze: SHA-256
  `0bd647c70544776e128cf43184b49effc3d5d20b2c15a05729103a8b8378c2f8`,
  2357600 bytes, self-hash
  `4fff2f905802d0f5ee7642fb828c43e552e12e8c031e54ad418a5302d0250496`.
- Runtime-probe intent: SHA-256
  `21e6a9aa5ec10a5602277f92c5ce6b256b0c62b6b575cf51cb4a3a3f8fa9113f`,
  3626 bytes.
- Runtime-probe success closeout: SHA-256
  `fb3dee0a08b2968fb403de5da3999d1db2315a7056e60296316e26edc2c4ebbc`,
  858 bytes.
- Runtime-probe failure receipt is absent.
- Job hash:
  `48f29b21b4e9d31409a15fcf93458bc1309fb8a5b5d674c1d90d349f8ab862b2`.
- Publication intent: SHA-256
  `621100edd33c0f8980038b19660faa8810441175869851a6f59cd3a8f6fec5f1`,
  1751 bytes.
- The exact staging directory exists. The destination, publication closeout,
  and post seal are absent.
- The consumed v1 runtime-probe launch intent remains pinned at SHA-256
  `d433ce9e5be085efc8854d60b2e34279c9f8e5dc3953e400e89751b53fdcba0a`
  (3626 bytes, device 66312, inode 6074562, uid 1000, mode 0644, one link).
  Its `probe_launch_intent_hash` is
  `8db122e79ede30eeb3cdb30a3e01d999bd91b3e34979dbf0eaa650ee2692785f`;
  the builder validates both that self-hash and the exact launch semantics.
- The complete transitive v1 absence set remains empty: the v1 freeze,
  failure receipt, post seal, r1 destination, and its exact staging,
  publication-intent, and publication-closeout namespaces. Thus all seven
  old-v1 paths are held absent at the final publication edge.

The primary launch intent is pinned at
`d1b5d087962de8b909fd9f06c459f568daad2044eb405b9bd953ccac652dd195`
(9966 bytes), and the verification launch intent at
`5a5a54aa7b743d62bb95ababc88e11fcd03401ed7b3ed151b85587a2473782ae`
(10011 bytes). The primary runtime receipt is pinned at
`e714f919d86e82229cca9fa2dbea6698cea69cd8a3cbc26eebd954b5ef5d042e`
(2109886 bytes), and the verification runtime receipt at
`11256d1c808561d4fc4bd533f3706dad48451bf72f591e6479b988cf660e78c4`
(2109896 bytes). Both receipts state `evaluator_called=true`,
`evaluator_rc=0`, and `evaluator_error=null`.

The two runtime receipts are not byte-identical: they truthfully contain
different role and role-output identities. The three evaluator science files
are byte-identical across primary and verification:

- `common_support_summary.json`:
  `64f50d509045c6fb1b09ce350a4b4303400e914f5c60e76fec96a0f22efdb6c4`,
  3760 bytes.
- `common_support_metrics.csv`:
  `a0be6693826227d6a07935dc7413b4f3799419a9551a14f0552c9671916a702c`,
  996 bytes.
- `common_grid_audit.csv`:
  `88cc1664c651585f51728af66543c2a6a82772a70b3aceeca2460793ae23f2fc`,
  2802 bytes.

Those byte identities are retained forensic facts, not a PASS decision. The
v2 destination was never published and no v2 post seal exists.

## Mechanical diagnosis

The frozen expected receipt and each role receipt contain 490 persistent
module rows. Exactly 110 rows are already byte-tree equal and 380 rows differ
before typed comparison. Of those 380, 373 differ only through persistent
realpath aliases and seven differ only through the expected probe-versus-role
sealed `/proc/self/fd/*` locators. Replacing persistent paths only after live
realpath/device/inode cross-checking, and replacing sealed locators only by
their existing sealed-source role, makes all 490 required rows exact for both
roles. There are no missing, mismatching, or extra module rows. A hardlink is
not treated as a realpath alias.

The same mechanical comparison covers the other two named closure views, even
though their 331 non-optional mapped-file records, 1697 non-optional map rows,
five sealed map rows, and 329 non-optional native ELF records are already exact
between probe and each role. Typed normalization therefore admits zero further
maps/native differences. Primary and verification have exact-equal module,
maps, and native closure trees, and the successor bootstrap's role/output-only
semantic identity is equal across the two role receipts.

The first mismatching module, `Cryptodome`, illustrates the defect. Its
expected lexical file is
`/lib/python3/dist-packages/Cryptodome/__init__.py`; the role receipt uses
`/usr/lib/python3/dist-packages/Cryptodome/__init__.py`. They resolve to the
same file and retain device 66312, inode 1051682, size 182, and SHA-256
`20a3a80330f01736e2f67dd72da47b2d0d7df6abb06b537101ac009e57bd4e42`.

There is a second, separately typed runtime-closure difference. The probe
alone loaded `/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2`. Its complete file
identity has lexical and resolved paths equal to that path, `symlink=null`,
SHA-256
`14147fcfadccacb4ddf94738143a3fa999a065a303dda898da8ab057cfb483b4`,
size 132976, and full stat identity `(device=66312, inode=169139, mode=420,
link_count=1, uid=0, gid=0, mtime_ns=1581039179000000000,
ctime_ns=1740666764578004477)`. It appears once in the expected mapped-file
set, in exactly five expected map rows at offsets `00000000`, `00006000`,
`00017000`, `0001d000`, and `0001e000`, and once as a whole
`PERSISTENT_ELF` native closure record containing that same file identity.
The file record, all five rows, and the whole native record are absent from
both actual role receipts; a partial omission would not satisfy the rule.
This is a probe-only optional runtime leaf, not a general subset or
missing-library permission.

The repaired rules are narrow and independent:

- `PROBE_EXPECTED_ACTUAL_REALPATH_ALIAS_NORMALIZATION_ONLY_FOR_PERSISTENT_MODULES_PERSISTENT_PROC_MAPS_FILES_AND_ROWS_AND_NATIVE_LOADED_ELF_CLOSURE;SAME_FILE_IDENTITY_REQUIRED;ROLE_TO_ROLE_AND_ALL_SCIENTIFIC_SEMANTICS_UNCHANGED` normalizes ordinary absolute lexical aliases only in the three named runtime-closure views, and only when the resolved file identity remains exact.
- `EXACT_PROBE_ONLY_OPTIONAL_LIBTBBMALLOC_RECORD_ONLY;NO_GENERAL_EXPECTED_RUNTIME_SUBSET_RELAXATION` permits omission only of the exact pinned `libtbbmalloc.so.2` mapped file, its exact five map rows, and its exact `PERSISTENT_ELF` item.

Neither rule may relax lexical/resolved-path typing, symlink identity, hashes,
sizes, any of the eight stat leaves, module order, sealed-source role binding,
map-row content, native mapping kind, argv, environment, evaluator output
validation, or any scientific threshold. The machine builder regenerates the
comparison facts from the locked freeze and both locked runtime receipts and
requires exact equality with the incident tree before publication.

## Successor authorization

Exactly one fresh v3/r3 namespace may be used. Its governor must be pinned by
SHA-256 and byte count, expose the pure namespace schema
`aqua-fe-matched-birth-r4-vins-g0-v3-runtime-alias-incident-namespace-contract-v1`,
use job id `matched_birth_r4_vins_g0_v3`, and bind fresh v3 freeze, probe
intent/failure/success, post, and r3 publication namespaces.

The only authorized sequence is `write-freeze`, `check-start`, `run`,
`seal-post`, `check-post`. The successor remains post-result exploratory. It
may not claim pre-outcome blindness, statistical significance, cross-window
generalization, independent ground truth, or whole-SLAM superiority. It may
not rerun detector export or VINS, and it may not alter the scientific inputs,
evaluator argv/environment, metrics, thresholds, or decision rules.

The machine incident JSON is intentionally not created by preparing this
human record. Only the builder's separately guarded `write-once` action may
publish it through the retained two-phase no-replace carrier. The machine
record itself enumerates the exact 22-path absence closure; the inner guard
holds it continuously and the outer carrier rechecks the same list immediately
before its no-replace commit.
