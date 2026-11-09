"""The later controller cannot relabel original PE compilation provenance."""
import pytest

from scripts.verify_windows_af_multistrip_native import bind_acceptance_provenance


def fixture():
    return ({"source_commit": "a" * 40}, dict(source_compile_commit="a" * 40,
            producer_run_id=11, controller_commit="b" * 40, acceptance_run_id=22))


def test_continuation_keeps_producer_and_controller_identity_distinct():
    package, args = fixture()
    result = bind_acceptance_provenance(package, **args)
    assert result == {**args, "original_PE_recompiled": False,
                      "original_delivery_ZIPs_repacked": False}
    assert package == {"source_commit": "a" * 40}


@pytest.mark.parametrize("fault", ["wrong_PE_commit", "invalid_source_commit",
                                  "invalid_controller_commit", "same_commit",
                                  "same_run", "non_integer_run", "zero_run"])
def test_continuation_rejects_provenance_substitution(fault):
    package, args = fixture()
    if fault == "wrong_PE_commit":
        package["source_commit"] = "c" * 40
    elif fault == "invalid_source_commit":
        args["source_compile_commit"] = "HEAD"
    elif fault == "invalid_controller_commit":
        args["controller_commit"] = "latest"
    elif fault == "same_commit":
        args["controller_commit"] = args["source_compile_commit"]
    elif fault == "same_run":
        args["acceptance_run_id"] = args["producer_run_id"]
    elif fault == "non_integer_run":
        args["producer_run_id"] = True
    else:
        args["acceptance_run_id"] = 0
    with pytest.raises(AssertionError):
        bind_acceptance_provenance(package, **args)
