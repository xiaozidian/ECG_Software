#!/usr/bin/env python3
"""Explicit, masked, loopback-only review of existing local hospital sources."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import sys


def create_review_app(data_root: Path, workspace: Path, *, purpose: str = 'user_review',
                      db_path: Path | None = None, source_kind: str = 'hospital_real',
                      release_id: str = ''):
    from app import create_app
    from flask import jsonify, request

    workspace = workspace.resolve()
    data_root = data_root.resolve()
    if workspace == data_root or data_root in workspace.parents or workspace in data_root.parents:
        raise ValueError('原始数据与复核工作区必须是互不包含的独立目录。')
    if not data_root.is_dir():
        raise ValueError('指定的真实数据目录不可用；未回退到其他目录。')
    workspace.mkdir(parents=True, exist_ok=True)
    database = Path(db_path).resolve() if db_path is not None else workspace / 'work.sqlite3'
    if database != workspace / 'work.sqlite3' and workspace not in database.parents:
        raise ValueError('工作数据库必须位于独立复核工作区内。')
    if source_kind not in ('hospital_real', 'mathematical_synthetic'):
        raise ValueError('请明确选择本机真实来源或数学合成来源。')
    app = create_app(data_root=data_root, db_path=database)
    if app.config['ALLOW_PHI']:
        raise ValueError('此入口要求 ECG_ALLOW_PHI=0；未开放身份信息。')
    source_ids = [p.name for p in sorted(data_root.iterdir()) if p.is_dir() and re.fullmatch(r'\d{16}', p.name)]
    alias_path = workspace / 'case-display-ids.json'
    aliases = json.loads(alias_path.read_text()) if alias_path.exists() else {}
    previous_aliases = {}
    if release_id:
        # The saved-work backup already includes audit_log. Keep the presentation
        # map in that database so offline recovery preserves Cxx labels without
        # weakening the existing two-member backup archive contract.
        from contextlib import closing
        with closing(app.extensions['storage'].connect()) as connection:
            row = connection.execute("SELECT detail FROM audit_log WHERE action='workspace.case_display_ids' ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            previous_aliases = json.loads(row[0])
            if not isinstance(previous_aliases, dict):
                raise ValueError('已保存病例显示编号异常；请保留工作区并检查。')
        if not aliases:
            aliases = dict(previous_aliases)
    used = set(aliases.values())
    for source_id in source_ids:
        if source_id not in aliases:
            number = 1
            while f'C{number:02d}' in used:
                number += 1
            aliases[source_id] = f'C{number:02d}'
            used.add(aliases[source_id])
    if len(set(aliases.values())) != len(aliases) or any(not re.fullmatch(r'C\d{2,}', value) for value in aliases.values()):
        raise ValueError('本地病例显示编号异常；请保留工作区并检查。')
    alias_path.write_text(json.dumps(aliases, ensure_ascii=False, indent=2) + '\n')
    if release_id and aliases != previous_aliases:
        app.extensions['storage'].audit('本机评估配置', 'workspace.case_display_ids',
                                        detail=json.dumps(aliases, ensure_ascii=False, sort_keys=True))
    app.config['REPORT_CASE_DISPLAY_IDS'] = dict(aliases)
    purpose_label = {'user_review': '用户复核工作区', 'doctor_evaluation': '医生功能评估工作区'}.get(purpose, '隔离工程测试工作区')
    source_label = '数学合成演示' if source_kind == 'mathematical_synthetic' else '原始真实记录'
    title = f"{'数学合成演示' if source_kind == 'mathematical_synthetic' else '本机真实病例复核'} · {purpose_label}"

    def present(value):
        if isinstance(value, list):
            return [present(child) for child in value]
        if not isinstance(value, dict):
            return value
        item = {key: present(child) for key, child in value.items()}
        if item.get('case_id') in aliases:
            item['display_case_id'] = aliases[item['case_id']]
        if isinstance(item.get('metadata'), dict):
            for key in ('name', 'patient_id', 'requesting_physician', 'requesting_doctor'):
                if key in item['metadata']:
                    item['metadata'][key] = '已遮蔽'
        return item

    @app.get('/api/local-review-context')
    def local_review_context():
        return jsonify(source_kind=source_kind, local_only=True, phi_visible=False,
                       source_files_readonly=True, workspace_purpose=purpose,
                       release_id=release_id, database_path=str(database),
                       case_labels=sorted(aliases[source_id] for source_id in source_ids),
                       case_count=len(source_ids),
                       input_assumptions='200 Hz / 8 存储通道 / 12 展示导联为现有导入口径，待独立设备资料核验；电压未标定。')

    @app.after_request
    def local_presentation(response):
        if response.is_json:
            value = response.get_json(silent=True)
            if value is not None:
                response.set_data(app.json.dumps(present(value)))
        elif request.path == '/' and response.status_code == 200:
            body = response.get_data(as_text=True)
            body = re.sub(r'<title>.*?</title>', f'<title>{html.escape(title)}</title>', body, count=1)
            body = body.replace('<html ', f'<html data-local-review="real" data-workspace-purpose="{purpose}" ', 1)
            body = body.replace('演示分析医生', html.escape(purpose_label))
            body = body.replace('<p id="settingsDataRoot">正在读取…</p>', '<p id="settingsDataRoot">正在读取…</p><p id="localSourceBoundary">200 Hz、8 存储通道与 12 展示导联是现有导入口径，设备采样率及通道映射待独立核验；电压为设备单位 u，增益和零点未校准。源文件只读，工作记录保存在本页所示独立工作区。</p>')
            body = body.replace('当前导入格式：200 Hz / 8 通道', '导入口径：200 Hz / 8 存储通道 → 12 展示导联（待独立核验）')
            body = body.replace('10 例仅用于功能回归', f'{source_label} · 独立复核')
            body = body.replace('不能据此声明灵敏度、特异度、临床有效性或符合医疗器械注册要求。',
                                '源波形只读；操作和草稿保存在独立工作区。电压未校准，设备采样率、通道映射、增益和零点仍待独立资料核验。')
            body = body.replace('自动结果均为候选提示，',
                                f'{source_label} · 身份已遮蔽 · 原文件只读 · {html.escape(purpose_label)}。仅供医生功能评估；无医生金标准，不能据此作为正式诊断放行。自动结果均为候选提示，', 1)
            response.set_data(body)
        return response

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--purpose', choices=['user_review', 'isolated_verification'], default='user_review')
    args = parser.parse_args()
    os.environ.update(ECG_ALLOW_PHI='0', ECG_APP_DATA_ROOT=str(args.workspace.resolve()),
                      ECG_DATA_ROOT=str(args.data_root.resolve()))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from waitress import serve
    app = create_review_app(args.data_root, args.workspace, purpose=args.purpose)
    print(json.dumps({'ready_to_bind': True, 'port': args.port, 'source_kind': 'hospital_real',
                      'workspace_purpose': args.purpose, 'allow_phi': False}), flush=True)
    serve(app, host='127.0.0.1', port=args.port, threads=4, channel_timeout=120)


if __name__ == '__main__':
    main()
