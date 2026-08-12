"""Build the browser-only synthetic GitHub Pages demo."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "build" / "pages"


def build(output: Path) -> Path:
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    environment = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
    )
    environment.globals["url_for"] = lambda endpoint, filename: f"static/{filename}"
    html = environment.get_template("index.html").render(
        app_name="CardioInsight Holter｜模拟数据在线演示",
        app_version="0.12.0-static-demo",
        app_version_short="0.12.0-demo",
        demo_readonly=True,
        allow_phi=False,
    )
    replacements = {
        '<meta name="description" content="本机运行的 Holter 心电分析研究工作站；病例数据默认脱敏且不上传。">': '<meta name="description" content="CardioInsight Holter 模拟数据在线交互演示；含一例用户确认模拟源片段，不含真实患者数据。">',
        "正在建立本地病例索引…": "正在加载公开模拟病例…",
        "演示分析医生": "合成演示访客",
        "本地工作站": "GitHub Pages · 纯前端",
        "<strong>研究与软件验证用途</strong>": "<strong>模拟数据在线演示</strong>",
        "自动结果均为候选提示，必须由专业人员回看原始波形；本软件不用于临床诊断、报警或治疗决策。": "含 1 例用户确认的模拟病例源波形片段和 9 例公式病例；不含真实患者数据，仅用于交互展示。",
        "10 例本地数据已建立只读索引，源波形不会被修改。": "第 5 例直接读取已公开的模拟 DATA 片段，其余病例由浏览器生成；不含真实患者数据。",
        "本地可用病例": "公开模拟病例",
        "小时 Holter 数据": "模拟波形时长",
        "源报告统计": "模拟数据统计",
        "原报告影像": "合成演示说明",
        "导出 PDF": "下载演示说明",
        '<button class="active" data-event-type="all">全部</button>': '<button class="active" data-event-type="all">全部</button><button data-event-type="AF">房颤样候选</button>',
    }
    for source, target in replacements.items():
        html = html.replace(source, target)
    app_script = '<script src="static/js/app.js"></script>'
    if app_script not in html:
        raise RuntimeError("application script tag not found")
    html = html.replace(
        app_script,
        '<script src="static/demo-data/uploaded-sim-af-001/case-data.js"></script>\n  '
        '<script src="static/js/demo-api.js"></script>\n  '
        + app_script,
    )
    if "{{" in html or "{%" in html:
        raise RuntimeError("unrendered Jinja markup remains")
    html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
    (output / "index.html").write_text(html, encoding="utf-8")
    shutil.copytree(PROJECT_ROOT / "static", output / "static")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    (output / "_headers").write_text(
        """/*
  Content-Security-Policy: default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data: blob:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'
  Permissions-Policy: camera=(), geolocation=(), microphone=()
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
""",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(f"Static synthetic demo built at {build(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
