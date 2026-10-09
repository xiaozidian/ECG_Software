# CardioInsight Holter

本仓库保存本机 ECG 软件源码及独立的浏览器交互 Demo。软件用于研究和工程验证，自动事件均为待医生复核的候选；本次发布不构成临床验收。

当前保存的评估版为 `0.12.9-doctor-evaluation.20261009+4314c977f468868f`。其 94 个生产文件与本机封存版本逐字节一致，完整指纹为 `4314c977f468868fdd72128028f311ad27314aedef8a8a38d904af933e2750b4`。文件清单与验证方式见 [版本说明](docs/releases/0.12.9-doctor-evaluation.20261009/README.md) 和 [来源清单](docs/releases/0.12.9-doctor-evaluation.20261009/source-manifest.json)。

## 本次交互更新

- 模板卡压缩重复文字、原位扩大波形；完整来源放在详情。密度分布和模板库双界面保留，单击立即选择，F 放大、Esc 返回。
- ST 导联及报告类别局部更新，保留有效计数、布局、人工输入和未应用区间；取消、修订和选择变化会使过期请求失效。
- 报告操作与事件分类导航分开，待应用区间及已应用区间明确显示；未处理的区间修改继续阻止保存和导出。
- HRV 网页连续展示，A4/PDF 预览放在最后。
- 保存、复核、报告依据、冲突及恢复失效保护保留。

## 在线 Demo

现有展示地址：[GitHub Pages](https://xiaozidian.github.io/ECG_Software/)。`.github/workflows/pages.yml` 在 `main` 更新时构建并发布。

此次 Demo 只使用仓库中的数学函数、固定种子和明确的人工标签生成一个 600 秒、200 Hz、8 存储通道的输入。它不读取本机病例、工作库、来源报告或旧演示载荷。十二导联由数学输入派生；波形单位和设备校准未经过独立硬件验证。旧演示数据目录不会复制到新的发布产物。

Demo 复用本评估版界面，静态适配器只在浏览器自己的版本命名空间保存演示修改。它不提供 Python 诊断后端、真实病例保存、医生审核认证、桌面工作库迁移或原生备份恢复。浏览器打印与本机后端生成 PDF 是不同的实现，不能互相替代验收。

```sh
python -m pip install 'Jinja2>=3.1,<4'
python scripts/build_static_demo.py
python -m http.server 4173 --bind 127.0.0.1 --directory build/pages
```

访问 `http://127.0.0.1:4173/`。`build/pages/` 是部署产物，[本版 Demo 快照](docs/demo/0.12.9-doctor-evaluation.20261009/index.html) 保存同一构建。版本目录与既有历史快照隔离；公开 Pages workflow 仅上传新构建目录。修改应落在 Demo 适配器或构建器，然后重建，不手改生成文件。

## 本机源码运行

安装 Python 3.12 与 `requirements.txt`，先生成独立数学输入并明确选择来源：

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/generate_synthetic_demo.py --output ./demo_data --cases 1 --duration-minutes 10
ECG_ALLOW_PHI=0 ECG_APP_DATA_ROOT=./local-math-workspace python app.py --data-root ./demo_data --host 127.0.0.1 --port 8765 --no-browser
```

Windows 使用 `.venv\Scripts\Activate.ps1`，并在启动前设置对应环境变量。未显式指定数据目录的普通源码入口可能搜索传统本地目录，且身份显示默认设置与隔离数学演示不同；因此示例始终指定数学来源和关闭身份显示。生产源码的运行契约没有为此次 GitHub 同步而改写。

`mac_release.py` 及 Mac `.command` 入口用于独立评估包；其中 `.command` 需要另行构建的 `.app`，不会仅凭源码仓库产生已验收的二进制。此次 `main` 源码与 Demo 同步跳过桌面二进制构建；现有桌面 workflow 仅在手动运行或 `v` 标签时构建。其产物是新构建结果，不能冒充此前本机封存的软件包。

## 验证及公开范围

本机此前同条件完整回归为 1765 项：基线 1741 通过、24 失败，评估版 1746 通过、19 失败，0 错误、0 跳过。五项 VM 依赖装载问题已修复，失败场景集合无新增。剩余 14 项来源不可用，另 5 项固定病例数量、趋势时长或分组假定未满足；失败后的断言未执行，不能称全绿。三尺寸本机医生流程的 95 项限定检查和实际 PDF 审计不构成临床有效性证据。

公开 CI 使用独立数学输入及源码、Demo 构建检查，不读取本机病例或复制私有回归日志。此仓库发布不带本机数据库、WAL/SHM、配置、身份映射、医院截图、病例报告或未经核查的软件包。历史既有演示素材未在本次重新上传或重新发布，其来源不在此次确认范围内。

本机四病例评估工作区与浏览器数学 Demo 相互隔离；本次同步不会迁移或覆盖医生已保存工作。ST 可测块及候选结果在本次修复后可能改变，使用新版结果须重新复核相应依据。没有可靠的新全流程冷暖提速结论。
