"""Freeze a separately reviewed 0.4→0.5 screening-refinement policy.

Only exact published engine manifests are accepted. No clinical database,
annotations, report or patient source is read by this build tool.
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ecg_core.analysis_provenance import MODULES
from ecg_core.performance_compatibility import code_fingerprints, digest
from ecg_core.screening_compatibility import (POLICY_NAME, POLICY_SCHEMA, CONTINUITY_KIND,
    LEGACY_SCREENING_VERSION, REFINED_SCREENING_VERSION, measurement_contract)


def build(root, parents):
    root = Path(root).resolve()
    contract = measurement_contract(root, require_source=True)
    names = ("app",) + tuple("ecg_core." + name for name in MODULES)
    engines = []
    allowed = {"app_version", "artifacts", "dependencies", "sample_rate_hz", "channels", "input_format"}
    for engine in parents:
        if (not isinstance(engine, dict) or not set(engine) <= allowed
                or not isinstance(engine.get("artifacts"), dict)
                or not engine["artifacts"].get("ecg_core.stt")
                or engine.get("sample_rate_hz") != 200 or engine.get("channels") != 8
                or engine.get("input_format") != "little-endian int16"):
            raise ValueError("仅接受明确发布的0.4程序engine清单，不接受病例或临床数据")
        engines.append(engine)
    if not engines:
        raise ValueError("需要明确的已发布0.4父程序清单")
    return dict(schema=POLICY_SCHEMA, continuity_kind=CONTINUITY_KIND,
                screening_from=LEGACY_SCREENING_VERSION, screening_to=REFINED_SCREENING_VERSION,
                current_code=code_fingerprints(root, names),
                parent_engine_ids=sorted({digest(engine) for engine in engines}),
                parent_engines=sorted(engines, key=digest), measurement_contract=contract)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--parents", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    parents = json.loads(args.parents.read_bytes())
    if isinstance(parents, dict):
        parents = [parents]
    policy = build(args.source, parents)
    output = args.output or args.source / POLICY_NAME
    output.write_text(json.dumps(policy, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print("Frozen screening refinement:", len(policy["current_code"]), "modules,",
          len(policy["parent_engine_ids"]), "published parent engines")
