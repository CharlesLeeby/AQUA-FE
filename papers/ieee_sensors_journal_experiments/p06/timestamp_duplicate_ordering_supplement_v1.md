# P06 duplicate-timestamp ordering supplement v1

Date: 2026-08-04
Protocol parent: `isj-window-selection-v2`
Status: `FROZEN_BEFORE_FINAL_SELECTION`

AFRL compressed-image streams contain a small number of consecutive frames
with identical header timestamps. The 100-frame legacy/direct equivalence pair
contains the same duplicates, so this is a source-data property rather than a
direct-adapter change.

For P06 screening and 45 s window construction:

1. rows are ordered by `(timestamp, frame_index, original_row_position)`;
2. `frame_index` remains unique, contiguous, and strictly increasing within
   the emitted stream;
3. identical timestamps are allowed and retain all corresponding image frames;
4. elapsed time is computed from `timestamp - minimum_timestamp`, so duplicate
   timestamps do not add artificial duration or move a row to another window;
5. non-finite or decreasing timestamps, duplicate frame indices, or a frame
   index gap remain fail-closed contract violations;
6. window score, thresholds, history exclusion, sequence cap, quota, and global
   tie-break are unchanged.

The stable secondary keys remove an implementation ambiguity in Python tuple
sorting. They do not inspect or order by any KLT score, texture stratum,
learned output, proposed-arm output, VINS result, APE, or RPE.
