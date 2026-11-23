"""Preserve authored evidence across one explicitly verified screening refinement.

Candidate selection changes from 0.4 to 0.5. Raw measurement identity does not.
The immutable 0.4 implementation replays signed report presentation; it never
supplies the current workstation's candidates or rewrites a doctor's record.
"""
from __future__ import annotations

import ast
import copy
import importlib
import importlib.util
from pathlib import Path
from types import CodeType
from hashlib import sha256

from .performance_compatibility import PerformanceCompatibility, code_value, digest
from .review_workflow import ReportConflict
from .stt_compatibility import (SCREENING_TRANSITION_SCHEMA, LEGACY_SCREENING_VERSION,
                                REFINED_SCREENING_VERSION)

POLICY_NAME = "screening-refinement-compatibility.json"
POLICY_SCHEMA = "stt-screening-refinement-continuity-v1"
CONTINUITY_KIND = "stt_screening_refinement"
SNAPSHOT_SCHEMA = "stt-signed-screening-presentation-v1"
LEGACY_SOURCE_SHA256 = "8e46a1393254c3b08d409a4e7a0b4a65ece35f4aa140d762db8e69055ec5c031"
BASELINE_MODULE_SHA256 = {
    "stt_range": "bffaab3c22f6cf48372f66ea0a074127b02dbc3f8441b1287a1b931c76f8ef49",
    "stt_records": "34703e862507136fad000d3ff9d02d0ed61d1dac1c49fc94ff085b678ad16f5b",
    "waveform": "52d0c3dfc40ea0e8129bbd997974dfff54974782eb0b953561f81e1f16a4fbf7",
    "clinical_analysis": "b357a407765f6232ea4ba1c02d2637dbf0643e185742173bf25405ba54a5af17",
    "beat_editor": "e3a7e351a95ac4f78c8dceedda5a21c135737d4aebb0485d1c4af442bb7b5ff1",
}
MEASUREMENT_HELPERS = (
    "_median", "_mad", "_derived", "_read_leads", "_normalize_records", "_evenly",
    "_estimate_j_sample", "_sample_frames", "_beat_measurements", "_block_measurement",
    "_support", "_finite", "minute_trends",
)


def _module_code(root, name):
    path = Path(root) / "ecg_core" / (name + ".py")
    if path.is_file():
        return compile(path.read_bytes(), "ecg_core." + name, "exec", dont_inherit=True, optimize=0)
    spec = importlib.util.find_spec("ecg_core." + name)
    code = spec.loader.get_code("ecg_core." + name) if spec and hasattr(spec.loader, "get_code") else None
    if code is None:
        raise ValueError("筛查升级缺少可验证的完整执行代码")
    return code


