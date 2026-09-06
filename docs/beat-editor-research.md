# 心搏右键编辑：调研与实现规范

更新：2026-09-05。菜单来自用户提供的医院分规软件截图；未展开的子菜单按公开软件工作方式推定，不宣称复制厂商私有算法。

## 竞品调研

查阅六类 Holter 产品的厂商资料。这是有代表性的公开资料调查，不是对市场“大多数产品”的穷尽统计。宣传性能不能当成本项目的准确率。

| 一手资料 | 公开工作方式 | 本项目采用 |
| --- | --- | --- |
| [NorthEast HE/LX Rev S 操作手册](https://www.nemon.com/supportfiles/NEMM027_Rev_S%20HE-LX%20Operator%20Manual.pdf)，[支持目录](https://www.nemon.com/support-downloads/)已列 Rev T | 单搏／模板匹配范围、多选、撤销、节律复核 | 明确数量及作用范围，保留撤销 |
| [Baxter/Hillrom HScribe 操作手册](https://www.hillrom.com/content/dam/hillrom-aem/us/en/sap-documents/LIT/80031/80031558LITPDF.pdf) | ECG 右键改型、插入、删除，设置分析条件，保留图条后审核报告 | 连续波形／图条共用菜单，预览、确认与报告状态联动 |
| [Philips Zymed 2010 Plus v2.7 使用说明](https://www.documents.philips.com/assets/Instruction%20for%20Use/20220223/c0a0f6c4352d456a985aae4501369318.pdf?feed=ifu_docs_feed)（历史版本） | 分类、逐搏、事件、趋势、图条等不同复核视图 | 所有视图读取同一修订结果 |
| [SCHILLER medilog DARWIN2 使用说明](https://eifu.schiller.ch/wp-content/uploads/2024/10/2.511454d_EN-US_medilog-Darwin2.pdf) | 多视图分析与人工复核工作区 | 保持病例与时间上下文，最终解释属于医生 |
| [Spacelabs Pathfinder SL](https://spacelabshealthcare.com/products/diagnostic-cardiology/holter-analyzers-recorders/pathfinder-sl/) | 形态、噪声、分析参数和重分析 | 位置／类型变化触发关联重算 |
| [GE CardioDay](https://www.gehealthcare.com/en-in/products/diagnostic-ecg/cardioday-holter-ecg-software) | 引导式复核与心电信息系统衔接 | 修改导致待重核；不虚构 MUSE/HIS 接口 |

## 截图全部可见条目

入口：波形复核连续 ECG、散点圈选图条、模板编辑连续 ECG 和代表图条。左下形态集合的“右键取消框选”不改变。

| 条目 | 实际行为 |
| --- | --- |
| N 正常、S 房性早搏、V 室性早搏、J 交界性早搏、G 交界性逸搏 | 人工指定类别，更新计数、逐搏显示和 NN 纳入 |
| P 起搏 | 推定子菜单：未细分、PA 心房、PV 心室、PD 双腔、PF 起搏融合；不是自动起搏脉冲识别 |
| B 束支传导阻滞 | 未细分、BL 左束支、BR 右束支；医生指定，不是 QRS 时限自动诊断 |
| A 房颤、C 房扑、M 房颤伴室内差异性传导、H 房扑伴室内差异性传导 | 人工逐搏节律属性，保留 QRS 并排除出 N-N；事件数量不是发作次数或负荷 |
| F 融合波、E 室性逸搏、R 室内差异性传导、W 房性逸搏、Z 房早伴室内差异性传导 | 分类持久化，关联 RR／计数／事件 |
| O 房早未下传、Y P 波、T T 波 | 把误识别的 QRS 改成非心搏标记，波形仍可见，不计心搏和 NN |
| X 伪差 | 保留噪声标记，不计有效心搏，阻断严格 N-N 连续差分 |
| 删除 D | 逻辑删除标记，邻接 RR 重算；不删除原始波形 |
| 手动批量添加 QRS | 输入一个或多个记录起点后的秒数，量化到 5 ms；默认 OTHER 未分类，预览后提交 |
| 手动调整 QRS 位置 | 精确时间输入或 5 ms 微调，稳定 ID 不变；RR 和模板成员位置跟随 |
| 自动向前／向后插入 | 锚点前／后 1–60 秒原始导联信号检测候选，展示波形；默认不勾选，医生确认才补标 |
| 修改前一／后一心搏 | 查找当前序列相邻心搏，选择完整类型并预览；首末边界报错 |
| 设为最长 RR 间期 L | 指定报告图条锚点；不覆盖数学上实际最长 RR 的数值 |
| 全选／当前页全选 K／反选／当前页反选 I | 圈选图条全集是圈选结果；编辑全集是当前类别／模板；连续复核全集是当前记录。当前页仅包含可见图条或当前波形窗口 |
| 设置选项 | 按病例保存导联、排重间隔、能量阈值系数、搜索时长、快慢心率／长 RR 默认阈值、NN 纳入上下限 |
| 恢复、撤销／重做（补充） | 恢复源类型与位置；保留跨刷新历史及审计；最多 20 次，本地大批量历史受容量约束，至少留最近一次 |

键盘：选中模板心搏后 N/S/V/X 单搏快速改型；其他类型、批量及位置编辑先确认。菜单支持类型字母、D/K/I/L、方向键、Home/End、Esc；Ctrl/⌘+A 全选当前集合，Ctrl/⌘+I 反选；Ctrl/⌘+Z 撤销，Ctrl/⌘+Shift+Z 重做。S/R 是类型字母，不再同时承担裸键全选／反选。

## 算法和医学边界

- UI 字母不是 WFDB 编码：例如截图 A 表示房颤，WFDB A 表示房性早搏。参见 [WFDB 编码](https://physionet.org/physiotools/wpg/wpg_36.htm)与[注释结构](https://www.physionet.org/physiotools/wpg/wpg_30.htm)。旧项目 O=其他仍读为 OTHER，不静默改成房早未下传。
- RR 由有效 QRS 采样位置差乘 5 ms 计算，不覆盖源 EBI 的 RR。X 保留为噪声边界；O/Y/T 为非心搏标记，不再构成 R-R 间隔端点。
- HRV 只纳入严格相邻 N-N；RMSSD/pNN50 的差分也必须是连续 NN 对，不把异常间隔删掉后拼接两段数据。依据 [PhysioNet HRV 教程](https://archive.physionet.org/tutorials/hrv/)与 [pNNx](https://archive.physionet.org/physiotools/pNNx/)。
- SDANN／SDNN index 采用完整五分钟区间，每段至少 30 个 NN（本项目质量门槛，不宣称通用临床标准），三角指数箱宽 7.8125 ms。短记录不等价于完整 Holter。
- QRS 候选算法：导数平方能量、80 ms 移动窗、median+系数×MAD 阈值、局部绝对峰、不应期排重，支持正向和倒置波形。参考 [WFDB 处理文档](https://wfdb.readthedocs.io/en/latest/processing.html)的检测／不应期概念；当前实现不是 XQRS，也未获得其性能验证。
- 阈值比不是置信概率。漂移、T 波、起搏脉冲、宽 QRS、低幅及噪声都可能误检／漏检；候选默认不选中，不直接自动写入。
- 插入／移动距其他有效 QRS 至少 100 ms，是防重叠的编辑保护，不是诊断阈值。
- 分类和 RR 阈值独立：一个室早可以同时进入 V 与长 RR 队列。AF/AFL 是医生逐搏属性，不自动判断发作、负荷、起搏感知或夺获失败。

## 数据与闭环

本地 SQLite 保存 beat_edit_documents 修订文档、历史；源 DATA/EBI 不写入。稳定 ID 为 s:原采样点或 i:补标初始采样点。beat_edit_template_refs 使模板成员跟随移动／撤销；删除成员暂不展示。

GET /beat-editor、GET /beat-editor/beats、POST /beat-editor/preview、PUT /beat-editor。提交要求当前 revision 和 confirmed=true。预览和搜索不写修订。数据接口默认保留源比较兼容，界面加 analysis=edited 读取修订结果。

本地修订、审计及复核失效在一个事务中：相关环节待重核，已审核报告回到草稿，旧事件证据待重核。源报告摘要和医生正文不自动改写；报告重算区单独显示修订数据。

Demo 独立保存于当前浏览器 localStorage，不写开发数据库、不上传。保存失败回滚；支持 Web Locks 的浏览器串行编辑提交；修订号防止旧预览提交。localStorage 不能作为正式医疗记录库。

## 验证范围与下一阶段

软件回归覆盖分类／非心搏、邻接 RR、NN 断点、独立事件计数、正／倒置 QRS、重复／越界拒绝、预览只读、持久化撤销／重做、旧版本拒绝、Python/JS 一致性、Demo 存储失败和模板稳定引用。浏览器使用临时数据库操作，不污染正式医生记录。

尚无独立标注集上的 QRS 灵敏度／阳性预测值、跨设备及跨人群评估，尚未完成 AF／起搏专用识别、导联／幅值计量核验、医疗器械注册、医院权限及电子签名体系。不能宣称医院软件等效或直接临床部署。
