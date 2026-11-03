"""The actual eager binding list must not stop startup after a page redesign."""
from pathlib import Path
import re


def test_eager_static_id_bindings_have_real_template_targets():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'templates/index.html').read_text()
    source = (root / 'static/js/app.js').read_text()
    identifiers = set(re.findall(r'''id=["']([^"']+)''', template))
    bindings = re.findall(r'''\$\(["']#([^"']+)["']\)\.addEventListener''', source)
    assert bindings, "The real startup binding list must be inspected"
    assert sorted(set(bindings) - identifiers) == []
