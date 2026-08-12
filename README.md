# CardioInsight Holter 心电分析工作站

CardioInsight Holter 是一个在本机运行的动态心电研究与软件验证工作站，同时支持 **macOS** 和 **Windows**。源码运行时使用项目根目录的本机 `config.json`；程序会按当前系统选择原生数据存储目录、界面字体、显示优化和搜索快捷键。服务默认只监听 `127.0.0.1`，病例文件只读访问，身份信息默认遮蔽。

> 本项目仅用于研究、教学和软件功能验证，不用于独立临床诊断、报警、分诊或治疗决策。自动分类、事件和统计均为待专业人员复核的候选结果。

## 先区分两个版本

仓库同时维护“实际开发版”和“在线 Demo 版”，二者共享界面基础，但入口、数据和运行方式相互隔离。

| 项目 | 实际开发版 | 在线 Demo 版 |
|---|---|---|
| 用途 | macOS / Windows 本机开发、完整功能调试 | GitHub Pages / Cloudflare Pages 公开演示 |
| 入口 | `app.py`、系统启动脚本或桌面打包程序 | `scripts/build_static_demo.py` 生成的静态站点 |
| 后端 | Python / Flask API | 无后端；由浏览器内只读 API 适配层提供数据 |
| 数据 | 本机 `config.json` 指向的病例目录 | 仅“徐有德”一例 10 分钟公开片段 |
| 配置 | 项目根目录本机 `config.json`，不提交 | 不读取 `config.json`、`.env` 或 `ECG_DATA_ROOT` |
| 写入 | 标注、报告、审计写入系统用户数据目录 | 只读演示；临时交互最多保存在当前浏览器 |
| 专属源码 | `app.py`、`ecg_core/`、`templates/`、`static/` | `demo/` |
| 生成产物 | `dist/` | `build/pages/`；仓库快照为 `docs/demo/` |

版本隔离约定：

- 正式版的 `app.py` 和 `ecg_core/` 不读取 `demo/`；正式 `static/` 中不存放 Demo 病例或 Demo API。
- `demo/static/` 只保存在线版专属浏览器 API 与公开病例片段；构建时才叠加到独立发布目录。
- `build/pages/` 和 `docs/demo/` 都是生成结果，不直接手工修改。改动应落在 `templates/`、正式 `static/` 或 `demo/` 的源文件，再重新构建。
- 本机 `config.json`、完整病例目录、数据库、报告和完整 DATA 不属于在线 Demo，禁止加入发布包。

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

### GitHub Pages / Cloudflare Pages 在线演示

原始完整应用需要 Python/Flask 服务、病例目录和可写的应用数据目录，不能直接在只支持静态文件的 GitHub Pages 上运行。仓库因此提供了一个独立的浏览器演示模式，公开版本仅展示用户指定并确认可公开的“徐有德”病例片段。

