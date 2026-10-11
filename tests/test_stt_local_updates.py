from pathlib import Path
import subprocess


def test_stt_local_refresh_output_and_request_lifecycle():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "tests/browser_stt_local_updates.cjs"], cwd=root,
        check=True, capture_output=True, text=True, timeout=20,
    )
    assert "ST local updates: equivalent raw output" in result.stdout


def test_stt_production_trend_navigation_is_exact_and_keeps_window():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "tests/browser_stt_layout_navigation.cjs"], cwd=root,
        check=True, capture_output=True, text=True, timeout=20,
    )
    assert "ST production trend navigation: exact ±16s" in result.stdout
