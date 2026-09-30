# QTDB 端点对照协议 v1

制定日期：2026-09-29，首次查看误差结果之前固定。目的：查找当前 QRS 起点／T 终点算法在真实形态上的失败，不宣称医疗器械验收通过。

## 数据及角色

- PhysioNet QT Database 1.0.0，`RECORDS` 全部 105 条，输入 `.hea/.dat`，参考为人工审校后的 `.q1c`；有 `.q2c` 时作为第二标注者的附加对照。`.pu*` 自动边界不能作为人工真值。
- 公开数据保持只读；记录全部使用文件的 SHA-256 和算法源文件 SHA-256，不复制到患者病例索引。
- 记录名 SHA-256 的首字节模 5 等于 0 为 development，其余为 evaluation。在 development 排查并固定修改后再运行 evaluation。这个工程拆分不是独立机构的盲测或临床试验。
- 原始数据库引用及许可：[QT Database](https://physionet.org/content/qtdb/1.0.0/)，Laguna 等，Computers in Cardiology 24:673–676 (1997)，ODC-By 1.0。标注过程：[Manual Annotations](https://physionet.org/files/qtdb/1.0.0/doc/node5.html)。

## 固定处理

1. 使用官方 WFDB 库解析格式与标注，不自写压缩数据解码器。250 Hz 数据经 SciPy `resample_poly(4,5)` 到 200 Hz，R 标记位置四舍五入；参考端点保留原始 4 ms 时间网格。时间重采样和对齐可能引入误差。
2. 输入幅度按头文件换算到微伏用于统一测试；部分记录的幅度增益仅为数据库估计，因此本次不检验电压准确性。
3. 每个参考 N 标记以相同 R 中心取前 250 ms、后 650 ms，使用应用的 PR 基线区间去基线，调用实际 `delineate`。不使用人工 Q/T 端点决定输入窗口、选择导联或调整参数。
4. 为复现当前 QT 的基本 RR 门槛，只使用参考标记中前后相邻 N 均在 700–2000 ms 内、相邻 RR 变化不超过 20% 的目标搏。稀疏标注的两端／间隔过大明确记为不符合条件；不把缺失参考心搏当作长 RR。不能据此验证自动 QRS 检出、AF 排除或完整心搏筛选。
5. 两个导联独立输出并分别与相同人工参考比较，不按更接近真值的导联择优计分。人工参考由专家同时观察两导联确定，并非逐导联真值，因此跨导联差异会影响误差；必须在报告中说明。

## 必报结果

- 全记录数、参考 N 数、有完整 Q/T 的数量、RR／边界条件排除数、实际尝试数、自动成功数、拒绝原因。
- 已成功测量的 Q 起点、T 终点、QT 差值：有符号均值、标准差、绝对误差中位数／均值／95 分位数和 >50 ms 数量。50 ms 仅是排错分层，不是临床合格阈值。
- 按记录与导联报告，保留逐搏结果；总体同时报告覆盖率，不能仅用成功样本误差掩盖拒绝率。
- 首次开发组运行遇到算法空数组异常，尚未产生完整误差结果。补充固定规则：算法异常单列 `error`，保留在尝试数分母中并记录数量；不混入正常质量拒绝。数据读取／摘要／格式错误仍直接终止评估。
- 对比旧版和修改版使用完全相同的病例、标注和预处理。测试参考误差不得用于运行时挑选导联。

## 限制

该实验检验单搏端点组件，不是最终多搏中位形态／八导联 QTd／QTc 临床有效性验证；不人为复制两导联成八导联，也不计算虚假的 QTd。数据库经筛选减少明显伪差，不能代替目标设备、真实伪差、人工端点工作流与医生盲测。

## 重跑方式

在独立验证虚拟环境安装 `requirements-validation.txt`，不改变应用运行环境。`scripts/fetch_qtdb.py --output /path/to/qtdb` 只从固定 PhysioNet 来源下载所需的 326 个数据／标注文件，另保存 `RECORDS` 及官方校验清单，四路并发并逐文件核对 SHA-256；不会传输本地病例。

使用该环境的 Python 执行：

```text
scripts/validate_qtdb.py --data /path/to/qtdb --split development --output /path/to/dev-results
scripts/validate_qtdb.py --data /path/to/qtdb --split evaluation --output /path/to/eval-results
scripts/validate_qtdb.py --data /path/to/qtdb --split all --annotator q2c --output /path/to/second-reader
```

每次输出 `summary.json`、逐搏 `beats.csv` 及 `algorithm_snapshot.py`，拒绝覆盖已有结果。可通过 `--algorithm-source` 加载此前本项目的算法快照，复现同一输入上的前后比较；不要加载不受信任的 Python 文件。摘要记录程序与依赖版本、算法／评估脚本／输入摘要。退出码 0 仅表示评估完成，不代表临床合格。`scripts/plot_qtdb_examples.py` 仅绘制开发组中每记录／导联一个最大误差例，方便追踪原因，不作为总体性能图。
