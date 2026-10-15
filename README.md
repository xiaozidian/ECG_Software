# CardioInsight Holter

本仓库保存 ECG 软件源码和独立的数学浏览器 Demo。当前代码版本为 `0.12.17-lasso.20261015`，生产软件清单包含112个文件。完整来源指纹、方法及验证记录见[Windows持续发布说明](docs/windows-doctor-release.md)与[来源清单](docs/releases/0.12.17-lasso.20261015/source-manifest.json)。实际本机安装版本和线上构建结果分别核对；源码更新本身不表示已经切换服务。

软件用于研究与工程验证，自动事件为待医生复核的候选。原波形使用既有200Hz、8存储通道导入口径及12展示导联，设备映射、电压校准和医生金标准尚未独立核验；本版不构成临床验收。

## Windows 医生离线便携版

Windows x64 便携包直接复用本项目算法和报告，内置一例连续24小时纯数学合成来源，使用独立保存工作区及系统浏览器，无需医生安装Python。当前1.0.2同步自由套索和细圆散点，完整回归2146通过、2项既有AF资料缺失失败、1跳过；原18项模板契约、4项全天断言和39项原生成品Edge流程通过。验证复用条件、下载校验和限制见[1.0.2同步记录](docs/windows-lasso-sync-20261015.md)。旧1.0.1记录保留；医院Windows10实机与实际跨核心升级仍待验收。

## 医生操作

- 模板散点图支持沿指针轨迹自由套索，凹形边界按真实多边形选取；小圆散点与独立命中范围兼顾密度和操作。Escape 取消当前拖动，清空恢复完整集合；浏览焦点保留圈选集合和独立改型勾选。

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

既有记录分别保存各提交的全量回归、Mac Chrome流程、编译版和数学Demo结果；本次Windows核心验收、严格整日回归与请求性能以[专项交付记录](docs/windows-doctor-eval-followup.md)及其Actions收据为准，不沿用旧版本成绩。核心数学验证方法见[核心验证说明](docs/core-verification.md)。0.12.13在Mac上的一分钟到整日区间均值实测及复跑脚本见[历史ST核心性能参考](docs/releases/0.12.13-doctor-feedback.20261012/performance.json)；进程首次调用与OS磁盘冷缓存分别说明，不用缓存命中比较全读，也不将核心计时当作网页等待。

数学参考只能证明相应软件契约与算术；不能证明真实全天设备数据、临床敏感度或特异度。HRT没有合格源事件时间时不制造跳转；QT与无有效搏均值保持未知。

公开范围仅软件、纯数学测试及可复现数学Demo，不包含病例、数据库与WAL/SHM、身份映射、医院素材、真实报告、私有截图或未经验证的二进制。旧版[0.12.11](docs/releases/0.12.11-doctor-evaluation.20261011/README.md)及[0.12.12](docs/releases/0.12.12-doctor-evaluation.20261012/README.md)记录保留，不沿用旧版本验收成绩。