- 正式演示地址（仓库管理员启用 Pages 后生效）：<https://xiaozidian.github.io/ECG_Software/>
- `scripts/build_static_demo.py` 生成 Pages 发布包；`.github/workflows/pages.yml` 在 `main` 更新时自动发布。
- `docs/demo` 保存同一演示的静态快照，可用于无需服务器的发布预览。
- “徐有德”对应病例 `2508040855572068`。完整 DATA 约 266 MB，超过 GitHub 100 MB 单文件限制和 Cloudflare Pages 25 MiB 单资源限制，因此公开版本发布其 22:53–23:03 的 10 分钟原始 8 通道 int16 片段（约 1.9 MB），并保留病例 ID、科室、诊断、逐搏分组和源报告摘要。
- 该片段不是重新绘制的波形：Demo 源文件 `demo/static/demo-data/uploaded-sim-af-001/waveform.bin` 是源 DATA 的直接字节裁剪，`case-data.js` 保存对应 EBI 逐搏记录和病例资料；发布后位于站点的 `static/demo-data/`，页面在浏览器内读取二进制并推导 12 导联。
- HRV 页面并列展示完整源报告（23 小时 04 分钟）与当前公开片段（10 分钟）的重算结果。片段结果直接从 NN 序列计算；SDANN 与 SDNN index 使用 5 分钟分段，三角指数使用 1/128 秒箱宽，定义参考 [ESC/NASPE HRV 测量标准](https://www.escardio.org/static-file/Escardio/Guidelines/Scientific-Statements/guidelines-Heart-Rate-Variability-FT-1996.pdf)。两组数据统计时长不同；10 分钟 SDANN、SDNN index 与三角指数只作为演示估计，不能解释为算法误差或临床结论。
- `scripts/import_public_simulated_case.py` 记录了可复现的裁剪流程，并且必须显式提供 `--confirm-synthetic` 才会导出。

#### 本地构建和预览 Demo

在项目根目录执行：

```zsh
./.venv/bin/python scripts/build_static_demo.py
./.venv/bin/python -m http.server 4173 --bind 127.0.0.1 --directory build/pages
```

然后打开 <http://127.0.0.1:4173/>。预览应只显示 1 例“徐有德”；停止服务按 `Ctrl+C`。构建过程只读取仓库内的模板、正式公共静态资源和 `demo/`，不会读取本机正式 `config.json` 或病例目录。

上线前建议执行：

```zsh
./.venv/bin/python -m pytest -q
node --check demo/static/js/demo-api.js
node --check static/js/app.js
./.venv/bin/python scripts/build_static_demo.py
```

#### GitHub Pages 自动上线

1. 将改动合并并推送到 `main`。
2. GitHub Actions 的 `pages.yml` 自动安装静态构建依赖、生成 `build/pages`、检查 JavaScript 并发布。
3. 在仓库 **Settings → Pages** 中将 Source 设为 **GitHub Actions**。首次启用后，后续每次推送 `main` 都会自动更新。
4. 在 Actions 页面确认 `Deploy single-case demo to GitHub Pages` 的 `build` 与 `deploy` 均成功，再访问正式演示地址。

GitHub Pages 上传的是构建产物，不会运行 `app.py`，也不会上传被 `.gitignore` 忽略的本机 `config.json` 与完整病例目录。

#### Cloudflare Pages 上线

Cloudflare Pages 可直接连接本 GitHub 仓库，不需要把 GitHub Pages 作为源站。创建 Pages 项目时使用以下配置：

| Cloudflare Pages 配置 | 值 |
|---|---|
| Production branch | `main` |
| Framework preset | `None` |
| Build command | `python -m pip install "Jinja2>=3.1,<4" && python scripts/build_static_demo.py` |
| Build output directory | `build/pages` |
| Environment variable | `PYTHON_VERSION=3.12` |

每次推送到 `main` 后，Cloudflare 会自动构建并分发同一份单病例静态演示。Cloudflare 项目中不需要配置 `ECG_DATA_ROOT`、正式 `config.json` 或本机病例路径；公开片段已经作为受版本控制的静态资源随站点发布。

Cloudflare 操作顺序：

1. 在 Cloudflare 控制台进入 **Workers & Pages → Create → Pages → Connect to Git**。
2. 选择 GitHub 仓库 `xiaozidian/ECG_Software`，Production branch 设为 `main`。
3. 按上表填写构建命令、输出目录和 Python 版本，然后执行首次部署。
4. 部署成功后先使用 Cloudflare 提供的 `*.pages.dev` 地址检查病例数量、波形加载和浏览器控制台，再按需绑定自定义域名。
5. 后续只需推送 `main`；Cloudflare 会重新构建。不要在 Cloudflare 环境变量中填写本机路径、患者目录或 `config.json` 内容。

GitHub Pages 模式用于展示界面和交互。若要运行 Python 分析流程、访问经过审批的私有病例或保存长期标注，应使用下方的容器/云部署，并配置身份认证、HTTPS 和私有存储。

数据与代码必须分开保存：

| 内容 | 建议位置 | 是否进入 GitHub / 公开镜像 |
|---|---|---|
| 源代码、模板、演示数据生成器 | GitHub 仓库 | 是 |
| 默认公开演示数据 | 仅“徐有德”一例经用户确认可公开的源病例片段 | 仅提交约 1.9 MB 的病例片段及逐搏资料；不提交 266 MB 完整 DATA |
| 经审批的脱敏病例或需长期保留的测试数据 | 私有、加密、只读持久卷，挂载到 `/data/cases` | 否 |
| SQLite、审计、标注和报告 | 私有、加密、可写持久卷，挂载到 `/data/app` | 否 |
| 可识别的原始病例 | 仅限满足授权、访问控制、审计和合规要求的受控环境 | 禁止进入公开仓库或公开演示 |

### Render 全栈测试环境（与静态 Demo 不同）

该路径运行 Flask，属于实际开发版的容器化测试环境，不是上面的“徐有德”单病例静态 Demo。仓库根目录的 `render.yaml` 可创建 Render Web Service；Render 会根据 `Dockerfile` 构建镜像，构建阶段运行 `scripts/generate_synthetic_demo.py` 生成 10 例不含真实身份信息的测试记录，因此无需把大体积病例上传到 GitHub。仅需公开展示时，优先使用 GitHub Pages 或 Cloudflare Pages。

1. 把代码（不含本地病例、`config.json` 和 `.env`）推送到 GitHub。
2. 在 Render 控制台从该仓库创建 Blueprint。
3. 首次创建时，在控制台为 `ECG_DEMO_PASSWORD` 设置高强度随机密码；`ECG_SECRET_KEY` 由 Render 生成，不写入仓库。
4. 部署完成后，将 Render 提供的 `https://...onrender.com` 地址发给演示设备，并使用演示用户名和密码访问。

免费实例适合只读、可重建的功能演示。它的本地写入可能在重启或重新部署后消失，不适合保存长期标注、报告或任何真实病例。需要持久化时，应改用私有持久卷或受控的院内/云端存储，并完成相应的数据授权、加密、备份、审计和访问控制。

### 通用 Docker 运行

构建并启动内置演示数据的只读版本：

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

不含病例数据的 GitHub Actions 会在 macOS 与 Windows 上运行平台路径测试、生成 EBI 散点核心测试、Python 编译检查、JavaScript 语法检查和对应平台启动脚本检查。

## 目录

- `app.py`：本机应用入口与 API。
- `ecg_core/`：数据解析、波形、事件、存储、平台路径和报告核心。
- `templates/`、`static/`：实际开发版使用的工作站界面与公共资源；不包含 Demo 病例数据。
- `demo/`：在线 Demo 专属浏览器 API 和单病例资源；实际开发版不读取。
- `build/pages/`：在线 Demo 临时构建产物，已忽略；`docs/demo/` 是同一构建的仓库快照。
- `tests/`：自动化验证。
- `docs/`：需求追踪、数据格式、测试和合规边界。
- `scripts/`：macOS / Windows 环境、打包和完整性工具。

## 当前边界

本版本未实现经临床验证的房颤/ST/QT/起搏器诊断算法、多人登录与完整 RBAC、HIS/PACS/DICOM/HL7 接口、可验证数字签名、PDF/A 或医疗器械注册所需的软件生命周期与风险管理体系。详见 `docs/需求追踪矩阵.md` 和 `docs/临床与合规边界.md`。
