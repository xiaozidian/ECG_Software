"""Candidate-only ST/T support diagnostics in uncalibrated source units.

These engineering settings are not clinical voltage or duration criteria.  The
function reads dense source samples, never filters/replaces the measurements
returned by ``stt._beat_measurements``, and never infers a diagnosis.  A quality
rejection must not hide the measured trend or raw waveform.
"""

from __future__ import annotations

import numpy as np

from .config import CHANNEL_COUNT, SAMPLE_RATE


CANDIDATE_QUALITY_DEFAULTS = {
    "candidate_t_inversion_prominence_units": 75.0,
    "candidate_t_biphasic_prominence_units": 50.0,
    "candidate_t_minimum_halfwidth_ms": 30.0,
    "candidate_t_noise_multiplier": 3.0,
    "candidate_t_maximum_roughness_ratio": 3.0,
    "candidate_st_maximum_roughness_ratio": 3.0,
    "candidate_t_roughness_floor_units": 20.0,
    "candidate_t_alternation_floor_units": 25.0,
    "candidate_t_maximum_fast_alternations": 2,
    "candidate_t_fast_alternation_ms": 80.0,
    "candidate_t_flat_noise_maximum_units": 16.0,
    "candidate_baseline_disagreement_units": 25.0,
    "candidate_baseline_noise_multiplier": 5.0,
    "candidate_t_alignment_correlation": 0.7,
    "candidate_t_partial_minimum_recovery_fraction": 0.10,
}


def _frames(buffer, anchors, offsets, total_samples):
    offsets = np.asarray(offsets)
    positions = anchors[:, None] + (offsets[None, :] if offsets.ndim == 1 else offsets)
    np.clip(positions, 0, total_samples - 1, out=positions)
    raw = np.frombuffer(buffer, dtype="<i2").reshape(-1, CHANNEL_COUNT)
    values = raw[positions].astype(np.float64)
    a, b = values[..., 0], values[..., 1]
    return np.stack((a, b, b-a, -(a+b)/2, a-b/2, b-a/2,
                     *[values[..., i] for i in range(2, 8)]), axis=-1)


def _masked_median(values, allowed):
    if np.all(allowed):
        return np.median(values, axis=1)
    counts = np.count_nonzero(allowed, axis=1)
    if np.all(allowed == (np.arange(allowed.shape[1])[None, :] < counts[:, None])):
        # All source guards produce prefix supports.  Reducing equal-length
        # rows directly avoids nanmedian's masked-array sorting machinery.
        result = np.zeros((len(values), values.shape[2]), dtype=float)
        for count in np.unique(counts):
            if count:
                rows = counts == count
                result[rows] = np.median(values[rows, :count, :], axis=1)
        return result
    values = np.where(allowed[..., None], values, np.nan)
    # Empty supports are rejected separately; do not manufacture warnings from
    # an all-NaN reduction or read a future QRS to estimate their noise.
    empty = ~np.any(allowed, axis=1)
    values[empty, 0, :] = 0.0
    return np.nanmedian(values, axis=1)


def _median5(values):
    """Exact middle order statistic, without a fivefold partition workspace."""
    low = np.maximum(np.minimum(values[..., 0], values[..., 1]),
                     np.minimum(values[..., 2], values[..., 3]))
    high = np.minimum(np.maximum(values[..., 0], values[..., 1]),
                      np.maximum(values[..., 2], values[..., 3]))
    return np.minimum(np.maximum(values[..., 4], np.minimum(low, high)), np.maximum(low, high))


def _minimum10(values):
    """Exact ten-sample sliding minimum with four contiguous SIMD passes."""
    pairs = np.minimum(values[:, :-1, :], values[:, 1:, :])
    fours = np.minimum(pairs[:, :-2, :], pairs[:, 2:, :])
    eights = np.minimum(fours[:, :-4, :], fours[:, 4:, :])
    return np.minimum(eights[:, :-2, :], pairs[:, 8:, :])


