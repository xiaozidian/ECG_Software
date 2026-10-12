# CardioInsight Holter

本仓库保存 ECG 软件源码和独立的数学浏览器 Demo。当前代码版本为 `0.12.14-template-linkage.20261012`，生产软件清单包含112个文件。完整来源指纹、方法及验证记录见[本版说明](docs/releases/0.12.14-template-linkage.20261012/README.md)与[来源清单](docs/releases/0.12.14-template-linkage.20261012/source-manifest.json)。实际本机安装版本和线上构建结果分别核对；源码更新本身不表示已经切换服务。

软件用于研究与工程验证，自动事件为待医生复核的候选。原波形使用既有200Hz、8存储通道导入口径及12展示导联，设备映射、电压校准和医生金标准尚未独立核验；本版不构成临床验收。

## 医生操作

- 总览或模板编辑的底部三导联连续波形右键选择房颤起点和终点，可跨时间窗分段插入；待复核与确认分别记录，显式保存。原心搏右键菜单、模板密度分布和模板库双界面保留，普通选择无需等待双击。
- ST-T保留手工点测量，新增至少60秒范围的全部合格搏算术均值、有效/剔除/缺失计数及来源。先填入医生复核备注，再独立保存；已保存备注可从报告详情明确追加至结论，不自动诊断持续下移。
- 报告默认移除审核前检查面板、术语树和冗余辅助入口；保留事件分类、图条、医生结论、保存与导出。既有文字和已保存术语引用继续保留。未应用区间、未保存修改、冲突、过期依据和医生确认保护继续生效。
- 编辑页散点图与分组波形增大，常驻说明精简，完整来源在详情回看；ST导联和报告类别局部更新，保留同病例上下文并拒绝旧请求覆盖新选择。
- HRV网页连续展示，A4/PDF入口位于最后。RR复核、NN范围与版本化术语能力保留独立来源和修订，不把未知值补成零。

## 数学 Demo

[GitHub Pages](https://xiaozidian.github.io/ECG_Software/)由`.github/workflows/pages.yml`构建发布。载荷只由数学函数、固定种子及明确人工标签生成：600秒、200Hz、8存储通道。构建不读取本机病例、工作库、来源报告、医院素材或旧演示载荷。

Demo适配器仅在浏览器自己的版本命名空间保存数学操作；ST均值从完整数学原始输入计算。浏览器数学摘要与原生HMAC凭据明确区分。Demo不提供真实病例保存、Python诊断后端或原生工作库恢复。浏览器打印与本机后端PDF是不同实现，分别验收。

```sh
python -m pip install -r requirements.txt
python scripts/build_static_demo.py
python -m http.server 4173 --bind 127.0.0.1 --directory build/pages
```

打开`http://127.0.0.1:4173/`。修改落在源码、Demo适配器或构建器，再重建产物，不手改生成文件。

## 本机运行

安装Python3.12与`requirements.txt`，显式选择独立数学输入：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/generate_synthetic_demo.py --output ./demo_data --cases 1 --duration-minutes 10
ECG_ALLOW_PHI=0 ECG_APP_DATA_ROOT=./local-math-workspace python app.py --data-root ./demo_data --host 127.0.0.1 --port 8765 --no-browser
```

Windows使用`.venv\Scripts\Activate.ps1`，并在启动前设置相应环境变量。数学示例始终明确输入目录并关闭身份显示。Mac `.command`入口需要另行构建的软件包；源码不能替代编译安装版实际验收。原始来源与独立工作库分离，更新软件不覆盖已有配置、病例或工作数据库。

## 验证范围

本版说明分别记录全量回归、实际Mac Chrome流程、编译版、数学Demo及对应提交的Actions结果。核心数学验证方法见[核心验证说明](docs/core-verification.md)。一分钟到整日区间均值的同硬件实测及复跑脚本见[本版性能收据](docs/releases/0.12.13-doctor-feedback.20261012/performance.json)；进程首次调用与OS磁盘冷缓存分别说明，不用缓存命中比较全读，也不将核心计时当作网页等待。

数学参考只能证明相应软件契约与算术；不能证明真实全天设备数据、临床敏感度或特异度。HRT没有合格源事件时间时不制造跳转；QT与无有效搏均值保持未知。

公开范围仅软件、纯数学测试及可复现数学Demo，不包含病例、数据库与WAL/SHM、身份映射、医院素材、真实报告、私有截图或未经验证的二进制。旧版[0.12.11](docs/releases/0.12.11-doctor-evaluation.20261011/README.md)及[0.12.12](docs/releases/0.12.12-doctor-evaluation.20261012/README.md)记录保留，不沿用旧版本验收成绩。
