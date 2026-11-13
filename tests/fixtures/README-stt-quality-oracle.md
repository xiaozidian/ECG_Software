# Frozen candidate-quality numerical oracle

`stt_candidate_quality_6e37_oracle.py` is a byte-for-byte copy of the reviewed helper before the proposed performance changes. SHA256:

`6e37ccddfcf5fee152ac2c419d3870af3c3ad0c94565d038157a1385d51a8868`

The numerical regression test verifies this hash and loads it from this relative fixture path in a separate module namespace. It does not depend on any developer workstation path, external dataset, work database, or the original project directory. The shared package config supplies only the unchanged 200 Hz / 8 source-channel acquisition constants, which the test also checks.

This fixture is a software-equivalence reference, not a clinical gold standard. Keep the independent waveform-shape and full-engine tests. A mismatch must be investigated rather than resolved by updating the fixture or weakening comparisons without a separately reviewed semantic change.
