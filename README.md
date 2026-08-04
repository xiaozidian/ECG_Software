# CardioInsight Holter 心电分析工作站

CardioInsight Holter 是一个在本机运行的动态心电研究与软件验证工作站，同时支持 **macOS** 和 **Windows**。程序会按当前系统选择原生用户数据目录、界面字体、显示优化和搜索快捷键；服务默认只监听 `127.0.0.1`，病例文件只读访问，身份信息默认遮蔽。

> 本项目仅用于研究、教学和软件功能验证，不用于独立临床诊断、报警、分诊或治疗决策。自动分类、事件和统计均为待专业人员复核的候选结果。

## 选择运行系统

| 系统 | 支持版本 | 双击启动 | 用户配置 | 打包产物 |
|---|---|---|---|---|
| macOS | macOS 12+，Apple Silicon / Intel | `启动心电分析软件.command` | `~/Library/Application Support/CardioInsightHolter/config.json` | `dist/CardioInsightHolter.app` |
| Windows | Windows 10/11 64 位 | `启动心电分析软件.cmd` | `%LOCALAPPDATA%\CardioInsightHolter\config.json` | `dist\CardioInsightHolter\CardioInsightHolter.exe` |

两个系统均要求 Python 3.11 或更高版本。首次启动会自动创建项目内 `.venv`、安装运行依赖并生成本机配置文件。

### macOS

双击 `启动心电分析软件.command`，或在终端执行：

```zsh
./scripts/setup_macos.sh
./启动心电分析软件.command
```

### Windows

双击 `启动心电分析软件.cmd`。它会自动调用 PowerShell 安装环境并启动程序，也可以手动执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
.\启动心电分析软件.cmd
```

软件通常会自动打开 `http://127.0.0.1:8765`；端口占用时会选择后续可用端口。

## 连接病例数据

首次运行后，编辑当前系统对应的 `config.json`，把 `data_root` 设为 `10个病人的心电数据` 目录的绝对路径：

macOS 示例：

```json
{
  "data_root": "/Users/your-name/Documents/ECG/10个病人的心电数据",
  "privacy_mode": "masked_by_default",
  "listen_host": "127.0.0.1",
  "listen_port": 8765
}
```

Windows 示例：

```json
{
  "data_root": "C:/Users/your-name/Documents/ECG/10个病人的心电数据",
  "privacy_mode": "masked_by_default",
  "listen_host": "127.0.0.1",
  "listen_port": 8765
}
```

也可临时使用环境变量 `ECG_DATA_ROOT`，或启动参数 `--data-root`。为防止误暴露健康数据，绑定非回环地址时必须显式增加 `--allow-remote`。

本地标注、报告版本、审计数据库和导出的 PDF 存放在系统原生用户数据目录，不写入签名后的 `.app` 或 `.exe` 目录。

## 构建桌面应用

必须在目标系统上构建目标产物。

macOS：

```zsh
./scripts/build_macos.sh
open dist/CardioInsightHolter.app
```

Windows：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
.\dist\CardioInsightHolter\CardioInsightHolter.exe
```

macOS 脚本会执行 ad-hoc 签名并严格校验，适合本机验证；正式分发前需要 Developer ID 签名和 notarization。Windows 构建会生成 64 位 `.exe` 目录；正式分发前需要受信任证书的 Authenticode 签名。

GitHub Actions 的 `desktop-builds.yml` 会在 macOS 与 Windows runner 上分别构建可下载压缩包，避免在单一系统上交叉打包。

## 已实现

- 病例工作台、检索、逻辑停用/恢复和患者资料本地覆写。
- 默认隐私遮蔽；查看可识别信息需要当前浏览器会话明确授权。
- 约 23 小时长记录的窗口化读取，不一次性载入完整波形。
- 8 路原始通道及推导 12 导联、3/6/12 导联布局、增益、时间窗和显示滤波。
- EBI 搏动分类、心率摘要、分钟趋势、RR 直方图、Poincaré 图与 HRV 时域指标。
- 心动过缓、心动过速、长 RR、室上性和室性候选事件筛选。
- 人工标注、审计日志、报告草稿/复核状态、版本记录与中文 PDF 导出。
- macOS Retina / Windows HiDPI、系统字体、`⌘ K` / `Ctrl K`、缩放窗口布局和减少动态效果偏好。

## 隐私与仓库边界

仓库不包含原始病例、报告影像、本地 SQLite、完整性清单、导出报告、虚拟环境或应用构建产物。`config.json` 也被忽略，避免把本机病例路径提交到版本控制。

如果需要验证原始数据完整性，请在受控环境中运行 `scripts/build_case_manifest.py`；生成的 `data/case_manifest.json` 只保留在本机。

## 测试

macOS / Linux shell：

```zsh
ECG_DATA_ROOT="/absolute/path/to/10个病人的心电数据" ./.venv/bin/python -m pytest -q
node --check ./static/js/app.js
```

Windows PowerShell：

```powershell
$env:ECG_DATA_ROOT = "C:\absolute\path\to\10个病人的心电数据"
.\.venv\Scripts\python.exe -m pytest -q
node --check .\static\js\app.js
```

不含病例数据的 GitHub Actions 会在 macOS 与 Windows 上运行平台路径测试、Python 编译检查、JavaScript 语法检查和对应平台启动脚本检查。

## 目录

- `app.py`：本机应用入口与 API。
- `ecg_core/`：数据解析、波形、事件、存储、平台路径和报告核心。
- `templates/`、`static/`：根据系统动态适配的工作站界面。
- `tests/`：自动化验证。
- `docs/`：需求追踪、数据格式、测试和合规边界。
- `scripts/`：macOS / Windows 环境、打包和完整性工具。

## 当前边界

本版本未实现经临床验证的房颤/ST/QT/起搏器诊断算法、多人登录与完整 RBAC、HIS/PACS/DICOM/HL7 接口、可验证数字签名、PDF/A 或医疗器械注册所需的软件生命周期与风险管理体系。详见 `docs/需求追踪矩阵.md` 和 `docs/临床与合规边界.md`。
