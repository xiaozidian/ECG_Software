# CardioInsight Holter

本仓库保存本机 ECG 软件源码及独立的浏览器交互 Demo。软件用于研究和工程验证，自动事件均为待医生复核的候选；本次发布不构成临床验收。

当前冻结来源为 `0.12.11-doctor-evaluation.20261011+54aaab615de4bfae`，94 个生产输入的完整指纹为 `54aaab615de4bfae9745804c6f5dfbedcd45d4203cc0d50f59609fc9f3f68915`。文件清单与验证方式见 [版本说明](docs/releases/0.12.11-doctor-evaluation.20261011/README.md) 和 [来源清单](docs/releases/0.12.11-doctor-evaluation.20261011/source-manifest.json)。安装版状态：新安装版单次 111 场景通过，覆盖十病例、8 个入口；独立补验 126 项滚动与控件可达性通过。原病例与医生工作区的保留和迁移范围以本轮实际验收为准。

## 本次交互更新

- 总览四趋势竖排、每搏 HR/RR 单位、散点点选/框选/圈选及取消操作；三导联设置保留明确入口。
- 编辑页散点图增高；类型剥离区减少常驻说明与统计，完整来源保留在详情。密度分布和模板库双界面保留；普通单击选择并放大当前波形，明确的全屏入口与返回操作保留上下文。
- ST 支持局部 1–12 导联选择，取消与应用独立，保留测量游标和医生草稿。
- 报告操作与事件分类分开；左侧保留紧凑勾选；当前候选入报后定位下一条，默认 12 导联与 15 秒上下文，导联来源及设备单位按原数据标记。拖动选区须明确应用，待应用与已应用范围分别显示，未处理修改阻止保存及输出请求。
- 编排保留计数、筛选、图条、结论和逐小时统计矩阵；保存、确认、冲突、修订及旧响应失效保护继续保留。
- HRV 连续内容先显示，同一时段可切换时域/频域；折叠的 A4/PDF 入口位于最后。

## 在线 Demo

现有展示地址：[GitHub Pages](https://xiaozidian.github.io/ECG_Software/)。`.github/workflows/pages.yml` 在 `main` 更新时构建并发布。

此次 Demo 只使用仓库中的数学函数、固定种子和明确的人工标签生成一个 600 秒、200 Hz、8 存储通道的输入。它不读取本机病例、工作库、来源报告或旧演示载荷。十二导联由数学输入派生；波形单位和设备校准未经过独立硬件验证。旧演示数据目录不会复制到新的发布产物。

Demo 复用本评估版界面，静态适配器只在浏览器自己的版本命名空间保存演示修改。它不提供 Python 诊断后端、真实病例保存、医生审核认证、桌面工作库迁移或原生备份恢复。浏览器打印与本机后端生成 PDF 是不同的实现，不能互相替代验收。

```sh
python -m pip install 'Jinja2>=3.1,<4'
python scripts/build_static_demo.py
python -m http.server 4173 --bind 127.0.0.1 --directory build/pages
```

访问 `http://127.0.0.1:4173/`。`build/pages/` 是部署产物，[本版 Demo 快照](docs/demo/0.12.11-doctor-evaluation.20261011/index.html) 保存同一构建。版本目录与既有历史快照隔离；公开 Pages workflow 仅上传新构建目录。修改应落在 Demo 适配器或构建器，然后重建，不手改生成文件。

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

`mac_release.py` 及 Mac `.command` 入口用于独立评估包；其中 `.command` 需要另行构建的 `.app`，不会仅凭源码仓库产生已验收的二进制。桌面 workflow 仅在手动运行或 `v` 标签时构建。仓库构建能力与本轮安装版验收结果分别记录，源码不能替代已安装程序的实际验收。

## 本轮验证及公开范围

以下成绩仅属于 `0.12.11-doctor-evaluation.20261011+54aaab615de4bfae`；历史版本和旧阶段结果不计入本轮。

- 冻结源完整回归：1783 项单次全量通过，失败、错误及跳过均为 0。
- 冻结源候选浏览器：隔离候选的 7 组流程分阶段完成，106 项业务检查与 12 项几何检查通过；不是一次不中断运行。
- 安装版原生验收：新安装版单次 111 场景通过，覆盖十病例、8 个入口；独立补验 126 项滚动与控件可达性通过。
- 数学 Demo 浏览器：最终单次 14 组交互与 16 项四尺寸几何检查通过；报告 3 页、HRV 新打印文档 2 页。
- 公开核心合成验证：本地纯数学和临时合成验证 20 项通过；对应提交的 Actions 成绩另行核对。

核心合成验证的范围与容差见 [核心验证说明](docs/core-verification.md)。GitHub Actions 成绩以对应提交实际 workflow 为准，本地执行不能冒充 Actions。数学 Demo 的浏览器 A4 打印与本机后端 PDF 为不同实现；600 秒数学输入不能证明真实全天病例、设备校准或临床表现。

界面参考已核对不代表完整 1:1 对齐。HRV 时段列表、频域分段和完整设置对话框仍有差异；HRT 缺少合格源事件时没有可验证的事件时间跳转；QT 未知值保持未知，分布界面未完全复刻。

公开版本不包含病例、数据库及 WAL/SHM、身份映射、医院素材、真实报告、私有截图或未经核查的二进制。诊断规则、阈值、单位与原波形输入未为布局调整改变。本轮不作未经同源实测支持的冷暖提速声明。
