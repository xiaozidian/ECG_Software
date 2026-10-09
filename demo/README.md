# 纯数学交互 Demo

公开 Pages 每次从冻结软件清单逐项校验并构建。此次纯数学快照另保存在 `docs/demo/0.12.9-doctor-evaluation.20261009/`；历史 Demo 目录不作为新构建输入。唯一输入是本次用数学公式重新生成的 `math-4314-001`：200 Hz、8 个存储通道、10 分钟。波形由高斯分量与正弦基线组成，心搏位置和示例 N/S/V/噪声标签由确定性生成器给出。这些标签用于演示交互，不是疾病金标准、患者诊断或算法性能证据。

构建只读取软件代码和发布清单，不读取既有病例、数据库、患者资料、源报告图片或旧 Demo 数据。`mathematical-source-manifest.json` 记录数学参数、生成器 SHA、两个新资产 SHA、实际复制资源白名单及生成副本的转换。冻结的 94 个生产文件保持原字节；页面副本仅转换浏览器存储命名空间、数学输入的本地写入权限与 ST 保存入口和提示。

模板库和密度分布使用当前分析版本及完整选集。模板、心搏编辑、人工复核和报告草稿仅存于当前浏览器的独立 `cardioinsight-public-math-4314-v2` 命名空间。取消不保存；存储失败会报错；清除浏览器站点数据会丢失这些修改。没有远端临床写入、用户间共享或桌面数据库。更换分析版本仍使旧依据失效，报告游标修改必须明确应用或放弃后保存。

可体验双模板视图的即时点选及 F / Escape 十二导联放大恢复、形态分组与保存重开、ST 导联和人工复核、报告类别及入报范围草稿、连续 HRV 与末尾 A4 预览。PDF 操作为浏览器打印预览；不代表桌面原生 PDF、备份恢复或医院病例验收。设备电压、导联采集映射及医学有效性未据此验证，保留研究提示。

构建依赖 Python 3、Jinja2 和标准库；无需 Flask、NumPy 或 SciPy。目标目录必须不存在，以保护已有产物。

```sh
python -m pip install Jinja2
python scripts/verify_public_release.py
python scripts/build_static_demo.py --output build/pages
python -m http.server 8871 --bind 127.0.0.1 --directory build/pages
```

`_headers` 保留 CSP、权限、引用来源及内容类型规则，供兼容静态平台使用；GitHub Pages 不通过该文件配置响应头。

```sh
python -m pytest -q tests/test_static_demo_builder.py
npm install --no-save playwright
npx playwright install chromium
node tests/public_demo_browser.cjs
```

浏览器脚本默认读取 `http://127.0.0.1:8871`，只创建自己的无界面浏览器并在结束关闭，结果和截图写入 `build/public-demo-evidence`。可用 `ECG_DEMO_URL`、`ECG_DEMO_EVIDENCE`、`ECG_PLAYWRIGHT_MODULE` 与 `ECG_CHROME` 指定测试地址、证据目录、Playwright 模块及浏览器可执行文件。脚本不操作已有浏览器标签；请自行启动和停止测试用静态服务。
