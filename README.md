# CardioInsight Holter 心电分析工作站

CardioInsight Holter 是一个在本机运行的动态心电研究与软件验证工作站，同时支持 **macOS** 和 **Windows**。源码运行时使用项目根目录的本机 `config.json`；程序会按当前系统选择原生数据存储目录、界面字体、显示优化和搜索快捷键。服务默认只监听 `127.0.0.1`，病例文件只读访问，身份信息默认遮蔽。

> 本项目仅用于研究、教学和软件功能验证，不用于独立临床诊断、报警、分诊或治疗决策。自动分类、事件和统计均为待专业人员复核的候选结果。

## 选择运行系统

| 系统 | 支持版本 | 双击启动 | 源码配置 | 本地数据目录 | 打包产物 |
|---|---|---|---|---|---|
| macOS | macOS 12+，Apple Silicon / Intel | `启动心电分析软件.command` | `项目根目录/config.json` | `~/Library/Application Support/CardioInsightHolter/` | `dist/CardioInsightHolter.app` |
| Windows | Windows 10/11 64 位 | `启动心电分析软件.cmd` | `项目根目录\config.json` | `%LOCALAPPDATA%\CardioInsightHolter\` | `dist\CardioInsightHolter\CardioInsightHolter.exe` |

两个系统均要求 Python 3.11 或更高版本。首次启动会自动创建项目内 `.venv`、安装运行依赖，并把 `config.example.json` 复制为项目根目录的 `config.json`。

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

首次运行后，编辑项目根目录的 `config.json`，把 `data_root` 设为 `10个病人的心电数据` 目录的绝对路径。源码运行时会优先读取该文件。

> `config.json` 只保留在本机。仓库已通过 `.gitignore` 忽略它，不会被正常的 Git 提交或推送上传；仓库仅保留不含本机路径的 `config.example.json`。

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

## 在其他设备打开：容器与云部署

### GitHub Pages 在线演示

原始完整应用需要 Python/Flask 服务、病例目录和可写的应用数据目录，不能直接在只支持静态文件的 GitHub Pages 上运行。仓库因此提供了一个独立的浏览器演示模式：它按固定公式生成 10 例完全虚构的病例、波形和统计结果，不读取、不上传、也不包含任何本地患者文件。

- 正式演示地址（仓库管理员启用 Pages 后生效）：<https://xiaozidian.github.io/ECG_Software/>
- `scripts/build_static_demo.py` 生成 Pages 发布包；`.github/workflows/pages.yml` 在 `main` 更新时自动发布。
- `docs/demo` 保存同一演示的静态快照，可用于无需服务器的发布预览。

GitHub Pages 模式用于展示界面和交互。若要运行 Python 分析流程、访问经过审批的私有病例或保存长期标注，应使用下方的容器/云部署，并配置身份认证、HTTPS 和私有存储。

数据与代码必须分开保存：

| 内容 | 建议位置 | 是否进入 GitHub / 公开镜像 |
|---|---|---|
| 源代码、模板、合成数据生成器 | GitHub 仓库 | 是 |
| 默认公开演示数据 | Docker 构建时生成的 10 例合成记录 | 只进入演示镜像，不提交原始数据文件 |
| 经审批的脱敏病例或需长期保留的合成数据 | 私有、加密、只读持久卷，挂载到 `/data/cases` | 否 |
| SQLite、审计、标注和报告 | 私有、加密、可写持久卷，挂载到 `/data/app` | 否 |
| 可识别的原始病例 | 仅限满足授权、访问控制、审计和合规要求的受控环境 | 禁止进入公开仓库或公开演示 |

### Render 免费合成演示

仓库根目录的 `render.yaml` 可创建 Render Web Service。Render 会根据 `Dockerfile` 构建镜像，构建阶段运行 `scripts/generate_synthetic_demo.py` 生成 10 例不含真实身份信息的演示记录，因此无需把大体积病例上传到 GitHub。

1. 把代码（不含本地病例、`config.json` 和 `.env`）推送到 GitHub。
2. 在 Render 控制台从该仓库创建 Blueprint。
3. 首次创建时，在控制台为 `ECG_DEMO_PASSWORD` 设置高强度随机密码；`ECG_SECRET_KEY` 由 Render 生成，不写入仓库。
4. 部署完成后，将 Render 提供的 `https://...onrender.com` 地址发给演示设备，并使用演示用户名和密码访问。

免费实例适合只读、可重建的合成演示。它的本地写入可能在重启或重新部署后消失，不适合保存长期标注、报告或任何真实病例。需要持久化时，应改用私有持久卷或受控的院内/云端存储，并完成相应的数据授权、加密、备份、审计和访问控制。

### 通用 Docker 运行

构建并启动内置合成数据的只读演示：

```sh
docker build -t cardioinsight-holter-demo .
docker run --rm -p 8765:8765 --env-file .env cardioinsight-holter-demo
```

`.env` 只保留在部署设备或秘密管理器中，不能提交到 GitHub。使用经审批的私有病例卷时，显式覆盖数据目录：

```sh
docker run --rm -p 8765:8765 --env-file .env \
  --mount type=bind,src=/absolute/private/cases,dst=/data/cases,readonly \
  --mount type=volume,src=cardioinsight-state,dst=/data/app \
  -e ECG_DATA_ROOT=/data/cases \
  cardioinsight-holter-demo
```

