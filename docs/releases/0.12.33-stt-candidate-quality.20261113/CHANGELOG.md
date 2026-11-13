# ST-T 候选形态与噪声核对

本次明确更新自动筛查算法至 `stt-screening-0.5.0-morphology-qualified`。旧规则仅凭相对 ISO 的负值和持续时间，可能把负向平台上的细小波纹、短尖峰或 T 区间噪声反复列为异常候选。

- 候选另行核对局部波峰突出程度、实测宽度、局部噪声、快速反复交替及基线不确定性。原始波形、ISO/ST/T 数值、范围统计和全部趋势保持原样。
- 极性可变导联的稳定负向背景不单独列异常；可靠的持续加深或极性变化仍保留。通常正向导联的持续负向 T 不要求事先出现正向 T。
- 极性变化只与此前可靠、连续的稳定参考比较。反转并持续倒置的同一段仅列一条，保留两项依据；回到通常极性作为恢复，不另增异常。
- 保留 ST 段改变、持续倒置、低平、双相及极性反转的独立支持。ST-T 与房颤／房扑独立，事件仍须有至少 60 秒连续有效支持，可持续 n 分钟；不设候选数上限。
- 新增独立的筛查升级核验：明确登记实际新执行程序，逐例验证原测量一致，保留人工复核、图条用途和报告版本。原签署报告保留其原有筛查呈现；真正来源、心搏或方法变化仍走原有失效规则。
- 首次升级完整核验后，重启只在程序、来源、心搏、人工记录、报告及独立审计凭证全部精确匹配时复用已验证证明，避免反复复算全天数据。任何不匹配仍完整重验；不缓存或替代新的候选分析。

候选阈值使用设备原始单位，是工程形态支持条件。没有增加自动诊断或全量逐条确认关卡；医生仍可查看全部趋势并自选范围复核。

验证覆盖短尖峰、负向平台波纹、局部噪声、真宽 T、ST 改变、双相、低平、59/60/61 秒边界、真实 next-R 截断和房颤／房扑全生命周期。具体执行结果随发布验收记录保存。

## Windows native schema lifecycle

The Windows adapter initializes its canonical implementation-continuity table before the launcher records the workspace schema. A later physician read or continuity proof does not create schema objects. This fixes a verified failure in the rejected first1.0.22 candidate: a second real process restart was refused after a lazy-created table changed the registered schema.

A narrowly identified official1.0.21 workspace may be recovered only when the actual schema differs from its recorded schema by exactly the released canonical continuity table and implicit primary-key index, with the same user_version and every remaining schema object byte-exact. Recognition is read-only. A complete SQLite WAL-inclusive backup and the original WORKSPACE bytes and SHA are preserved before completion records `known-legacy-DDL-reconciliation`. Unknown DDL, indexes, triggers, release identity or schema differences still fail closed.

Internal manager/workspace child failures exit without a modal MessageBox, allowing the parent launcher to report the failure promptly. Interactive launcher errors retain their user-facing dialog. These changes are native adapters; clinical measurements, candidate thresholds and common132 source bytes are unchanged.