def _literals(root, name, keys):
    path = Path(root) / "ecg_core" / (name + ".py")
    if not path.is_file():
        module = importlib.import_module("ecg_core." + name)
        return {key: copy.deepcopy(getattr(module, key)) for key in keys}
    values = {}
    for node in ast.parse(path.read_bytes()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in keys:
                    values[target.id] = ast.literal_eval(node.value)
    if set(values) != set(keys):
        raise ValueError("筛查升级缺少原始方法常量")
    return values


def measurement_contract(root, *, require_source=False):
    """Exact baseline helpers/configuration plus the unchanged measurement modules.

    The build step requires the immutable source hashes. Frozen installations
    instead recheck the resulting full code fingerprints in their policy.
    """
    root = Path(root)
    baseline = root / "ecg_core/stt_screening_legacy.py"
    if baseline.is_file():
        if sha256(baseline.read_bytes()).hexdigest() != LEGACY_SOURCE_SHA256:
            raise ValueError("旧版筛查代码不等于冻结的0.4原件")
    elif require_source:
        raise ValueError("生成策略必须提供冻结的0.4源代码")
    for name, expected in BASELINE_MODULE_SHA256.items():
        path = root / "ecg_core" / (name + ".py")
        if path.is_file():
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("筛查升级改变了测量依赖：" + name)
        elif require_source:
            raise ValueError("生成策略缺少测量依赖：" + name)
    old = _literals(root, "stt_screening_legacy", ("ALGORITHM_VERSION", "DEFAULT_CONFIG", "LEADS"))
    new = _literals(root, "stt", ("ALGORITHM_VERSION", "DEFAULT_CONFIG", "LEADS"))
    if old["ALGORITHM_VERSION"] != LEGACY_SCREENING_VERSION or new["ALGORITHM_VERSION"] != REFINED_SCREENING_VERSION:
        raise ValueError("仅支持明确的0.4到0.5筛查升级")
    current_configuration = {key: new["DEFAULT_CONFIG"].get(key) for key in old["DEFAULT_CONFIG"]}
    if new["LEADS"] != old["LEADS"] or digest(current_configuration) != digest(old["DEFAULT_CONFIG"]):
        raise ValueError("筛查升级改变了原有测量配置")
    helpers = []
    for name in ("stt_screening_legacy", "stt"):
        code = _module_code(root, name)
        functions = {c.co_name: c for c in code.co_consts if isinstance(c, CodeType)}
        if not set(MEASUREMENT_HELPERS) <= set(functions):
            raise ValueError("筛查升级缺少原有测量函数")
        helpers.append({key: digest(code_value(functions[key])) for key in MEASUREMENT_HELPERS})
    if helpers[0] != helpers[1]:
        raise ValueError("筛查升级改变了原有测量函数")
    from .stt_records import METHOD, RANGE_PROFILE, RHYTHM_POLICY
    from .stt_range import method_profile
    if (METHOD != "stt-hospital-review-v3"
            or RANGE_PROFILE != "raw-200hz-fixed16s-st-perbeat-morphology-v3"
            or RHYTHM_POLICY != "independent_of_AF_AFL_reviews"):
        raise ValueError("筛查升级改变了测量协议")
    return dict(schema="stt-unchanged-measurement-contract-v1", legacy_source_sha256=LEGACY_SOURCE_SHA256,
                helpers=helpers[0], configuration=old["DEFAULT_CONFIG"], leads=list(old["LEADS"]),
                measurement_modules={name: digest(code_value(_module_code(root, name)))
                                     for name in BASELINE_MODULE_SHA256},
                method=METHOD, range_profiles={str(ms): method_profile(ms) for ms in (0, 60, 80)},
                rhythm_policy=RHYTHM_POLICY)


def _review(analysis):
    return dict(analysis=analysis, automatic_candidates=dict(enabled=True,
                items=analysis["candidates"], quality=analysis["quality"]))


def measurement_projection(analysis):
    # Screening-only metadata and candidates are deliberately separate. Every
    # displayed raw trend value, gap, coverage flag and contract is compared.
    return {key: copy.deepcopy(analysis.get(key)) for key in
            ("trends", "quality", "sample_rate_hz", "units", "unit_label",
             "calibration_status", "exclusions", "rhythm_policy")}


def report_identity(report):
    return digest({key: report.get(key) for key in
                   ("version", "conclusion", "composition", "status", "reviewed_by",
                    "updated_at", "analysis_provenance")})


def edited_feed_identity(feed):
    """Cryptographic edited-beat/settings identity, beyond the display hash."""
    rows = feed.beats + feed.markers
    return digest(dict(records=feed.records,duration_s=feed.duration,
        beats=[(row['id'],row['sample_index'],row['class_code']) for row in rows],
        settings=feed.document['settings']))


class ScreeningCompatibility(PerformanceCompatibility):
    policy_name = POLICY_NAME
    policy_schema = POLICY_SCHEMA

    def __init__(self, root, runtime, storage, editor):
        super().__init__(root, runtime, storage, editor)
        self._measurement_ok = False
        self._verified_certificate_reuses = 0
        self._full_verification_attempts = 0
        if not self.policy or not self._code_ok:
            return
        try:
            actual = measurement_contract(self.root)
            self._measurement_ok = (actual == self.policy.get("measurement_contract")
                and self.policy.get("screening_from") == LEGACY_SCREENING_VERSION
                and self.policy.get("screening_to") == REFINED_SCREENING_VERSION
                and self.policy.get("continuity_kind") == CONTINUITY_KIND)
        except (ImportError, ValueError, OSError, TypeError, KeyError, AttributeError):
            self._measurement_ok = False

    def diagnostics(self):
        return {**super().diagnostics(), "continuity_kind": CONTINUITY_KIND,
                "measurement_matched": self._measurement_ok,
                "verified_certificate_reuses": self._verified_certificate_reuses,
                "full_verification_attempts": self._full_verification_attempts}

    def build_allowed(self, previous, current):
        return self._measurement_ok and super().build_allowed(previous, current)

    def record_evaluation_options(self):
        if not self._measurement_ok:
            return {}
        return {
            "screening_transition": {"schema": SCREENING_TRANSITION_SCHEMA,
                "policy_digest": self.policy_digest, "from": LEGACY_SCREENING_VERSION,
                "to": REFINED_SCREENING_VERSION,
                "measurement_identity": digest(self.policy["measurement_contract"])}}

    def resolve(self, case, previous, current, feed, annotations, report, review_revision, beat_revision):
        if not self.build_allowed(previous,current):
            return None
        if self.storage is not None:
            cached = self.storage.get_compatible_implementation(case['case_id'],
                self.runtime.engine_id,current['digest'])
            if cached and self._cached_snapshot_matches(cached,case,previous,current,feed,
                                                        annotations,report,review_revision,beat_revision):
                self.runtime.assert_current()
                with self._lock:self._verified_certificate_reuses += 1
                # Keep the original proof byte-for-byte. Atomic commit guards
                # and the live source guard still run in the caller.
                return copy.deepcopy(cached)
        with self._lock:self._full_verification_attempts += 1
        certificate = super().resolve(case, previous, current, feed, annotations, report, review_revision, beat_revision)
        if certificate is None:
            return None
        from . import stt, stt_screening_legacy
        from .clinical_analysis import beat_basis_version
        from .report_sections import screening_presentation, screening_snapshot
        old = stt_screening_legacy.analyze_stt(case["paths"]["data"], feed.records,
                                              feed.duration, analysis_revision=beat_revision)
        new = stt.analyze_stt(case["paths"]["data"], feed.records,
                               feed.duration, analysis_revision=beat_revision)
        old_measurements, new_measurements = measurement_projection(old), measurement_projection(new)
        if digest(old_measurements) != digest(new_measurements):
            return None
        certificate.update(continuity_kind=CONTINUITY_KIND,case_id=case['case_id'],
            screening_transition=self.record_evaluation_options()["screening_transition"],
            beat_basis_version=beat_basis_version(feed),
            edited_feed_digest=edited_feed_identity(feed),
            measurement_projection_digest=digest(old_measurements),
            report_state_digest=report_identity(report),
            signed_report_snapshot=None)
        origin = (report.get("analysis_provenance") or {}).get("screening_algorithm_version")
        if report.get("status") == "reviewed" and origin not in (None, LEGACY_SCREENING_VERSION, REFINED_SCREENING_VERSION):
            return None
        if report.get("status") == "reviewed" and origin != REFINED_SCREENING_VERSION:
            old_presentation = screening_presentation(_review(old))
            snapshot = screening_snapshot(old_presentation)
            new_presentation = screening_presentation(_review(new))
            new_presentation["st_evaluation"] = copy.deepcopy(snapshot["st_evaluation"])
            if digest(new_presentation) != digest(old_presentation):
                return None
            certificate["signed_report_snapshot"] = dict(schema=SNAPSHOT_SCHEMA,
                report_identity=report_identity(report), report_version=report.get("version", 1),
                **snapshot, before_digest=digest(old_presentation), after_digest=digest(new_presentation))
        self.runtime.assert_current()
        return certificate

    def _cached_snapshot_matches(self, certificate, case, previous, current, feed,
                                 annotations, report, review_revision, beat_revision):
        """Accept audited prior computation only for this exact live snapshot."""
        from .clinical_analysis import beat_basis_version
        context = dict(schema=POLICY_SCHEMA,continuity_kind=CONTINUITY_KIND,
            case_id=case['case_id'],policy_digest=self.policy_digest,
            screening_transition=self.record_evaluation_options()['screening_transition'],
            reference_basis=previous,execution_basis=current['digest'],
            execution_engine_id=self.runtime.engine_id,source_inputs_digest=digest(current['inputs']))
        if (current.get('engine_id') != self.runtime.engine_id
                or digest(current.get('engine') or {}) != self.runtime.engine_id
                or any(certificate.get(key) != value for key,value in context.items())):
            return False
        state = report_identity(report)
        if (certificate.get('report_version') == report.get('version',1)
                and certificate.get('report_state_digest') != state):
            # A genuine server edit advances the report version. Recomputing
            # signal measurements cannot authorize a same-version text/signature
            # rewrite, even if the database was edited outside the UI.
            raise ReportConflict('报告内容或签署状态在同一版本下变化，请重新核对')
        snapshot = dict(beat_revision=beat_revision,beat_basis_version=beat_basis_version(feed),
            edited_feed_digest=edited_feed_identity(feed),editor_document_digest=digest(feed.document),
            authored_annotations_digest=digest(annotations),review_revision=review_revision,
            report_version=report.get('version',1),report_composition_digest=digest(report.get('composition') or {}),
            report_state_digest=state)
        if any(certificate.get(key) != value for key,value in snapshot.items()):
            return False
        identity = certificate.get('measurement_projection_digest')
        if not isinstance(identity,str) or len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):
            return False
        signed = certificate.get('signed_report_snapshot')
        origin = (report.get('analysis_provenance') or {}).get('screening_algorithm_version')
        if report.get('status')=='reviewed' and origin != REFINED_SCREENING_VERSION:
            if (not isinstance(signed,dict) or signed.get('schema') != SNAPSHOT_SCHEMA
                    or signed.get('report_identity') != state
                    or signed.get('report_version') != report.get('version',1)
                    or not signed.get('before_digest')
                    or signed.get('before_digest') != signed.get('after_digest')):
                return False
        elif signed is not None:
            return False
        return True

    def apply_report_presentation(self, case, report, value, feed):
        """Project an unchanged signed report; new drafts use current screening."""
        if report.get("status") != "reviewed":
            return value
        certificate = self.runtime.compatibility_certificate(case)
        if not certificate or certificate.get("schema") != POLICY_SCHEMA:
            return value
        snapshot = certificate.get("signed_report_snapshot")
        if not snapshot:
            return value
        if snapshot.get("report_identity") != report_identity(report):
            origin = (report.get("analysis_provenance") or {}).get("screening_algorithm_version")
            if (report.get("version") != snapshot.get("report_version")
                    and origin == REFINED_SCREENING_VERSION):
                # A genuine new server save follows ordinary draft/re-sign rules.
                return value
            raise ReportConflict("原签署报告内容或签署状态已变化，请重新载入并复核")
        from .clinical_analysis import beat_basis_version
        from .report_sections import apply_screening_snapshot
        if (certificate.get("policy_digest") != self.policy_digest
                or not self._measurement_ok
                or certificate.get("beat_basis_version") != beat_basis_version(feed)):
            raise ReportConflict("原签署报告的筛查兼容依据已变化，请重新复核")
        return apply_screening_snapshot(value, snapshot)
