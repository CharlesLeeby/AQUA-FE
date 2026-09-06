"""EXP-20260906-012: explicit published-ID continuation around frozen v2.

The archived exporter is loaded unchanged, with two narrowly scoped callbacks.
No external estimator or default exporter code is modified by this entrypoint.
"""
from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import numpy as np

from uw_frontend.tracking.track_state import TrackSet

V2_REF = "3c50b742d6e0c69796a69813e42823e9895ed684"
V2_SHA = "bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d"


def load_frozen_exporter():
    root = Path(__file__).resolve().parents[2]
    source = subprocess.check_output(
        ["git", "show", f"{V2_REF}:uw_frontend/ros/export_vins_features.py"], cwd=root)
    if hashlib.sha256(source).hexdigest() != V2_SHA:
        raise RuntimeError("Frozen v2 exporter identity mismatch")
    module = types.ModuleType("_aquafe_continuation_frozen_v2")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{V2_REF}:export_vins_features.py", "exec"), module.__dict__)
    return module


class PublishedLifecycle:
    """Keep admission reservation and final publication ledgers distinct."""

    def __init__(self, code, events=None, frames=None):
        self.code = code
        self.original_seed = code._apply_online_seed_sidecar_gate
        self.original_final = code._finalize_mirror_sidecar_export
        self.active = {}  # raw ID -> (public ID, first publication frame)
        self.closed = set()
        self.published = 0
        self.stage = TrackSet.empty()
        self.stage_frame = -1
        self.basic = {}
        self.previous_frame = -1
        self.events = events
        self.frames = frames

    def seed_gate(self, tracks, info, **kwargs):
        # Snapshot is after existing upstream tracking/geometry/source gates.
        # It is NOT a claim about private IDs absent from this stage.
        self.stage = tracks
        self.stage_frame = int(kwargs["frame_index"])
        self.basic = kwargs
        return self.original_seed(tracks, info, **kwargs)

    def event(self, frame, raw_id, public_id, event, reason, index=None):
        if self.events is None:
            return
        row = dict(selected_feature_index=frame, raw_id=raw_id, public_id=public_id,
                   event=event, reason=reason, cumulative_published=self.published,
                   source="Unknown", raw_age="Unknown", fb="Unknown", ncc="Unknown", quality="Unknown")
        if index is not None:
            row.update(source=self.stage.sources[index], raw_age=int(self.stage.ages[index]),
                       fb=float(self.stage.fb_errors[index]), ncc=float(self.stage.ncc_scores[index]),
                       quality=float(self.stage.qualities[index]))
        self.events.writerow(row)

    def valid(self, index):
        track, params, code = self.stage, self.basic, self.code
        return (code._is_confirmed_sidecar_source(track.sources[index])
                and code._is_non_loftr_learned_source(track.sources[index])
                and int(track.ages[index]) >= max(1, int(params["min_age"]))
                and float(track.qualities[index]) >= float(params["min_quality"])
                and float(track.ncc_scores[index]) >= float(params["min_ncc"])
                and float(track.fb_errors[index]) <= float(params["max_fb"])
                and np.all(np.isfinite(track.points[index])))

    def finalize(self, tracks, mirror_tracks, **kwargs):
        code = self.code
        frame = int(kwargs["selected_feature_index"])
        if mirror_tracks is None:
            raise RuntimeError("Lifecycle requires the independent KLT mirror")
        if int(kwargs["max_features"]) != 350 or int(kwargs["persistence_max_per_frame"]) != 6:
            raise RuntimeError("Lifecycle requires the frozen 350/6 contract")
        if not kwargs["persistence_replacement"] or not kwargs["persistence_source_router"]:
            raise RuntimeError("Lifecycle requires frozen v2 admission")
        if frame != self.previous_frame + 1:
            raise RuntimeError("Output-frame discontinuity; no synthetic continuation allowed")
        mirror = code._deduplicate_tracks_for_vins(mirror_tracks)
        mirror = code._subset_tracks_by_indices(mirror, np.arange(min(350, len(mirror))))
        newborn = [i for i, source in enumerate(mirror.sources)
                   if source == "gftt" and int(mirror.ages[i]) == 1]
        available = 350 - (len(mirror) - len(newborn))
        remaining = max(0, 50 - self.published)
        stage_index = ({int(tid): i for i, tid in enumerate(self.stage.ids)}
                       if self.stage_frame == frame else {})
        continuation = []
        next_active = {}
        previous_ids = set(self.active)
        for raw_id, (public_id, first_frame) in sorted(
                self.active.items(), key=lambda item: (item[1][1], item[1][0])):
            idx = stage_index.get(raw_id)
            if idx is None:
                reason = "absent_pre_online_stage_exact_tracker_cause_unknown"
            elif not self.valid(idx):
                reason = "current_source_or_basic_quality_invalid"
            elif len(continuation) >= remaining:
                reason = "final_publication_budget_exhausted"
            elif len(continuation) >= available:
                reason = "no_newborn_or_vacant_capacity"
            elif len(continuation) >= 6:
                reason = "per_frame_capacity"
            else:
                continuation.append((raw_id, public_id, idx))
                next_active[raw_id] = (public_id, first_frame)
                continue
            self.closed.add(raw_id)
            self.event(frame, raw_id, public_id, "terminate", reason, idx)

        indices = np.array([item[2] for item in continuation], dtype=np.int64)
        continued = (code._subset_tracks_by_indices(self.stage, indices)
                     if len(indices) else TrackSet.empty())
        continued = replace(continued, ids=np.array([item[1] for item in continuation], dtype=np.int64))
        omitted_count = max(0, len(mirror) + len(continued) - 350)
        omitted = set(newborn[-omitted_count:]) if omitted_count else set()
        protected = code._subset_tracks_by_indices(
            mirror, np.array([i for i in range(len(mirror)) if i not in omitted], dtype=np.int64))
        protected = code._append_tracksets(protected, continued)

        # Existing and closed IDs cannot masquerade as newly admitted IDs.
        new_indices = [i for i, tid in enumerate(tracks.ids)
                       if int(tid) not in previous_ids and int(tid) not in self.closed]
        new_tracks = code._subset_tracks_by_indices(tracks, np.array(new_indices, dtype=np.int64))
        new_slots = min(6 - len(continued), remaining - len(continued))
        if new_slots <= 0:
            new_tracks = TrackSet.empty()
        final_kwargs = dict(kwargs, persistence_max_per_frame=max(1, new_slots))
        final, info = self.original_final(new_tracks, protected, **final_kwargs)
        learned_mask = ~code._classical_backbone_mask(final)
        public_ids = set(int(tid) for tid in final.ids[learned_mask])
        first_ids = []
        mapping = kwargs["state"].id_map
        for idx, raw in enumerate(new_tracks.ids):
            raw_id = int(raw)
            if not code._is_non_loftr_learned_source(new_tracks.sources[idx]):
                continue
            public_id = mapping.get(("sidecar", raw_id))
            if public_id in public_ids:
                if frame > 4:
                    raise RuntimeError("First admission escaped the frozen horizon")
                next_active[raw_id] = (public_id, frame)
                first_ids.append(public_id)
        total = len(public_ids)
        self.published += total
        if total > 6 or self.published > 50 or len(final) > 350 or len(set(final.ids)) != len(final):
            raise RuntimeError("Publication capacity/identity violation")
        final_ids = set(int(tid) for tid in final.ids)
        removed = [i for i, tid in enumerate(mirror.ids) if int(tid) not in final_ids]
        if any(i not in newborn for i in removed):
            raise RuntimeError("Carried classical observation was removed")
        for raw_id, public_id, idx in continuation:
            self.event(frame, raw_id, public_id, "continue", "valid_current_observation", idx)
        for raw_id, (public_id, first_frame) in next_active.items():
            if first_frame == frame:
                self.event(frame, raw_id, public_id, "admit", "frozen_v2_first_admission", stage_index.get(raw_id))
        if self.frames is not None:
            self.frames.writerow(dict(
                selected_feature_index=frame, first_ids_json=json.dumps(first_ids),
                continued_ids_json=json.dumps([item[1] for item in continuation]),
                removed_classical_ids_json=json.dumps([int(mirror.ids[i]) for i in removed]),
                removed_classical_ages_json=json.dumps([int(mirror.ages[i]) for i in removed]),
                total_published_learned=total, cumulative_published=self.published,
                pre_online_candidate_count=len(stage_index), terminated_count=len(previous_ids - set(next_active))))
        self.active = next_active
        self.previous_frame = frame
        return final, replace(info, kept_sidecars=total, zero_sidecar_restore=(total == 0),
                              input_sidecars=info.input_sidecars + len(continued),
                              dropped_classical_for_cap=len(removed))