def _local_diagnostics(values, allowed, roughness_floor):
    last = np.maximum(0, np.count_nonzero(allowed, axis=1)-1)
    final = values[np.arange(len(values)), last, :]
    safe = np.where(allowed[..., None], values, final[:, None, :])
    # This median is used ONLY to measure the high frequency residual.  Its
    # output is never a replacement waveform, ISO, ST level, or T amplitude.
    windows = np.lib.stride_tricks.sliding_window_view(
        np.pad(safe, ((0, 0), (2, 2), (0, 0)), mode="edge"), 5, axis=1)
    residual = safe - _median5(windows)
    center = _masked_median(residual, allowed)
    noise = np.maximum(1.0, 1.4826 * _masked_median(
        np.abs(residual-center[:, None, :]), allowed))
    difference_allowed = allowed[:, 1:] & allowed[:, :-1]
    variation = np.sum(np.where(difference_allowed[..., None],
                                np.abs(np.diff(safe, axis=1)), 0.0), axis=1)
    high = np.max(np.where(allowed[..., None], safe, -np.inf), axis=1)
    low = np.min(np.where(allowed[..., None], safe, np.inf), axis=1)
    span = np.maximum(0.0, high-low)
    roughness = variation / np.maximum(roughness_floor, span)
    return safe, noise, roughness


def _halfwidth(signed, allowed, peak_index, peak_prominence):
    peak_value = np.take_along_axis(signed, peak_index[:, None, :], axis=1)[:, 0, :]
    half = peak_value-peak_prominence/2
    above = (signed >= half[:, None, :]) & allowed[..., None]
    indices = np.arange(signed.shape[1])[None, :, None]
    left_out = np.max(np.where((indices < peak_index[:, None, :]) & ~above,
                               indices, -1), axis=1)
    right_out = np.min(np.where((indices > peak_index[:, None, :]) & ~above,
                                indices, signed.shape[1]), axis=1)
    width = np.maximum(0, right_out-left_out-1) * 1000.0/SAMPLE_RATE
    return np.where(peak_prominence > 0.0, width, 0.0)


def _row_halfwidth(signed, allowed, peak_index, prominence):
    peak = np.take_along_axis(signed, peak_index[..., None], axis=-1)[..., 0]
    above = (signed >= (peak-prominence/2)[..., None]) & allowed
    indices = np.arange(signed.shape[-1])
    # A sentinel guarantees argmax finds the same nearest outside cell as the
    # old integer where+max/min reductions, with boolean workspaces only.
    left = (indices < peak_index[..., None]) & ~above
    right = (indices > peak_index[..., None]) & ~above
    left = np.pad(left, [(0, 0)]*(left.ndim-1)+[(1, 0)], constant_values=True)
    right = np.pad(right, [(0, 0)]*(right.ndim-1)+[(0, 1)], constant_values=True)
    left_out = signed.shape[-1]-1-np.argmax(left[..., ::-1], axis=-1)
    right_out = np.argmax(right, axis=-1)
    width = np.maximum(0, right_out-left_out-1)*1000.0/SAMPLE_RATE
    return np.where(prominence > 0.0, width, 0.0)


def _row_minimum10(values):
    pairs = np.minimum(values[..., :-1], values[..., 1:])
    fours = np.minimum(pairs[..., :-2], pairs[..., 2:])
    eights = np.minimum(fours[..., :-4], fours[..., 4:])
    return np.minimum(eights[..., :-2], pairs[..., 8:])


