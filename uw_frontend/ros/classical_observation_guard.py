"""Fail-closed safety boundary for paired KLT/proposed feature messages.

Protect ALL baseline observations, not just mature tracks. This is not an
algorithmic no-harm guarantee: a valid additive proposal may still harm VIO.
No frozen exporter or backend is changed. Decisions use current/past frames.
"""
import io
import math
import struct


def message_bytes(message):
    stream = io.BytesIO()
    message.serialize(stream)
    return stream.getvalue()


def observations(message):
    names = [channel.name for channel in message.channels]
    if len(set(names)) != len(names) or not {'id', 'camera_id'}.issubset(names):
        raise ValueError('invalid channel schema')
    if any(len(channel.values) != len(message.points) for channel in message.channels):
        raise ValueError('channel length mismatch')
    id_index, camera_index = names.index('id'), names.index('camera_id')
    result = []
    for index, point in enumerate(message.points):
        values = [float(channel.values[index]) for channel in message.channels]
        if not all(math.isfinite(x) for x in [point.x, point.y, point.z, *values]):
            raise ValueError('nonfinite observation')
        tid, camera = values[id_index], values[camera_index]
        if tid != int(tid) or camera != int(camera):
            raise ValueError('noninteger identity')
        key = (int(tid), int(camera))
        payload = struct.pack('<' + 'f' * (3 + len(values)), point.x, point.y, point.z, *values)
        result.append((key, payload))
    if len({key for key, _ in result}) != len(result):
        raise ValueError('duplicate observation identity')
    return result


class ClassicalObservationGuard:
    """Latch baseline fallback after any destructive/malformed proposal."""

    def __init__(self):
        self.latched_reason = None
        self.frames = 0

    def select(self, baseline, proposal):
        # A malformed baseline is a contract error, not something to truncate.
        base = observations(baseline)
        if len(base) > 350:
            raise ValueError('baseline exceeds frozen 350 cap')
        self.frames += 1
        if self.latched_reason:
            return baseline, 'latched:' + self.latched_reason
        reason = None
        if message_bytes(baseline.header) != message_bytes(proposal.header):
            reason = 'header_changed'
        elif [c.name for c in baseline.channels] != [c.name for c in proposal.channels]:
            reason = 'channel_schema_changed'
        else:
            try:
                proposed = observations(proposal)
            except ValueError:
                proposed = []
                reason = 'malformed_proposal'
            if reason is None:
                by_key = dict(proposed)
                base_keys = {key for key, _ in base}
                if len(proposed) > 350:
                    reason = 'feature_cap_exceeded'
                elif any(key not in by_key for key, _ in base):
                    reason = 'baseline_observation_deleted'
                elif any(by_key[key] != payload for key, payload in base):
                    reason = 'baseline_observation_modified'
                elif [key for key, _ in proposed if key in base_keys] != [key for key, _ in base]:
                    reason = 'baseline_observation_reordered'
        if reason:
            self.latched_reason = reason
            return baseline, reason
        return proposal, 'preserved_baseline'
