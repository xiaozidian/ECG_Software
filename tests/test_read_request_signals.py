import subprocess


def test_read_request_consumer_abort_and_real_api_adapter():
    subprocess.run(['node', 'tests/browser_read_request_signals.cjs'], check=True, timeout=15)