def _lobes(values, allowed, noise, settings):
    # Only min/max/argmax and elementwise arithmetic move axes here.  All
    # floating sums/means/measurement medians retain their frozen code/order.
    rows = np.ascontiguousarray(values.transpose(0, 2, 1))
    valid = allowed[:, None, :]
    count = np.count_nonzero(allowed, axis=1)
    last = np.maximum(0, count-1)
    first = rows[..., 0]
    final = np.take_along_axis(rows, np.broadcast_to(last[:, None, None],
                                                    (*rows.shape[:2], 1)), axis=-1)[..., 0]
    result = {}
    for direction, name in ((1.0, "positive"), (-1.0, "negative")):
        signed = direction*rows
        left_min = _row_minimum10(np.pad(signed, ((0, 0), (0, 0), (10, 0)),
                                         constant_values=np.inf))[..., :rows.shape[-1]]
        right_min = _row_minimum10(np.pad(np.where(valid, signed, np.inf),
                                          ((0, 0), (0, 0), (0, 10)),
                                          constant_values=np.inf))[..., 1:rows.shape[-1]+1]
        local = signed-np.maximum(left_min, right_min)
        whole = signed-np.maximum(direction*first, direction*final)[..., None]
        prominence = np.where(valid & (signed > 0.0),
                              np.maximum(0.0, np.maximum(local, whole)), 0.0)
        prominence[..., 0] = 0.0
        prominence[..., -1] = 0.0
        peak_index = np.argmax(prominence, axis=-1)
        peak_prominence = np.max(prominence, axis=-1)
        width = _row_halfwidth(signed, valid, peak_index, peak_prominence)
        result[name] = (peak_prominence, width, prominence, peak_index,
                        np.zeros_like(peak_prominence, dtype=bool))
    original = result.copy()
    indices = np.arange(rows.shape[-1])
    for direction, name, opposite_name in ((1.0, "positive", "negative"),
                                           (-1.0, "negative", "positive")):
        signed = direction*rows
        peak_index = np.argmax(np.where(valid, signed, -np.inf), axis=-1)
        peak = np.take_along_axis(signed, peak_index[..., None], axis=-1)[..., 0]
        opposite = original[opposite_name]
        floor = np.maximum(settings["candidate_t_biphasic_prominence_units"],
                            settings["candidate_t_noise_multiplier"]*noise)
        possible = ((peak > 0) & (direction*final > peak/2) &
                    (peak_index < last[:, None]) & (opposite[0] >= floor) &
                    (opposite[1] >= settings["candidate_t_minimum_halfwidth_ms"]) &
                    (opposite[3] < peak_index))
        if not np.any(possible):
            continue
        beat, lead = np.nonzero(possible)
        selected = signed[beat, lead, :]
        selected_valid = allowed[beat, :]
        selected_index = peak_index[beat, lead]
        selected_peak = peak[beat, lead]
        recovered = selected_peak-np.min(np.where(
            (indices > selected_index[:, None]) & selected_valid, selected, np.inf), axis=-1)
        left_floor = np.min(np.where(
            (indices < selected_index[:, None]) & selected_valid, selected, np.inf), axis=-1)
        recovery_floor = np.maximum(settings["candidate_t_noise_multiplier"]*noise[beat, lead],
                                     settings["candidate_t_partial_minimum_recovery_fraction"]*selected_peak)
        observed_width = _row_halfwidth(selected, selected_valid, selected_index,
                                        np.maximum(0.0, selected_peak))
        old_prominence, old_width, profile, old_index, _ = original[name]
        use = ((left_floor <= noise[beat, lead]) & (recovered >= recovery_floor) &
               (observed_width >= settings["candidate_t_minimum_halfwidth_ms"]) &
               (selected_peak > old_prominence[beat, lead]))
        censored = np.zeros_like(possible)
        censored[beat, lead] = use
        updated_prominence = old_prominence.copy()
        updated_width = old_width.copy()
        updated_index = old_index.copy()
        chosen_beat, chosen_lead = beat[use], lead[use]
        updated_prominence[chosen_beat, chosen_lead] = selected_peak[use]
        updated_width[chosen_beat, chosen_lead] = observed_width[use]
        updated_index[chosen_beat, chosen_lead] = selected_index[use]
        result[name] = (updated_prominence, updated_width, profile, updated_index, censored)
    # Existing callers/API still receive [beat,time,lead] profile views.
    return {name: (value[0], value[1], value[2].transpose(0, 2, 1), value[3], value[4])
            for name, value in result.items()}


def _rapid_alternation(lobes, noise, settings):
    positive = np.ascontiguousarray(lobes["positive"][2].transpose(0, 2, 1))
    negative = np.ascontiguousarray(lobes["negative"][2].transpose(0, 2, 1))
    floor = np.maximum(settings["candidate_t_alternation_floor_units"],
                       settings["candidate_t_noise_multiplier"]*noise)
    sign = np.zeros_like(positive, dtype=np.int8)
    for prominence, polarity in ((positive, 1), (negative, -1)):
        local_peak = np.zeros_like(prominence, dtype=bool)
        local_peak[..., 1:-1] = ((prominence[..., 1:-1] > prominence[..., :-2]) &
                                (prominence[..., 1:-1] >= prominence[..., 2:]))
        sign = np.where(local_peak & (prominence >= floor[..., None]), polarity, sign)
    indices = np.arange(sign.shape[-1])
    present = sign != 0
    seen = np.maximum.accumulate(np.where(present, indices, -1), axis=-1)
    previous_index = np.concatenate((np.full_like(seen[..., :1], -1), seen[..., :-1]), axis=-1)
    previous = np.take_along_axis(sign, np.maximum(previous_index, 0), axis=-1)
    changed = present & (previous_index >= 0) & (previous != 0) & (sign != previous)
    fast_count = np.sum(changed & ((indices-previous_index) <=
                       settings["candidate_t_fast_alternation_ms"]*SAMPLE_RATE/1000.0), axis=-1)
    return fast_count > settings["candidate_t_maximum_fast_alternations"]


