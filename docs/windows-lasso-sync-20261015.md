# Windows 1.0.2 与网页自由套索同步

Windows 包装版本 1.0.2，核心 0.12.17-lasso.20261015。构建提交 `af54df43700af53c97c72dfa0203bfe0c5acb2c8`，生产112文件SHA256 `658919366e55094ad4a50b5873e627c360df7a2cd73529af1f5771fd9f03f5aa`。

自由套索和细圆散点与已部署的 [Cloudflare Demo](https://ecg-software.pages.dev/) 和 [GitHub Pages](https://xiaozidian.github.io/ECG_Software/) 共用相同的 app.js、template-linked-view.js、morphology-workbench.css。Windows 后端保留原0.12.16的全天请求性能与独立工作区保护，不改诊断阈值。网页版只使用数学10分钟数据，Windows仅内置数学24小时M01。

## 实际验证

[最终原生续验](https://github.com/xiaozidian/ECG_Software/actions/runs/38719645725)通过：重新构建冻结EXE、ZIP自检、系统Edge全部39项成品检查，包含新增7项实际指针套索检查。凹多边形完整EBI独立预期选中21,609搏，对应外接矩形会选中38,199搏。非空临床目标、取消、两视图、空选、重复圈选、缩放和清空均验证。

完整回归来自[前次运行38710973555](https://github.com/xiaozidian/ECG_Software/actions/runs/38710973555)：2146通过、2项历史AF研究材料缺失失败、1跳过、0错误；无新增回归、无丢测，4项原整日断言通过。该运行在新增浏览器脚本失败，不能称整体成功。后续只修正验收脚本等待当前工作区就绪、按既有每视图临床目标缓存分别断言；生产文件未改。

续验严格固定前次提交及证据SHA256，检查除浏览器辅助脚本、续验脚本与工作流之外的所有Git文件均未变化，才复用完整回归。生产、依赖、构建、原测试或清单有任何变化均会拒绝复用。完整成品浏览器流程和Windows请求性能在新运行重跑；原失败证据保留。

## 下载与核验

首次使用 full ZIP，全部解压至新目录后双击 CardioInsightDoctorEval.exe。已有版本先保存并停止服务，software ZIP解压到另一新目录，保留原程序、Sources/M01及独立工作区。

| 产物 | 字节 | SHA256 |
|---|---:|---|
| CardioInsight-DoctorEval-Windows-x64-1.0.2-full.zip | 201976110 | `788687f15a6adf4e991ba9bdb9bcd63362485465c56c39847268e4fb1b4ea293` |
| CardioInsight-DoctorEval-Windows-x64-1.0.2-software.zip | 38092826 | `ef2ee59de28d982f6e651c50462dafc8963b1f4ae1a33ec6f7a3b86ad22d40c8` |

Actions产物见[本轮运行](https://github.com/xiaozidian/ECG_Software/actions/runs/38719645725)。正式产物不含1.0.3测试夹具。本地归档已进行CRC、清单逐文件SHA256、AMD64 EXE、来源清单和共享交互文件一致性检查。

## 保留限制

两个AF研究测试在读取缺失的历史冻结材料时失败，原阈值及来源漂移断言尚未执行；不替换材料、不改阈值，不宣称全量全绿或临床准确性已验收。Windows原生验收运行于GitHub Windows Server2025 x64和系统Edge，医院Windows10、干净无Python机器、EDR/签名接受、中文实体打印仍待实机确认。升级验证为同核同结构1.0.2→CI-only1.0.3，不能证明实际1.0.1→1.0.2跨核升级。

旧1.0.1及其历史验收记录保留。Mac现用十病例版本、真实来源、医生保存工作及原工程未提交修改均未被此次发布覆盖。完整摘要见[机器可读证据](releases/0.12.17-lasso.20261015/windows-final-acceptance-summary.json)。
