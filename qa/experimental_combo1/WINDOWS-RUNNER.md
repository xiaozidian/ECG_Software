# Portable combo1 source-only diagnostic

Experimental in-memory monkeypatch only; NOT runtime-identity verification,
NOT native PE acceptance, and NOT a deployable release. No production source,
threshold, measurement helper, algorithm version or request timeout is edited.
Only the fixed verified wholly mathematical M01-24h-v1 dataset is accepted.

Keep these four files together:

- run_combo_comparison.py
- profile_combo.py
- stt_flags_trial.py
- quality_layout_trial.py

Use the existing pinned Python 3.12.10 / NumPy 2.2.6 environment on Windows:

    & $PinnedPython -B .\run_combo_comparison.py --source $FrozenProject --math-root $VerifiedM01 --out $FreshArtifactDirectory --require-windows-pinned

Source must still contain original STT SHA 87053181... and quality SHA6e37ccdd...
(native app/storage fixes may differ). Output must be a fresh directory outside
source and M01 input. The script runs baseline then combo in separate child
processes using the same sys.executable. Each child verifies M01 source bytes,
opens a temporary empty mathematical work DB, opens the case header/basis,
and times complete cold and warm GET /stt-review through Flask's test client.
It does not connect to a native server, change a controller, or access real cases.

Outputs: baseline-1/result.json and combo-1/result.json, gzipped full cold bodies,
stdout logs, stacks sampled every30s, and portable-comparison.json. Full raw
HTTP body must be byte-identical: no scope deletion, relabelling, tolerance, or
field exemptions. Source Python and experimental module hashes must be unchanged.
The result includes wall/CPU, helper call counts, body SHA and environment.

The script reports timing without imposing a new acceptance threshold or changing
any product timeout. Only the release owner can decide whether to continue to
actual Windows PE three-round cold-read acceptance and broader equivalence tests.

A quick comparison-only mode for already completed outputs is available:

    & $PinnedPython -B .\run_combo_comparison.py --source $FrozenProject --math-root $VerifiedM01 --out $ExistingArtifactDirectory --require-windows-pinned --verify-existing

Combo1 fixed module hashes:

stt_flags_trial.py
c475c00420199d7259d27901546cef65fb9003e132623376a879b21af3db89f8

quality_layout_trial.py
d5b3c2a988480f5c84230b87b4eb6d89bb93b773c63347a39f73f1e408776c66
