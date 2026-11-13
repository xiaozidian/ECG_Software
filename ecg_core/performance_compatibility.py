"""Audited continuity of reviewed evidence across a verified performance-only build.

The reference analysis basis stays unchanged; executing-build guards remain
strict. This is neither a doctor confirmation nor a general algorithm alias.
"""
from __future__ import annotations
import copy
import importlib.util
import json
import struct
import threading
from hashlib import sha256
from pathlib import Path
from types import CodeType

POLICY_NAME = "performance-compatibility.json"
POLICY_SCHEMA = "performance-evidence-continuity-v1"


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
                             separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _constant(value):
    if isinstance(value,CodeType):return ["code",code_value(value)]
    if value is Ellipsis:return ["ellipsis"]
    if isinstance(value,bytes):return ["bytes",value.hex()]
    if type(value) is float:return ["float64",struct.pack(">d",value).hex()]
    if type(value) is complex:return ["complex",_constant(value.real),_constant(value.imag)]
    if isinstance(value,tuple):return ["tuple",[_constant(v) for v in value]]
    if isinstance(value,frozenset):
        return ["frozenset",sorted((_constant(v) for v in value),key=lambda x:json.dumps(x,sort_keys=True))]
    return value


def code_value(code):
    # Exclude only installation paths and debugging line positions. All actual
    # instructions, constants, names, argument and exception semantics remain.
    return dict(bytecode=code.co_code.hex(),constants=[_constant(v) for v in code.co_consts],
                names=code.co_names,variables=code.co_varnames,free=code.co_freevars,cells=code.co_cellvars,
                args=code.co_argcount,posonly=code.co_posonlyargcount,kwonly=code.co_kwonlyargcount,
                locals=code.co_nlocals,stack=code.co_stacksize,flags=code.co_flags,
                exceptions=getattr(code,"co_exceptiontable",b"").hex(),
                name=code.co_name,qualname=getattr(code,"co_qualname",code.co_name))


def code_fingerprints(root, module_names):
    result={}
    for name in module_names:
        path=Path(root)/("app.py" if name=="app" else "ecg_core/"+name.split(".")[-1]+".py")
        if path.is_file():
            code=compile(path.read_bytes(),name,"exec",dont_inherit=True,optimize=0)
        else:
            spec=importlib.util.find_spec(name)
            code=spec.loader.get_code(name) if spec and hasattr(spec.loader,"get_code") else None
            if code is None:raise ValueError("无法核对性能升级的完整执行代码")
        result[name]=digest(code_value(code))
    return result


class PerformanceCompatibility:
    policy_name = POLICY_NAME
    policy_schema = POLICY_SCHEMA

    def __init__(self, root, runtime, storage, editor):
        self.root=Path(root);self.runtime=runtime;self.storage=storage;self.editor=editor
        self.policy=None;self.policy_digest=None;self._code_ok=False;self._lock=threading.RLock()
        path=self.root/self.policy_name
        if not path.is_file():return
        runtime.assert_current()
        policy=json.loads(path.read_bytes())
        runtime.assert_current()
        if policy.get("schema")!=self.policy_schema:return
        self.policy=policy;self.policy_digest=digest(policy)
        try:
            names=("app",)+tuple("ecg_core."+n for n in runtime.module_names)
            actual=code_fingerprints(self.root,names)
            self._code_ok=actual==policy.get("current_code")
        except (ImportError,ValueError,OSError,TypeError):
            self._code_ok=False

    def diagnostics(self):
        return dict(policy_present=self.policy is not None,code_matched=self._code_ok,
                    parent_builds=len(self.policy.get("parent_engine_ids",[])) if self.policy else 0,
                    executing_engine_id=self.runtime.engine_id)

    def build_allowed(self, previous, current):
        if not self.policy or not self._code_ok:return False
        old_engine=previous.get("engine") or {}
        if (previous.get("engine_id")!=digest(old_engine)
                or previous.get("engine_id") not in self.policy.get("parent_engine_ids",[])
                or digest(old_engine) not in {digest(x) for x in self.policy.get("parent_engines",[])}):
            return False
        body={k:previous[k] for k in ("schema","engine_id","inputs") if k in previous}
        if previous.get("recovery_epoch"):body["recovery_epoch"]=previous["recovery_epoch"]
        if digest(body)!=previous.get("digest"):return False
        if (previous.get("schema")!=current.get("schema")
                or previous.get("inputs")!=current.get("inputs")
                or previous.get("recovery_epoch","")!=current.get("recovery_epoch","")
                or old_engine.get("dependencies")!=current.get("engine",{}).get("dependencies")):
            return False
        for field in ("sample_rate_hz","channels","input_format"):
            if old_engine.get(field)!=current.get("engine",{}).get(field):return False
        return True

    def resolve(self, case, previous, current, feed, annotations, report, review_revision, beat_revision):
        if not self.build_allowed(previous,current):return None
        from .stt_records import review_metadata
        from .stt_compatibility import evaluate_record, annotation_digest
        scope=dict(case_id=case["case_id"],analysis_basis=current["digest"],
                   analysis_revision=review_revision,beat_revision=beat_revision)
        references={}
        comp=report.get("composition") or {}
        for row in list(comp.get("selected_events",[]))+list(comp.get("stt_report_use",[])):
            if isinstance(row,dict) and row.get("basis_version"):
                references.setdefault(row.get("event_id"),[]).append(row["basis_version"])
        proofs=[];preserved=[]
        for record in annotations:
            if record.get("details",{}).get("kind") not in ("ST","ST_REVIEW_NOTE"):continue
            receipt=review_metadata(record)
            old_scope=record.get("details",{}).get("review_scope") or (record.get("details",{}).get("stt_event_evidence") or {}).get("scope") or {}
            # Never revive a review that the reference implementation already
            # considered unreviewed, method-stale, source-stale or beat-stale.
            was_current=(receipt["review_state"]=="reviewed"
                         and old_scope.get("case_id")==case["case_id"]
                         and old_scope.get("analysis_basis")==previous["digest"]
                         and old_scope.get("beat_revision")==scope["beat_revision"])
            if not was_current:continue
            checked=evaluate_record(record,previous,current,scope,feed,case["paths"]["data"],
                         persisted_basis_versions=references.get("annotation:"+str(record["id"]),()),
                         implementation_compatible=True, **self.record_evaluation_options())
            if not checked["compatible"]:return None
            proofs.append(checked["proof"]);preserved.append(record["id"])
        return dict(schema=self.policy_schema,policy_digest=self.policy_digest,
                    reference_basis=copy.deepcopy(previous),execution_basis=current["digest"],
                    execution_engine_id=self.runtime.engine_id,
                    source_inputs_digest=digest(current["inputs"]),beat_revision=scope["beat_revision"],
                    authored_annotations_digest=digest(annotations),editor_document_digest=digest(feed.document),
                    review_revision=review_revision,report_version=report.get("version",1),
                    report_composition_digest=digest(comp),stt_proofs=proofs,retained_stt_records=preserved)

    def record_evaluation_options(self):
        # Performance upgrades retain the strict current-screening requirement.
        # A separately verified refinement policy may supply its own transition.
        return {}