容器和云平台统一读取平台提供的 `PORT`，并监听 `0.0.0.0`。公网前端必须由平台提供 HTTPS；本项目的演示密码保护不能替代完整的多用户身份系统、RBAC 或医疗数据合规控制。

### 云部署环境变量

| 变量 | 用途与建议 |
|---|---|
| `ECG_DATA_ROOT` | 病例根目录。演示镜像默认指向构建时生成的数据；私有部署建议使用只读卷 `/data/cases`。 |
| `ECG_APP_DATA_ROOT` | SQLite、审计、标注与报告的可写目录；需要保留时挂载私有持久卷 `/data/app`。 |
| `ECG_DEMO_PASSWORD` | 非空时启用演示访问密码。公网部署必须在平台控制台设置高强度随机值，禁止写入仓库。 |
| `ECG_DEMO_READONLY` | 公网演示设为 `true`，阻止资料、标注、报告和身份信息授权等写操作。 |
| `ECG_ALLOW_PHI` | 公网演示设为 `false`，强制禁止显示可识别身份信息；仅在有明确授权的受控环境中考虑启用。 |
| `ECG_SECRET_KEY` | Flask 会话签名密钥。使用平台生成或秘密管理器保存的稳定随机值（至少 32 个字符），禁止写入仓库。 |
| `ECG_DEMO_USERNAME` | 演示用户名，默认 `demo`。 |
| `ECG_TRUST_PROXY_HEADERS` | 在 Render 等受信任的单层反向代理后设为 `true`。 |
| `ECG_SESSION_COOKIE_SECURE` | HTTPS 部署设为 `true`，只通过安全连接发送会话 Cookie。 |

### 健康检查

容器和 Render 均使用 `GET /api/health`：

```sh
curl -fsS https://your-service.example/api/health
```

可用演示应返回 HTTP 200，且 JSON 中 `status` 为 `ok`、`data_root_found` 为 `true`、`case_count` 为预期病例数。若返回 `data_root_missing`，检查 `ECG_DATA_ROOT` 和私有卷挂载。健康检查端点不返回患者身份或波形数据。

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
- 8 路原始通道及推导 12 导联、3/6/12 导联布局、1–120 秒时间窗、增益和显示滤波。
- EBI 搏动分类、心率摘要、分钟趋势、RR 直方图、Poincaré 图与 HRV 时域指标。
- R-R、N、N-N、S、V、小时六类散点图；小时图随主波形焦点切换到对应整点一小时，显示该小时的 RR(i)–RR(i+1)。
- 鼠标自由圈选和键盘数值范围选择都会在完整逐搏数据上精确计算，并在左侧虚拟滚动显示全部圈内三导联片段。
- 心动过缓、心动过速、长 RR、室上性和室性候选事件筛选。
- 人工标注、审计日志、报告草稿/复核状态、版本记录与中文 PDF 导出。
- macOS Retina / Windows HiDPI、系统字体、`⌘ K` / `Ctrl K`、缩放窗口布局和减少动态效果偏好。

### 波形复核操作

- 在多导联波形上滚动滚轮：以指针所在时间为中心缩放时间轴；`Shift + 滚轮`：切换 5/10/20 mm/mV 电压增益。
- 工具栏 `− / 当前时间窗 / ＋`：缩小、复位或放大时间轴；窗口下拉框可直接选择 1、2、5、10、20、30、60、120 秒。
- 键盘 `+` / `-`：放大或缩小；`0`：复位到 10 秒；`←` / `→`：切换前后窗口；`A`：添加人工标注。
- 拖动波形可平移时间窗；悬停显示精确时间、当前导联和电压坐标；双击创建标注。
- 在右侧散点图中按住鼠标或触控笔画闭合圈；键盘用户可展开“键盘范围选择”输入横纵轴范围。左侧按时间列出圈内全部心搏片段，列表按滚动位置加载；点击任一片段会把主波形定位并高亮到对应心搏。
- 六类散点图可即时切换；“清除”按钮会清空圈线、高亮和片段列表。界面显示“当前绘制点 / 完整候选点”，圈选结果不受绘图抽样影响。

## 隐私与仓库边界

仓库不包含原始病例、报告影像、本地 SQLite、完整性清单、导出报告、虚拟环境或应用构建产物。项目根目录的 `config.json` 也被忽略，避免把本机病例路径提交到版本控制或上传到 GitHub。

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

不含病例数据的 GitHub Actions 会在 macOS 与 Windows 上运行平台路径测试、合成 EBI 散点核心测试、Python 编译检查、JavaScript 语法检查和对应平台启动脚本检查。

## 目录

- `app.py`：本机应用入口与 API。
- `ecg_core/`：数据解析、波形、事件、存储、平台路径和报告核心。
- `templates/`、`static/`：根据系统动态适配的工作站界面。
- `tests/`：自动化验证。
- `docs/`：需求追踪、数据格式、测试和合规边界。
- `scripts/`：macOS / Windows 环境、打包和完整性工具。

## 当前边界

本版本未实现经临床验证的房颤/ST/QT/起搏器诊断算法、多人登录与完整 RBAC、HIS/PACS/DICOM/HL7 接口、可验证数字签名、PDF/A 或医疗器械注册所需的软件生命周期与风险管理体系。详见 `docs/需求追踪矩阵.md` 和 `docs/临床与合规边界.md`。
