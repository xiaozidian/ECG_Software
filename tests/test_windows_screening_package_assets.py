import json
import pytest
from test_windows_doctor_build import minimal_package
from scripts.windows_doctor_build import package_inventory,PackageError
@pytest.mark.parametrize('version,accepted',[('1.0.21',True),('1.0.22',False)])
def test_new_screening_resources_required_only_for_22(tmp_path,version,accepted):
    root=minimal_package(tmp_path)
    (root/'RELEASE.json').write_text(json.dumps({'packaging_version':version,'source_id':'M01'}))
    for name in ['screening-refinement-compatibility.json','screening-parent-engines.json']:
        (root/'_internal'/name).unlink()
    if accepted:assert package_inventory(root)
    else:
        with pytest.raises(PackageError,match='software allowlist'):package_inventory(root)
