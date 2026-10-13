# Windows 医生离线便携版发布流程

本入口直接调用主项目 app.py 和 ecg_core，不维护另一套算法。首版包装版本为1.0.0，目标为Windows 10 x64；医院电脑架构和实机兼容仍待确认。系统浏览器用于界面，不捆绑Python开发环境、Chrome或Electron。

程序、来源与工作分离：程序在解压目录，固定M01示例在Sources/M01，医生工作在%LOCALAPPDATA%/CardioInsightDoctorEval/workspaces。新体验保留旧工作；每个工作区有独立进程、端口和Cookie。反馈仅含经允许的技术字段，禁止打包来源、整个数据库、报告或自由文字。

## 可重复构建

使用已提交、已复核的Windows x64工作副本和Python3.12.10，在隔离环境安装requirements-doctor-build.txt。该文件固定运行、构建及CI测试依赖；测试工具不进入医生包。构建器验证实际Git HEAD、生产来源清单和未提交的软件修改。

```powershell
python -m pip install -r requirements-doctor-build.txt
$releaseCommit = git rev-parse HEAD
python scripts/windows_doctor_build.py --output .\build\windows-doctor-1.0.0 --source-commit $releaseCommit --version 1.0.0 --verification-upgrade-version auto
```

输出必须为新目录。在项目内使用build、dist或releases子目录，保留旧代码与产物。后续发布传入新包装版本及--release-notes；用--source-root指定已验证的M01来源即可复用全天数据，禁止从任意病例目录递归拼包。来源版本目前仅支持M01-24h-v1；改变来源必须显式增版并更新兼容与验证要求。

独立分支推送触发windows-doctor-eval.yml；并入主线后可手动传包装版本、来源版本、基线提交和变更说明。构建在Windows运行，记录真实OS、架构、依赖、源提交和文件SHA256。CI-only升级夹具自动递增包装补丁号，复用同一EXE，不能当作第二正式版本。

## 产物与升级

full ZIP用于初次部署；software ZIP不含Sources或工作库；独立source ZIP含固定来源版本与校验。使用说明、版本说明、RELEASE.json、CONTENTS.json和SHA256SUMS.txt在软件包内，ZIP旁另有整个压缩包的.sha256。

升级前保存并停止本评估服务。新软件解压到新目录，保留旧程序、已登记的来源和用户工作区，不要求重传全天波形。程序在首次迁移前通过SQLite在线备份保存升级副本并检查完整性，记录数据库结构；检测到更高版本或不匹配结构时拒绝写入。首版不提供自动降级恢复按钮；恢复升级前副本需核验后创建独立工作区，不能覆盖当前库。

## 验证边界

关键源变更、过期依据、保存和备份保护必须通过后才构建。全天数学源默认86400秒、200Hz、8存储通道int16，原始DATA为276480000字节；四个其他展示导联沿用现有公式生成。所有源标注都是生成器练习参考，不能作为临床金标准。

全量回归与同运行器的冻结基线比较；既有失败和缺失公开夹具的设置错误保留记录，新增失败、丢失测试或通过项退化会阻止交付。浏览器验证使用CI安装的系统Edge，覆盖读数、返回、取消重试、保存重开、PDF、工作区隔离和同结构升级。

程序首次与暖读计时使用相同EXE、来源、控件及范围，多次报告中位数和范围，不宣称清空OS磁盘缓存。CI安装有开发工具；剥离PATH和验证加载DLL可以证明冻结运行路径，不能替代干净Windows 10、医院安全策略、签名接受或中文PDF字形与打印验收。当前包未购买签名证书，也不提供联网自动更新服务。

当前平台兼容修复仅涉及Windows内容校验与内置示例只读句柄、备份文件刷新与连接关闭及版本记录；诊断阈值、算法和原始波形保持不变。每版以构建报告和对应CI结果为准，不能沿用上一版成绩。
