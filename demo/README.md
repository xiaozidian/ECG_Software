# 在线 Demo 专属源文件

本目录只保存 GitHub Pages / Cloudflare Pages 在线演示所需的浏览器 API 和经确认可公开的单病例资源。正式开发版不读取本目录。

- `static/js/demo-api.js`：纯浏览器、只读的单病例 API 适配层。
- `static/demo-data/`：在线 Demo 的“徐有德”10 分钟病例片段与逐搏资料。
- `../scripts/build_static_demo.py`：先复制正式版公共界面资源，再把本目录内容叠加到独立发布目录。

隔离约定：

1. `app.py`、`ecg_core/`、正式版 `templates/` 和 `static/` 不得依赖本目录。
2. 本目录不得包含 `config.json`、`.env`、本地病例根目录、数据库或完整源 DATA。
3. `build/pages/` 和 `docs/demo/` 都是生成结果；不要直接修改其中的文件。
4. 公开病例发生变化时，应先修改或重新导入本目录的源资源，再运行静态构建和测试。
