# CardioInsight Holter

心电研究与工程工作站源码。共同算法、适用界面与平台适配的来源规则见 [共享源码说明](SHARED_SOURCE.md)；核心和界面由内容指纹版本化，平台安装包版本单独记录。

本机网页和Windows医生软件使用Python核心。GitHub Pages及既有Cloudflare网页是独立数学演示，没有完整Python后端或真实病例工作区；共同源码来源不能用来声称三端能力或临床结果已经等价。

当前交互包括：模板散点初始显示全部类别，显式选择类别后不绘制其他类别，清除恢复全量；报告1/3/12导联共用时间窗、固定行高和幅度域，增加导联只增加纵向空间。原搏小图/R标注提供心搏类型菜单，波形空白处提供波形操作；报告波形保持只读。房颤/房扑分段入口属于全程RR区域，逐搏A/C标记与分段操作分开。

## 数学网页构建

在已有Python/Jinja环境中运行：

```sh
python scripts/shared_source.py build --output build/shared-source.zip
python scripts/shared_source.py check build/shared-source.zip --target .
python scripts/build_static_demo.py --shared-bundle build/shared-source.zip --output build/pages
python -m http.server 4173 --bind 127.0.0.1 --directory build/pages
```

共同JS/CSS按字节来自同一包，数学适配器单独标识。载荷由固定种子和数学函数生成，600秒、200Hz、8存储通道；不读取病例、工作库或医院资料。修改只保存在浏览器的来源版本命名空间。构建完成、网页实际部署、Windows原生包验收需分别核实，不能互相代替。

既有 [GitHub Pages](https://xiaozidian.github.io/ECG_Software/) 与 [Cloudflare数学Demo](https://ecg-software.pages.dev/) 的实际部署版本应各查自身清单；本仓库的Pages工作流不更新其他托管服务。

## 本机和Windows

使用`requirements.txt`的已有环境，运行 `python app.py --data-root YOUR_LOCAL_DATA_ROOT --host 127.0.0.1 --port 8765 --no-browser`。原始来源和独立工作库保持分离；更新源码或软件不得覆盖病例、配置及工作数据库。平台组装命令、Windows固定基线与冲突保护见[共享源码说明](SHARED_SOURCE.md)。

公开范围仅代码、非敏感文档和纯数学输入；不包含病例、身份映射、真实波形/报告、医院素材、工作库、密钥、缓存或未经验证的二进制。历史冻结版本说明保留在 `docs/releases/`，其成绩不自动适用于后续源码或成品包。

设备采样/导联映射、电压校准、医院纸速/增益/模板规范及医生金标准仍须独立核验。屏幕设备单位与显示增益不是物理mm/mV标定，本项目不据此声称临床验收通过。
