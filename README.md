# CardioInsight Holter 心电分析工作站

CardioInsight Holter 是一个在本机运行的动态心电研究与软件验证工作站。服务默认只监听 `127.0.0.1`，病例文件只读访问，身份信息默认遮蔽；应用不会主动上传病例数据。

> 本项目仅用于研究、教学和软件功能验证，不用于独立临床诊断、报警、分诊或治疗决策。自动分类、事件和统计均为待专业人员复核的候选结果。

## macOS 快速启动

运行要求：macOS 12 或更高版本、Python 3.11 或更高版本。Apple Silicon 与 Intel Mac 均可从源码运行。

1. 双击项目根目录的 `启动心电分析软件.command`。
2. 首次运行会创建 `.venv` 并安装依赖，同时创建本地配置文件：

   ```text
   ~/Library/Application Support/CardioInsightHolter/config.json
   ```

3. 编辑配置中的 `data_root`，让它指向本机的 `10个病人的心电数据` 目录。
4. 再次启动。软件会使用默认浏览器打开 `http://127.0.0.1:8765`；端口占用时会自动选择后续可用端口。

也可以在终端中执行：

```zsh
./scripts/setup_macos.sh
./启动心电分析软件.command
```

本地标注、报告版本、审计数据库和导出的 PDF 保存在 `~/Library/Application Support/CardioInsightHolter/`，不会写入签名后的 `.app` 包。

## 配置

复制 [`config.example.json`](config.example.json) 的内容到上述用户配置路径。建议使用绝对路径：

```json
{
  "data_root": "/Users/your-name/Documents/ECG/10个病人的心电数据",
  "privacy_mode": "masked_by_default",
  "listen_host": "127.0.0.1",
  "listen_port": 8765
}
```

也可临时使用环境变量 `ECG_DATA_ROOT`，或启动参数 `--data-root`。为防止误暴露健康数据，绑定非回环地址时必须显式增加 `--allow-remote`。

## macOS 应用打包

```zsh
./scripts/build_macos.sh
open dist/CardioInsightHolter.app
```

构建脚本会生成 `dist/CardioInsightHolter.app` 并执行临时 ad-hoc 签名，适合本机验证。正式分发前必须使用 Apple Developer ID 签名并完成 notarization；Apple Silicon 与 Intel 的安装包应分别在对应架构上构建，或使用完整的 universal2 Python 依赖链。

## 已实现

- 病例工作台、检索、逻辑停用/恢复和患者资料本地覆写。
- 默认隐私遮蔽；查看可识别信息需要当前浏览器会话明确授权。
- 约 23 小时长记录的窗口化读取，不一次性载入完整波形。
- 8 路原始通道及推导 12 导联、3/6/12 导联布局、增益、时间窗和显示滤波。
- EBI 搏动分类、心率摘要、分钟趋势、RR 直方图、Poincaré 图与 HRV 时域指标。
- 心动过缓、心动过速、长 RR、室上性和室性候选事件筛选。
- 人工标注、审计日志、报告草稿/复核状态、版本记录与中文 PDF 导出。
- Retina 波形画布、macOS 系统字体、`⌘ K` 搜索、缩放窗口布局及减少动态效果偏好。

## 隐私与仓库边界

仓库不包含原始病例、报告影像、本地 SQLite、完整性清单、导出报告、虚拟环境或应用构建产物。`config.json` 也被忽略，避免把本机病例路径提交到版本控制。

如果需要验证原始数据完整性，请在受控环境中运行 `scripts/build_case_manifest.py`；生成的 `data/case_manifest.json` 只保留在本机。

## 测试

连接本机测试数据后运行：

```zsh
ECG_DATA_ROOT="/absolute/path/to/10个病人的心电数据" ./.venv/bin/python -m pytest -q
node --check ./static/js/app.js
```

自动化覆盖数据结构、时长、搏动统计、导联推导、窗口性能、隐私控制、事件/趋势/HRV、人工编辑、报告和审计流程。现有样本只能证明功能可运行及回归一致性，不能证明临床灵敏度、特异度或准确率目标。

## 目录

- `app.py`：本机应用入口与 API。
- `ecg_core/`：数据解析、波形、事件、存储、平台路径和报告核心。
- `templates/`、`static/`：工作站界面。
- `tests/`：自动化验证。
- `docs/`：需求追踪、数据格式、测试和合规边界。
- `scripts/`：macOS 环境、打包及完整性工具。

## 当前边界

本版本未实现经临床验证的房颤/ST/QT/起搏器诊断算法、多人登录与完整 RBAC、HIS/PACS/DICOM/HL7 接口、可验证数字签名、PDF/A 或医疗器械注册所需的软件生命周期与风险管理体系。详见 `docs/需求追踪矩阵.md` 和 `docs/临床与合规边界.md`。
