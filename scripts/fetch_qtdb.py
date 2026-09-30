#!/usr/bin/env python3
"""Fetch only the public QTDB files used by validate_qtdb.py, with SHA checks.

No local ECG is transmitted. Dataset license and citation are recorded in
docs/qtdb-validation-protocol.md. Uses requests from validation-only WFDB env.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
import re
import requests

ORIGIN = 'https://physionet.org/files/qtdb/1.0.0/'


def fetch(folder):
    folder.mkdir(parents=True, exist_ok=True)
    def get(name, digest=None):
        target = folder/name
        if target.exists() and digest and sha256(target.read_bytes()).hexdigest() == digest:
            return
        error = None
        for _ in range(3):
            try:
                response = requests.get(ORIGIN+name, timeout=(15, 60))
                response.raise_for_status()
                content = response.content
                if digest and sha256(content).hexdigest() != digest:
                    raise ValueError(f'SHA256 mismatch for {name}')
                temporary = target.with_name(target.name+'.part')
                temporary.write_bytes(content)
                temporary.replace(target)
                return
            except (requests.RequestException, ValueError) as exc:
                error = exc
        raise error
    get('SHA256SUMS.txt')
    sums = {}
    for line in (folder/'SHA256SUMS.txt').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        sums[name.removeprefix('*').removeprefix('./')] = digest
    get('RECORDS', sums['RECORDS'])
    records = (folder/'RECORDS').read_text().split()
    if len(records) != 105 or any(not re.fullmatch(r'sel\w+', r) for r in records):
        raise ValueError('Unexpected QTDB record list')
    names = [f'{r}.{ext}' for r in records for ext in ('hea', 'dat', 'q1c', 'q2c')
             if f'{r}.{ext}' in sums]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(get, name, sums[name]) for name in names]
        for i, result in enumerate(as_completed(jobs), 1):
            result.result()
            if i % 20 == 0 or i == len(names):
                print(f'{i}/{len(names)} checked public files', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    fetch(p.parse_args().output)
