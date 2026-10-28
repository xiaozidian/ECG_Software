# 共享核心、界面与平台适配

共同源码只有一份：`ecg_core` 的算法模块、`static` 的适用界面与 `templates`。`shared-source.json` 定义所有权和白名单，`scripts/shared_source.py` 从这些原文件生成版本化源码包，不维护另一套手工拷贝。

`core-<hash>` 标识核心源码，`ui-<hash>` 标识共同界面，完整 `source_fingerprint` 还覆盖构建配方。`ecg_core/core_contract.py` 统一当前导入格式的200Hz/8存储通道假设；它不是设备标定证据。平台版本如doctor1.0.4与核心版本分开记录。

| 交付 | 共同来源 | 执行能力 |
|---|---|---|
| 本机网页 | 同一核心源码及共同界面 | 本机Python后端；病例与独立工作库仅本机 |
| Windows医生软件 | 同一核心源码及共同界面，叠加必要平台适配 | Windows原生Python打包；保留来源租约、脱敏及医生工作区 |
| GitHub数学网页 | 同一包中的共同界面及数学适配器 | 静态浏览器数学演示；不能执行完整Python算法或真实病例后端 |

同一个核心来源标识不意味着三个平台执行能力相同。浏览器数学适配器仍是受限实现，不能拿它的摘要冒充完整后端结果。要让静态网页运行完整核心，需要另行设计后端或浏览器运行时，本机制不引入新的云服务。

## 构建与核对

使用现有Python环境；本工具不安装软件、不联网、不读取病例。

```sh
python scripts/shared_source.py build --output build/shared-source.zip
python scripts/shared_source.py check build/shared-source.zip --target .
python scripts/build_static_demo.py --shared-bundle build/shared-source.zip --output build/pages
```

输出目录/ZIP必须是新路径，已有产物不会被覆盖。源码包只接受算法代码、界面、模板、内置术语和明确列出的构建配方，排除病例、原报告、医院截图、工作数据库、缓存、虚拟环境及Git对象。数学网页中的每个共同JS/CSS文件与包内原文件字节相同，不做构建后字符串补丁；适配器和模板渲染另记来源。数学草稿的浏览器存储命名空间随来源指纹变化。

现有Pages工作流已接入上述机制。它构建的是数学网页；部署结果应核对对应提交和 `mathematical-source-manifest.json`，不能把源码提交直接算成网页已经上线。

## Windows原发布链路的输入

doctor1.0.4的既有适配基线是 `3ee41f442c486a9ad6391af4943899b3914b17ba`。与当时主线相比，29个算法模块的Git blob相同；平台差异包括版本配置、来源身份、存储/备份及医生启动器。这些适配不能被普通UI覆盖操作舍弃。

```sh
python scripts/shared_source.py stage build/shared-source.zip \
  --profile windows-doctor \
  --adapter-root PATH_TO_VERIFIED_WINDOWS_CHECKOUT \
  --base platforms/windows-doctor/base-3ee41f44.json \
  --output NEW_WINDOWS_STAGING_DIRECTORY
```

命令只读原Windows源码，在新构建目录组装共同包和平台适配，不读取或搬运病例、医生工作区或已有安装。已有共同文件必须与新包或显式固定基线一致；未知模块或独有改动会阻止组装，保留冲突供合并，不能靠重新生成“基线”批准丢弃修改。

来源租约、连接管理、脱敏与存储适配按原文件保留。仅两个必要构建适配可有可追溯修改：配置引用共同采样/通道常量；医生打包资产列表增加 `shared-source-build.json`。输入/输出适配哈希写入 `platform-source-build.json`。未来更新平台基线时，应先从已核实的提交更新基线清单，再独立做平台接口与原生验收。

组装不等于生成或验收新的EXE。原发布流程须在Windows使用自己的构建/升级验证，检查包内核心、UI指纹及适配哈希；已有doctor1.0.4成品不会因此自动包含新界面。当前任务不构建竞争安装包，不改P01数据包，不自动安装升级医生工作区。

## 验证范围

`tests/test_shared_source.py` 检查可重现打包、共同界面字节一致、数学输入来源、保留适配及拒绝独有修改/篡改。`tests/test_scatter_report_invariants.py` 检查类别绘图/命中集合和1/3/12导联的样本坐标、行高及增益不变量；浏览器检查另行验证实际CSS与数学草稿保存重开。它们不操作PDF，不代表临床、设备或医院Windows验收。
