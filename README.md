# CardioInsight Holter

本仓库保存本机 ECG 软件源码及独立的浏览器交互 Demo。软件用于研究和工程验证，自动事件均为待医生复核的候选；本次发布不构成临床验收。

当前冻结来源为 `0.12.11-doctor-evaluation.20261011+805637aa415a176f`，94 个生产输入的完整指纹为 `805637aa415a176feb25afca77b740bb3266541e31433107cdfa047a5c519e6a`。文件清单与验证方式见 [版本说明](docs/releases/0.12.11-doctor-evaluation.20261011/README.md) 和 [来源清单](docs/releases/0.12.11-doctor-evaluation.20261011/source-manifest.json)。本机十病例入口已切换至本指纹；切换前完成备份，重启后所有数据库表值、299 个只读源文件和配置核对一致。线上同步以同一提交的 Pages 验证为准。

## 本次交互更新

- 总览四趋势竖排、每搏 HR/RR 单位、散点点选/框选/圈选及取消操作；三导联设置保留明确入口。
- 编辑页散点图增高；类型剥离区减少常驻说明与统计，完整来源保留在详情。密度分布和模板库双界面保留；普通单击选择并放大当前波形，明确的全屏入口与返回操作保留上下文。
- ST 支持局部 1–12 导联选择，取消与应用独立，保留测量游标和医生草稿。
- 报告操作与事件分类分开；左侧保留紧凑勾选；当前候选入报后定位下一条，默认 12 导联与 15 秒上下文，导联来源及设备单位按原数据标记。拖动选区须明确应用，待应用与已应用范围分别显示，未处理修改阻止保存及输出请求。
- 编排保留计数、筛选、图条、结论和逐小时统计矩阵；保存、确认、冲突、修订及旧响应失效保护继续保留。
- HRV 连续内容先显示，同一时段可切换时域/频域；全记录N-N参考与已有NN纳入范围设置可直接打开，折叠的 A4/PDF 入口位于最后。
- 修复总览插入图条的STRIP类型校验缺漏；既有入报范围、确认及审核失效保护保持原规则。

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

本指纹完整本地回归为 1810 项通过、0 失败、0 错误、0 跳过，包含 27 项新增保护回归。最终数学 Demo 在 Mac Chrome 中通过 16 项流程和 16 组尺寸检查，200 次 API 请求无 400 及以上响应；同一编译二进制的两个独立临时工作库通过 31 项总览入报、取消、保存重开及跨病例保护检查。GitHub Actions 运行范围与本地完整回归分别记录。

原十病例入口的新版 Mac Chrome 只读验收通过 48 项检查：10 个病例均实际打开，模板双界面、ST 与报告返回、NN 设置取消、HRV 表格逐格核对及末尾 A4 入口通过；API、脚本错误和医生编辑写入均为 0。升级前保存内容和原历史经严格保护审计保持等价。由于软件来源指纹更新，10 病例的已有确认按原规则失效，需重新复核；这不表示临床诊断验收，也不沿用旧版原生 PDF 成绩。

核心合成验证的范围与容差见 [核心验证说明](docs/core-verification.md)。GitHub Actions 成绩以对应提交实际 workflow 为准，本地执行不能冒充 Actions。数学 Demo 的浏览器 A4 打印与本机后端 PDF 为不同实现；600 秒数学输入不能证明真实全天病例、设备校准或临床表现。

界面参考已核对不代表完整 1:1 对齐。HRV 已有全记录、日夜和小时指标以只读对照表展示；全记录 N-N 参考及既有 NN 范围设置可直接进入。完整 RR 分类与搏跳联动、医院五分钟块编辑和完整 HRV 参数模型仍缺少接口；报告的完整医生核准术语树也未实现。HRT 缺少合格源事件时没有可验证的事件时间跳转；QT 未知值保持未知。

公开版本不包含病例、数据库及 WAL/SHM、身份映射、医院素材、真实报告、私有截图或未经核查的二进制。诊断规则、阈值、单位与原波形输入未为布局调整改变。本轮不作未经同源实测支持的冷暖提速声明。