def _alignment(values, allowed, groups=None):
    # All floating arithmetic/reduction axes remain exactly as frozen.  Only
    # NaN padding/sort machinery for group references is avoided.
    last = np.maximum(0, np.count_nonzero(allowed, axis=1)-1)
    final = values[np.arange(len(values)), last, :]
    fraction = np.arange(values.shape[1])[None, :, None] / np.maximum(1, last)[:, None, None]
    chord = values[:, :1, :] + fraction*(final-values[:, 0, :])[:, None, :]
    shape = np.where(allowed[..., None], np.abs(values-chord), 0.0)
    shape -= np.mean(shape, axis=1, keepdims=True)
    norm = np.sqrt(np.sum(shape*shape, axis=1))
    normalized = np.divide(shape, norm[:, None, :], out=np.zeros_like(shape),
                           where=norm[:, None, :] > 0)
    if groups is None:
        reference = np.median(normalized, axis=0)[None, :, :]
        reference_norm = np.sqrt(np.sum(reference*reference, axis=1))
    else:
        _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
        order = np.argsort(inverse, kind="stable")
        starts = np.r_[0, np.cumsum(counts)[:-1]]
        references = np.empty((len(counts), *normalized.shape[1:]), dtype=float)
        for count in np.unique(counts):
            selected = np.flatnonzero(counts == count)
            positions = starts[selected, None]+np.arange(count)[None, :]
            references[selected] = np.median(normalized[order[positions]], axis=1)
        reference = references[inverse]
        reference_norm = np.sqrt(np.sum(references*references, axis=1))[inverse]
    correlation = np.divide(np.sum(normalized*reference, axis=1), reference_norm,
                            out=np.ones_like(norm), where=reference_norm > 0)
    return correlation, norm


