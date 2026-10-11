# 核心源码与纯模拟核验

本地 Python 核心和线上数学 Demo 使用同一份经 SHA-256 清单核对的软件源码。GitHub Pages 发布静态 HTML、JavaScript 和公式生成的输入；Python 只在本地软件或 GitHub Actions 核验中运行。源码一致、指定夹具上的输出一致和运行架构是三个独立结论。

现有 Pages Demo 的初始波形、逐搏列表和参考摘要由 `scripts/build_math_payload.py` 新生成。来源收据 `mathematical-source-manifest.json` 记录软件源码版本、每个输出资产哈希和数学输入哈希；数据来源限定为公式生成。浏览器通过 `demo-api.js` 计算支持的接口并在独立 `localStorage` 命名空间保存模拟修改。该过程不运行 Flask、NumPy 或生产 Python 服务。

| 能力 | Python 核验 | 静态 Demo |
| --- | --- | --- |
| 心搏编辑、RR、事件与 QRS 候选 | Python 与便携 JS 的指定夹具输出逐项比较 | 浏览器 JS 计算 |
| 临床事件索引、HRV 分段 | Python/JS 索引与分段对照 | 浏览器 JS 计算 |
| HRV 时域、频谱与日夜分段 | Python/JS 指标及频谱对照；另检查缺口、噪声、未知时钟及频谱时间轴 | 浏览器 JS 与 FFT |
| QT、交替谱、Kors 向量和 RR 周期性研究指标 | 已知数学输入、异常输入与质量条件的 Python 参考断言 | 没有 `advanced-analysis` API，不执行 Python 核心 |
| 高级分析报告文档 | Python 生成证据后，比较 Python/JS 文档；Python PDF 烟测 | 可展示已提供的证据；不证明浏览器计算高级指标 |
| 原生 PDF、SQLite 与备份 | 属于本地软件的独立能力 | 无 `report.pdf`、`hrv-report.pdf` 或工作库备份 API；浏览器打印及存储具有不同实现 |

`scripts/verify_core_synthetic.py` 先核对冻结软件清单，再运行固定的数学测试选择器。测试在内存或临时目录生成输入，并将默认输入目录指向临时空目录。它不选择依赖原病例 `client` 夹具的 API 测试；任何失败、错误或跳过都使核验失败。

```sh
python -m pip install -r requirements-dev.txt
python scripts/verify_core_synthetic.py
```

Node 必须可用。现有 GitHub Actions 的 `core-verification.yml` 使用 Python 3.12 和 Node 22 运行相同命令，没有部署步骤。产物 `mathematical-core-verification` 包含 `result.json`、`junit.xml` 和 `pytest.log`；记录软件源 SHA、实际依赖版本、测试选择器与结果，保留 14 天，可重新运行生成。

仓库中保存的 [core-verification-result.json](core-verification-result.json) 是本地纯合成核验记录，`execution_kind` 为 `local`；它不表示远端 Actions 已运行。查看远端结果时，需核对对应运行及产物中的源码 SHA。

核验选择器如下：

- `tests/test_beat_editor.py::test_portable_engine_matches_python_operations_hrv_events_and_qrs`
- `tests/test_clinical_analysis.py::test_python_browser_parity`
- `tests/test_review_hrv_ranges.py::test_hrv_browser_backend_parity_and_day_night`
- 同文件的 `test_frequency_peak_and_energy_are_measured`、`test_gaps_are_not_interpolated_into_frequency`、`test_short_noise_and_unknown_clock_do_not_fabricate_metrics`
- `tests/test_rr_quality.py` 的 `test_hrv_frequency_never_interpolates_across_short_af_span`、`test_spectrum_rejects_invalid_time_axis_and_dc_bin_is_not_doubled`
- `tests/test_advanced_analysis.py` 的已知交替/Kors、测量与缓存、AF/平线/坏输入、削顶与 AF 边界、参数拒绝、RR 周期性及共享报告证据测试；精确函数名见 `result.json` 的 `checks`

心搏、事件索引和直方图采用测试中的逐项相等断言；HRV 时域及频谱对照使用现有测试规定的绝对容差 `0.0002`。高级分析的已知交替幅度、质量拒绝及文档断言是 Python 参考检查，不能当作浏览器高级算法对照。10 分钟默认数学 Demo 是交互示例；核验中的独立夹具另覆盖指定分段及缺失边界。以上证据仅覆盖列出的测试向量与断言，不表示所有配置、设备信号或临床准确性已经验证。

The same workflow also runs the three mathematical Demo tests for provenance, deterministic input, isolated browser storage, confirmation, stale revision, undo, and quota rollback. These are reported separately in `mathematical-demo-junit.xml`; they are not included in the 20 core tests shown in the local JSON.
