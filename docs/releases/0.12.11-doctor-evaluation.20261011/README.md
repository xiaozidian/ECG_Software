# 0.12.11 独立评估版软件来源

版本：`0.12.11-doctor-evaluation.20261011+b536fff32339cc27`。

94 个生产软件输入的 SHA256：`b536fff32339cc271f408160d9186fdc088bfb7a4bf8e965a5e967cfb3afe8c7`。完整指纹为 `source-manifest.json` 的 `files` 对象以 UTF-8、`ensure_ascii=False`、`sort_keys=True`、紧凑分隔符 `(',', ':')` 序列化后的 SHA256。可运行 `python scripts/verify_public_release.py` 逐文件核对。

该版本延续模板双界面、单击波形放大、ST 和报告局部更新、待应用游标保护与连续 HRV 页面。1440×900 模板库工具栏减少 2 像素垂直占位，为第二行波形候选留出空间。诊断规则、阈值、单位和波形输入未改变。

数学 Demo 使用同一批前端输入，构建时另做浏览器存储隔离与数学保存适配；转换前后摘要均写入 `mathematical-source-manifest.json`。Pages 执行浏览器 JavaScript，不执行 Flask/Python；其能力范围见 [核心验证说明](../../core-verification.md)。

这是工程功能评估版，源码和合成测试不能证明临床有效性。病例、工作数据库、真实报告和医院素材未包含于公开版本。

本地冻结软件完整回归：1768 项通过，失败、错误、跳过均为 0（202.982 秒）。原病例只读，每个测试独立临时数据库，私有历史参照保护保留；这是工程测试结果，未替代新版实机医生流程或临床验收。公开 CI 的纯合成测试单独运行，其结果以提交对应的 Actions 为准。
