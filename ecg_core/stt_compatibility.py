"""Read-only, record-specific evidence comparison for verified implementation changes.

A compatibility certificate is not a diagnosis or a replacement review. It binds
the untouched authored annotation to equal source contents, the same edited
beats/settings, the declared measurement method and remeasured saved statistics.
An old record that was already stale is never revived by this comparison.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import struct

from .clinical_analysis import beat_basis_version
from .stt import ALGORITHM_VERSION
from .stt_range import analyze_stt_range
from .stt_records import (METHOD, RHYTHM_POLICY, RANGE_PROFILE, current_method,
                          decorate_event, digest, normalized_findings)
from .waveform import _derive
from .source_identity import SourceUnavailable, SourceReadError

SCHEMA = "stt-record-evidence-equivalence-v1"
_SCOPE_KEYS = ("case_id", "analysis_basis", "beat_revision")
_NUMERIC_KEYS = ("leads", "coverage", "counts", "method_profile")
_FRAME = struct.Struct("<8h")
SCREENING_TRANSITION_SCHEMA = "stt-screening-refinement-transition-v1"
LEGACY_SCREENING_VERSION = "stt-screening-0.4.0-comprehensive-independent"
REFINED_SCREENING_VERSION = "stt-screening-0.5.0-morphology-qualified"


def screening_versions(transition=None):
    """An explicit server-verified policy is the only historical-version grant."""
    if transition is None:
        return (ALGORITHM_VERSION,)
    if (not isinstance(transition, dict)
            or transition.get("schema") != SCREENING_TRANSITION_SCHEMA
            or transition.get("from") != LEGACY_SCREENING_VERSION
            or transition.get("to") != REFINED_SCREENING_VERSION
            or transition.get("to") != ALGORITHM_VERSION):
        return ()
    for key in ("policy_digest", "measurement_identity"):
        value = transition.get(key)
        if (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            return ()
    return (ALGORITHM_VERSION, LEGACY_SCREENING_VERSION)


def annotation_digest(annotation):
    """Bind all stored annotation content; no text, timestamp or decision is edited."""
    return digest(annotation)


def make_input_binding(feed, scope, source_basis):
    """Server-only binding for a newly saved record, independent of report adoption."""
    if scope.get("analysis_basis") != source_basis.get("digest"):
        raise ValueError("ST-T input binding does not match the saving scope")
    return dict(schema="stt-input-binding-v1", analysis_basis=source_basis["digest"],
                case_id=scope["case_id"], beat_revision=scope["beat_revision"],
                source_inputs_digest=digest(source_basis["inputs"]),
                source_contract=_source_contract(source_basis),
                beat_basis_version=beat_basis_version(feed),
                measurement_method=METHOD, screening_method=ALGORITHM_VERSION)


def _input_binding_matches(binding, annotation, basis, scope, feed, *, screening_transition=None):
    old_scope=_scope(annotation)
    return bool(isinstance(binding,dict) and binding.get("schema")=="stt-input-binding-v1"
                and binding.get("case_id")==scope.get("case_id")
                and binding.get("analysis_basis")==old_scope.get("analysis_basis")
                and binding.get("beat_revision")==scope.get("beat_revision")
                and binding.get("source_inputs_digest")==digest(basis["inputs"])
                and binding.get("source_contract")==_source_contract(basis)
                and binding.get("beat_basis_version")==beat_basis_version(feed)
                and binding.get("measurement_method")==METHOD
                and binding.get("screening_method") in screening_versions(screening_transition))


def _failure(reason):
    return {"compatible": False, "reason": reason, "proof": None}


def _source_contract(basis):
    engine = basis.get("engine") or {}
    return {key: engine.get(key) for key in ("sample_rate_hz", "channels", "input_format")}


def _valid_inputs(inputs):
    return bool(isinstance(inputs,dict) and set(inputs)=={"data","ebi","lps"}
                and all(isinstance(row,dict) and type(row.get("bytes")) is int and row["bytes"]>0
                        and isinstance(row.get("sha256"),str) and len(row["sha256"])==64
                        and all(c in "0123456789abcdef" for c in row["sha256"])
                        for row in inputs.values()))


def _scope(annotation):
    d = annotation.get("details") or {}
    return d.get("review_scope") or (d.get("stt_event_evidence") or {}).get("scope") or {}


def _metrics(result):
    return {key: copy.deepcopy(result.get(key)) for key in _NUMERIC_KEYS}


def _point_proof(path, point, total_samples, protocol):
    if not isinstance(point, dict):
        raise ValueError("point_missing")
    samples = [point.get(k) for k in ("iso_sample", "j_sample", "measurement_sample")]
    if any(type(n) is not int or not 0 <= n < total_samples for n in samples):
        raise ValueError("point_geometry")
    iso, j, measured = samples
    if not iso < j <= measured or point.get("measurement_ms") != protocol["measurement_ms"]:
        raise ValueError("point_geometry")
    if abs(measured-j-protocol["measurement_ms"]/5) > 1:
        raise ValueError("point_geometry")
    start, duration = point.get("window_start_s"), point.get("window_duration_s")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in (start, duration)) or not 0 <= start < start+duration <= total_samples/200+1e-8:
        raise ValueError("point_geometry")
    if not start*200-1 <= iso < measured <= (start+duration)*200+1:
        raise ValueError("point_geometry")
    leads = point.get("leads")
    if not isinstance(leads, list) or not leads or len(set(leads)) != len(leads):
        raise ValueError("point_leads")
    values = {}
    with Path(path).open("rb") as stream:
        for key, sample in zip(("iso", "j", "measurement"), samples):
            stream.seek(sample*_FRAME.size)
            frame = stream.read(_FRAME.size)
            if len(frame) != _FRAME.size:
                raise ValueError("point_source")
            all_values = _derive([[value] for value in _FRAME.unpack(frame)])
            if any(lead not in all_values for lead in leads):
                raise ValueError("point_leads")
            values[key] = {lead: all_values[lead][0] for lead in leads}
    return dict(samples=samples, leads=list(leads), values=values,
                differences={lead: values["measurement"][lead]-values["iso"][lead] for lead in leads},
                units="source_device_units")


def evaluate_record(annotation, previous_basis, current_basis, current_scope, current_feed,
                    waveform_path, *, persisted_basis_versions=(), range_analyzer=None,
                    implementation_compatible=False, screening_transition=None):
    """Return an evidence-equivalence certificate or an explicit refusal.

    Caller must perform source, scope, annotation and report-version checks again
    before atomically writing the certificate ledger. The annotation is untouched.
    persisted_basis_versions are original saved receipt references, not freshly
    fabricated values; they prove the old full beat/settings identity where present.
    """
    original = copy.deepcopy(annotation)
    versions = screening_versions(screening_transition)
    if not versions:
        return _failure("screening_policy_invalid")
    details = annotation.get("details") or {}
    if not isinstance(details, dict) or details.get("kind") not in ("ST", "ST_REVIEW_NOTE"):
        return _failure("not_a_st_review")
    scope = _scope(annotation)
    if details.get("reviewed") is not True or not current_method(details):
        return _failure("not_a_current_authored_review")
    if not isinstance(previous_basis, dict) or not isinstance(current_basis, dict):
        return _failure("missing_previous_basis")
    if scope.get("analysis_basis") != previous_basis.get("digest"):
        return _failure("review_was_already_stale")
    if (annotation.get("case_id") != current_scope.get("case_id")
            or scope.get("case_id") != current_scope.get("case_id")
            or scope.get("beat_revision") != current_scope.get("beat_revision")):
        return _failure("edited_beats_changed")
    if previous_basis.get("schema") != current_basis.get("schema") or previous_basis.get("recovery_epoch") != current_basis.get("recovery_epoch"):
        return _failure("source_contract_changed")
    old_contract, new_contract = _source_contract(previous_basis), _source_contract(current_basis)
    if old_contract != new_contract or new_contract != dict(sample_rate_hz=200, channels=8, input_format="little-endian int16"):
        return _failure("source_contract_changed")
    if not _valid_inputs(previous_basis.get("inputs")) or not _valid_inputs(current_basis.get("inputs")):
        return _failure("missing_source_content_evidence")
    if previous_basis.get("inputs") != current_basis.get("inputs"):
        return _failure("source_contents_changed")
    if current_scope.get("analysis_basis") != current_basis.get("digest"):
        return _failure("current_scope_mismatch")
    protocol = details.get("measurement_protocol") or {}
    if protocol.get("method_version") != METHOD or protocol.get("rhythm_policy") != RHYTHM_POLICY:
        return _failure("measurement_method_changed")
    event = decorate_event({"event_id": "annotation:"+str(annotation["id"])}, annotation,
                           beat_basis_version(current_feed))
    references = tuple(persisted_basis_versions)
    binding=details.get("stt_input_binding")
    if references:
        if event["basis_version"] not in references:
            return _failure("missing_or_changed_previous_beat_identity")
        beat_evidence="persisted_receipt_basis"
    elif binding is not None:
        if not _input_binding_matches(binding,annotation,current_basis,current_scope,current_feed,
                                      screening_transition=screening_transition):
            return _failure("stored_input_binding_changed")
        beat_evidence="server_input_binding"
    elif implementation_compatible is True:
        # Legacy unadopted records did not store a per-record beat hash. Trust
        # the existing authoritative editor revision only after the caller has
        # proved the exact published-parent/current-implementation policy; do
        # not pretend a historical hash existed. All numerical evidence below
        # must still be remeasured and equal. A stale saved reference never
        # enters this branch.
        beat_evidence="authoritative_revision_and_verified_implementation"
    else:
        return _failure("missing_or_changed_previous_beat_identity")
    evidence = details.get("stt_event_evidence") or {}
    if evidence.get("algorithm_version") not in (None, *versions):
        return _failure("screening_algorithm_changed")
    if evidence and evidence.get("rhythm_policy") != RHYTHM_POLICY:
        return _failure("measurement_method_changed")
    first = annotation.get("sample_index")
    end = details.get("end_sample", first)
    leads = details.get("review_leads") or evidence.get("leads") or []
    try:
        findings = normalized_findings(details, first, end, leads)
        children = evidence.get("findings") if isinstance(evidence.get("findings"), list) else [evidence]
        measured = []
        cache = {}
        analyzer = range_analyzer or analyze_stt_range
        if details.get("review_extent") == "whole":
            if len(children) != len(findings):
                return _failure("finding_proofs_missing")
            for finding, child in zip(findings, children):
                a, b, names = finding["start_sample"], finding["end_sample"]+1, finding["leads"]
                child_protocol = child.get("measurement_protocol") or {}
                if (child.get("result_code", finding["result_code"]) != finding["result_code"]
                        or round(child.get("start_s", -1)*200) != a
                        or round(child.get("end_s", -1)*200) != b
                        or child.get("leads") != names
                        or child_protocol.get("method_version") != METHOD
                        or child_protocol.get("rhythm_policy") != RHYTHM_POLICY
                        or child_protocol.get("extent") != "whole"):
                    return _failure("finding_proof_changed")
                if b-a >= 12000:
                    profile = child_protocol.get("range_profile") or {}
                    if profile.get("id") != RANGE_PROFILE or profile.get("rhythm_policy") != RHYTHM_POLICY:
                        return _failure("range_method_changed")
                    key = (a, b, tuple(names), child_protocol.get("measurement_ms"))
                    if key not in cache:
                        cache[key] = analyzer(waveform_path, current_feed.records, start_sample=a, end_sample=b,
                                              leads=names, measurement_ms=child_protocol["measurement_ms"],
                                              basis=current_scope, source_digest=digest(current_basis["inputs"]))
                    result = cache[key]
                    expected = dict(leads=child.get("metrics"), coverage=child.get("coverage"),
                                    counts=child.get("counts"), method_profile=profile)
                    if _metrics(result) != expected:
                        return _failure("remeasured_statistics_changed")
                    measured.append(dict(range=[a, b], leads=names,
                                         result_digest=digest(_metrics(result))))
                else:
                    measured.append(dict(range=[a, b], leads=names,
                                         source_bound_short_finding=True))
        else:
            if evidence and any(key in evidence for key in ("metrics", "findings")):
                return _failure("unsupported_point_proof")
        point = None
        if details.get("point_measurement") is not None:
            point = _point_proof(waveform_path, details["point_measurement"],
                                 round(current_feed.duration*200), protocol)
        if details.get("review_extent") != "whole" and point is None:
            return _failure("point_measurement_evidence_missing")
    except (OSError, SourceUnavailable, SourceReadError):
        return _failure("measurement_source_unavailable")
    except (ValueError, KeyError, TypeError, OverflowError):
        return _failure("invalid_measurement_evidence")
    if annotation != original:
        raise AssertionError("compatibility comparison changed the authored annotation")
    proof = dict(schema=SCHEMA, verifier="exact-source-beats-method-and-measurements",
                 annotation_digest=annotation_digest(annotation),
                 record_id="annotation:"+str(annotation["id"]),
                 previous_basis=previous_basis["digest"], current_basis=current_basis["digest"],
                 source_inputs_digest=digest(current_basis["inputs"]),
                 case_id=current_scope["case_id"], beat_revision=current_scope["beat_revision"],
                 beat_basis_version=beat_basis_version(current_feed),
                 beat_identity_evidence=beat_evidence,
                 implementation_compatible=implementation_compatible is True,
                 retained_basis_version=event["basis_version"],
                 method_version=METHOD, algorithm_version=evidence.get("algorithm_version"),
                 measurements=measured, point_digest=digest(point) if point is not None else None,
                 decision_digest=digest(dict(result_code=details.get("result_code"), findings=findings,
                                            status=details.get("status"),
                                            physician_note=details.get("physician_note"),
                                            note=annotation.get("note"))))
    if screening_transition is not None:
        proof["screening_transition"] = copy.deepcopy(screening_transition)
    return dict(compatible=True, reason="exact_record_evidence_equal", proof=proof)


def certificate_matches(proof, annotation, current_basis, current_scope, current_feed, *, screening_transition=None):
    """Check a persisted server-created certificate against current actual inputs."""
    if (not isinstance(proof, dict) or proof.get("schema") != SCHEMA
            or proof.get("verifier") != "exact-source-beats-method-and-measurements"):
        return False
    details = annotation.get("details") or {}
    versions = screening_versions(screening_transition)
    if not versions or proof.get("screening_transition") != screening_transition:
        return False
    return bool(details.get("reviewed") is True and current_method(details)
                and annotation.get("case_id") == current_scope.get("case_id")
                and proof.get("record_id") == "annotation:"+str(annotation["id"])
                and proof.get("annotation_digest") == annotation_digest(annotation)
                and proof.get("current_basis") == current_basis.get("digest") == current_scope.get("analysis_basis")
                and proof.get("source_inputs_digest") == digest(current_basis.get("inputs"))
                and proof.get("case_id") == current_scope.get("case_id")
                and proof.get("beat_revision") == current_scope.get("beat_revision")
                and proof.get("beat_basis_version") == beat_basis_version(current_feed)
                and proof.get("method_version") == METHOD
                and proof.get("algorithm_version") in (None, *versions))