def candidate_t_support(buffer, beats, total_samples, config, *, j_sample, next_samples,
                        alignment_groups=None):
    """Return independent ``[beat, 12-lead]`` candidate support diagnostics.

    Windows match the existing T search and its actual next-R-minus-40-ms
    guard.  No sample at or after that guard participates in noise, prominence,
    width, or alignment.  Baseline uncertainty compares the existing early ISO
    surrogate with an independent -110..-60 ms observation; neither is declared
    anatomically verified PR, and neither replaces the original baseline.

    ``t_flat_supported`` describes quality sufficient to consider low-flat T;
    the caller must still apply its measured amplitude, R-amplitude and ratio
    conditions.  Lobe support does not replace the caller's signed ISO test.

    ``j_sample`` may be one scalar or an integer array with one J offset per
    beat.  Batched callers pass original block IDs as ``alignment_groups`` to
    preserve the descriptive within-block median alignment exactly.
    """
    if not beats:
        return {}
    settings = {**CANDIDATE_QUALITY_DEFAULTS,
                **{k: v for k, v in (config or {}).items() if k in CANDIDATE_QUALITY_DEFAULTS}}
    anchors = np.asarray([beat[0] for beat in beats], dtype=int)
    j_offsets = np.asarray(j_sample, dtype=int)
    if j_offsets.ndim == 0:
        j_offsets = np.full(len(beats), int(j_offsets), dtype=int)
    if j_offsets.shape != anchors.shape:
        raise ValueError("candidate support requires one J offset per beat")
    if alignment_groups is not None:
        alignment_groups = np.asarray(alignment_groups)
        if alignment_groups.shape != anchors.shape:
            raise ValueError("candidate alignment requires one block ID per beat")
    nexts = np.asarray(next_samples, dtype=int)
    if nexts.shape != anchors.shape:
        raise ValueError("candidate support requires the real next R for every beat")
    early = _frames(buffer, anchors, range(-40, -23), total_samples)
    late = _frames(buffer, anchors, range(-22, -11), total_samples)
    early_center = np.median(early, axis=1)
    late_center = np.median(late, axis=1)
    baseline_noise = np.maximum(1.0, 1.4826*np.median(
        np.abs(early-early_center[:, None, :]), axis=1))
    disagreement = np.abs(early_center-late_center)
    baseline_uncertain = disagreement > np.maximum(
        settings["candidate_baseline_disagreement_units"],
        settings["candidate_baseline_noise_multiplier"]*baseline_noise)
    baseline_source_valid = (anchors-40 >= 0) & (anchors-12 < total_samples)
    baseline_uncertain |= ~baseline_source_valid[:, None]

    offsets = j_offsets[:, None]+np.arange(24, 73)[None, :]
    rr = np.maximum(np.asarray([beat[2] for beat in beats])*SAMPLE_RATE/1000.0,
                    .45*SAMPLE_RATE)
    last = np.minimum(j_offsets+72, np.maximum(j_offsets+30, np.rint(rr*.62))).astype(int)
    last = np.minimum(last, nexts-anchors-8)
    allowed = ((offsets <= last[:, None]) &
               (anchors[:, None]+offsets < total_samples) &
               (anchors[:, None]+offsets >= 0))
    values = _frames(buffer, anchors, offsets, total_samples)-early_center[:, None, :]
    safe, t_noise, t_roughness = _local_diagnostics(
        values, allowed, settings["candidate_t_roughness_floor_units"])
    lobes = _lobes(safe, allowed, t_noise, settings)
    rapid = _rapid_alternation(lobes, t_noise, settings)
    valid = np.broadcast_to((np.count_nonzero(allowed, axis=1) >= 5)[:, None],
                            t_noise.shape).copy()
    correlation, alignment_energy = _alignment(safe, allowed, alignment_groups)
    aligned = ((correlation >= settings["candidate_t_alignment_correlation"]) |
               (alignment_energy <= settings["candidate_t_alternation_floor_units"])) & valid

    st_offsets = j_offsets[:, None]+np.arange(4, 21)[None, :]
    st_allowed = ((st_offsets <= (nexts-anchors-8)[:, None]) &
                  (anchors[:, None]+st_offsets < total_samples) &
                  (anchors[:, None]+st_offsets >= 0))
    st_values = _frames(buffer, anchors, st_offsets, total_samples)-early_center[:, None, :]
    _, st_noise, st_roughness = _local_diagnostics(
        st_values, st_allowed, settings["candidate_t_roughness_floor_units"])
    st_valid = np.count_nonzero(st_allowed, axis=1) >= 5
    t_roughness_excessive = t_roughness > settings["candidate_t_maximum_roughness_ratio"]
    st_roughness_excessive = st_roughness > settings["candidate_st_maximum_roughness_ratio"]
    good = valid & ~baseline_uncertain & ~rapid & ~t_roughness_excessive
    st_good = (st_valid[:, None] & ~baseline_uncertain &
               ~st_roughness_excessive)
    minimum_width = settings["candidate_t_minimum_halfwidth_ms"]
    inversion_floor = np.maximum(settings["candidate_t_inversion_prominence_units"],
                                 settings["candidate_t_noise_multiplier"]*t_noise)
    biphasic_floor = np.maximum(settings["candidate_t_biphasic_prominence_units"],
                                settings["candidate_t_noise_multiplier"]*t_noise)
    pos, neg = lobes["positive"], lobes["negative"]
    positive_supported = good & (pos[0] >= inversion_floor) & (pos[1] >= minimum_width)
    negative_supported = good & (neg[0] >= inversion_floor) & (neg[1] >= minimum_width)
    biphasic_supported = (good & (pos[0] >= biphasic_floor) & (neg[0] >= biphasic_floor) &
                          (pos[1] >= minimum_width) & (neg[1] >= minimum_width))
    return {
        "t_support_valid": valid,
        "t_positive_prominence_units": pos[0], "t_negative_prominence_units": neg[0],
        "t_positive_halfwidth_ms": pos[1], "t_negative_halfwidth_ms": neg[1],
        "t_positive_right_censored": pos[4], "t_negative_right_censored": neg[4],
        "t_local_noise_units": t_noise, "st_local_noise_units": st_noise,
        "t_roughness_ratio": t_roughness, "st_roughness_ratio": st_roughness,
        "t_rapid_alternation": rapid, "t_alignment_consistent": aligned,
        "t_roughness_excessive": t_roughness_excessive,
        "st_roughness_excessive": st_roughness_excessive,
        "t_noise_above_flat_limit": t_noise > settings["candidate_t_flat_noise_maximum_units"],
        "t_positive_lobe_too_narrow": (pos[0] > 0) & (pos[1] < minimum_width),
        "t_negative_lobe_too_narrow": (neg[0] > 0) & (neg[1] < minimum_width),
        "t_positive_lobe_weak": pos[0] < inversion_floor,
        "t_negative_lobe_weak": neg[0] < inversion_floor,
        "baseline_uncertain": baseline_uncertain,
        "baseline_disagreement_units": disagreement,
        "t_shape_quality_good": good, "st_baseline_quality_good": st_good,
        "t_positive_lobe_supported": positive_supported,
        "t_negative_lobe_supported": negative_supported,
        "t_biphasic_supported": biphasic_supported,
        "t_flat_supported": good & (t_noise <= settings["candidate_t_flat_noise_maximum_units"]),
    }