def main():
    if "--reset-recovered-export-ids" in sys.argv or "--learned-export-loftr-source-memory" in sys.argv:
        raise RuntimeError("Separate recovered-ID mapping is outside this frozen lifecycle experiment")
    code = load_frozen_exporter()
    directory = Path(os.environ["AQUAFE_LIFECYCLE_LOG_DIR"])
    with (directory / "lifecycle_events.csv").open("x", newline="") as events_file, \
         (directory / "lifecycle_frames.csv").open("x", newline="") as frames_file:
        events = csv.DictWriter(events_file, fieldnames=["selected_feature_index", "raw_id", "public_id", "event", "reason", "cumulative_published", "source", "raw_age", "fb", "ncc", "quality"])
        frames = csv.DictWriter(frames_file, fieldnames=["selected_feature_index", "first_ids_json", "continued_ids_json", "removed_classical_ids_json", "removed_classical_ages_json", "total_published_learned", "cumulative_published", "pre_online_candidate_count", "terminated_count"])
        events.writeheader()
        frames.writeheader()
        controller = PublishedLifecycle(code, events, frames)
        code._apply_online_seed_sidecar_gate = controller.seed_gate
        code._finalize_mirror_sidecar_export = controller.finalize
        return code.main()


if __name__ == "__main__":
    raise SystemExit(main())
