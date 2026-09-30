#!/usr/bin/env python3
"""Offline/local saved-work backup utility. No live-database replacement."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecg_core.config import user_data_root
from ecg_core.workspace_backup import BackupError, create_backup, verify_backup, restore_backup


def main(argv=None):
    parser = argparse.ArgumentParser(description='本机已保存工作备份；不含原始 ECG、未保存修改或 PDF，不加密')
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create', help='创建并校验备份，不修改工作数据库')
    create.add_argument('--db', type=Path, default=user_data_root() / 'data' / 'cardioinsight.db')
    create.add_argument('--destination', type=Path, required=True, help='私有本地备份目录')
    verify = sub.add_parser('verify', help='检查备份摘要、数据库完整性和字段格式')
    verify.add_argument('archive', type=Path)
    restore = sub.add_parser('restore', help='恢复至新应用数据目录，所有报告重新复核')
    restore.add_argument('archive', type=Path)
    restore.add_argument('--new-app-data-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            result = create_backup(args.db, args.destination)
        elif args.command == 'verify':
            result = verify_backup(args.archive)
        else:
            result = restore_backup(args.archive, args.new_app_data_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BackupError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
