---
name: CardioInsight Holter
description: 保留证据、时间和复核状态的临床心电工作台
colors:
  navy-950: "#0a1f2e"
  navy-900: "#102a3b"
  navy-800: "#173b4f"
  teal-700: "#0a7676"
  teal-600: "#0d9491"
  teal-500: "#15aaa4"
  teal-100: "#d9f1ef"
  teal-50: "#ecf8f7"
  ink-900: "#152834"
  ink-700: "#3c525f"
  ink-500: "#687d89"
  line: "#d8e2e7"
  line-soft: "#e6edf0"
  surface: "#ffffff"
  surface-alt: "#f4f7f8"
  canvas: "#e9eff1"
  ov-line: "#d7e3e8"
  ov-ink: "#243f4b"
  ov-muted: "#526773"
  ov-accent: "#078987"
  ov-paper: "#fbfdfd"
  hr-trace: "#207cba"
  rr-trace: "#52a72c"
  report-ink: "#111"
  report-rule: "#333"
  report-grid-major: "#b9b9b9"
  report-grid-minor: "#e4e4e4"
  report-context: "#dedede"
typography:
  page-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei UI", system-ui, sans-serif'
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.3px"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei UI", system-ui, sans-serif'
    fontSize: "13.5px"
    fontWeight: 700
    letterSpacing: "0.1px"
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei UI", system-ui, sans-serif'
    fontSize: "12px"
    fontWeight: 400
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei UI", system-ui, sans-serif'
    fontSize: "12px"
    fontWeight: 650
    letterSpacing: "0.1px"
  coordinate:
    fontFamily: "ui-monospace, monospace"
    fontSize: "10px"
    fontWeight: 400
  report-body:
    fontFamily: '"Songti SC", SimSun, "Noto Serif CJK SC", serif'
    fontSize: "10pt"
    fontWeight: 400
    lineHeight: 1.45
  report-title:
    fontFamily: '"Songti SC", SimSun, "Noto Serif CJK SC", serif'
    fontSize: "17pt"
    fontWeight: 700
    lineHeight: 1.4
  report-section:
    fontFamily: '"Songti SC", SimSun, "Noto Serif CJK SC", serif'
    fontSize: "12pt"
    fontWeight: 700
    lineHeight: 1.35
rounded:
  control: "8px"
  surface: "10px"
  dialog: "12px"
  overview-compact: "5px"
spacing:
  "4": "4px"
  "6": "6px"
  "8": "8px"
  "10": "10px"
  "12": "12px"
  "14": "14px"
  "18": "18px"
components:
  button-primary:
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 13px"
    height: "32px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-700}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 13px"
    height: "32px"
  button-dark:
    backgroundColor: "{colors.navy-900}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 13px"
    height: "32px"
  text-field:
    backgroundColor: "{colors.surface}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "9px 10px"
  navigation-item:
    rounded: "9px"
  status-pill:
    rounded: "999px"
    padding: "0 8px"
    height: "22px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.surface}"
  overview-action:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ov-ink}"
    rounded: "{rounded.overview-compact}"
    padding: "4px 9px"
  overview-lane:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.overview-compact}"
  report-sheet:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.report-ink}"
    typography: "{typography.report-body}"
    padding: "10mm"
    width: "210mm"
    height: "297mm"
---

# Design System: CardioInsight Holter

## Overview

**Creative North Star: "临床工作台"**

白色测量区、岩板灰文字、深海军蓝导航和青绿色控件构成现有视觉系统。界面为长时间复核安排紧凑的信息密度，依靠标题、边界、坐标和复核状态组织证据；原始波形与统计图是视觉主体。

这是对现有实现的记录。全局规则描述壳层和可复用控件；概览、房颤／房扑和波形密度的测量配色及布局单独限定范围。医院参考截图确定了本次概览页的图表语义与操作，没有将该页组合提升为所有页面的布局模板。

最终报告另有用户提供的医院纸质报告照片作为视觉依据：白色 A4 纸张、宋体文字、黑色细线与灰阶心电网格。该例外限定于报告纸面、打印与对应 PDF；报告编排控件继续使用工作台的界面字体和青绿操作语言。

**Key Characteristics:**

- 白色证据表面与深色导航形成稳定层级。
- 青绿色表达操作与选择，测量颜色保留各自含义。
- 细边框、紧凑间距和短标题支持并排核对。
- 复核状态有文字，坐标有单位，原始波形保留上下文。

### 依据与边界

记录日期：2026-09-17。依据是最终的模板、CSS 叠加顺序、运行时界面代码和本地验证截图。样式按 `app.css → clinical-workflow.css → beat-editor.css → clinical-ui.css → visual-refresh.css → overview-workbench.css` 加载；后两层决定本文件的主要数值，局部高优先级规则仍以源文件为准。来源为 [模板](templates/index.html)、[全局基础样式](static/css/app.css)、[临床流程样式](static/css/clinical-workflow.css)、[临床界面样式](static/css/clinical-ui.css)、[现有视觉令牌](static/css/visual-refresh.css)、[概览样式](static/css/overview-workbench.css) 和 [概览行为与绘图](static/js/overview-workbench.js)。

报告补记日期：2026-09-19。报告局部事实来自 [纸面样式](static/css/report-paper.css)、[纸面与图条渲染](static/js/report-paper.js)、[报告编排控件](static/js/clinical-ui.js)、[图条时间窗](static/js/report-engine.js) 和 [A4 PDF 绘制](ecg_core/report_paper_pdf.py)。该范围的方向约定保留于 [报告 surface brief](.impeccable/surfaces/static-js-report-paper-js.md)；下方概览／AF 截图不作为报告的验证证据。

沿用 [PRODUCT.md](PRODUCT.md) 中的克制、证据与明确状态等稳定约束；其中流程数量的旧表述不在本文件中固化。页面策略保留于 [概览 surface brief](.impeccable/surfaces/static-js-overview-workbench-js.md)。本文件没有改动产品文档或页面实现。

[design.json](.impeccable/design.json) 提供阴影、动效、断点和独立组件预览。色条为由已提取颜色合成的 OKLCH 预览色阶，不是新增产品令牌；组件预览不承载病例数据或业务事件。

### 截图来源

以下七张 PNG 均是本次实现的本地浏览器验证输出，保留在 `.impeccable/review/`；它们是验证附件，不是浏览器打包资产。患者信息、数值和片段仅属于截图中的验证状态，不构成设计令牌或临床结论。本次工作没有新增需要投放到页面的栅格资产。

| 文件 | 已知来源与用途 |
| --- | --- |
| [desktop.png](.impeccable/review/desktop.png) | 本地病例总览，1920×1080 验证视口；宽屏四条纵向测量 lane。 |
| [user-1280.png](.impeccable/review/user-1280.png) | 同一总览路径，1280×720 验证视口；HR／RR 两列及波形对照。 |
| [mobile.png](.impeccable/review/mobile.png) | 总览，390×844 验证视口；缩窄壳层与纵向内容。仅证明该表面的窄屏表现。 |
| [af-desktop-final.png](.impeccable/review/af-desktop-final.png) | 最后一轮 AF 工作台宽屏截图，1920×1080 验证视口。 |
| [af-user-1280.png](.impeccable/review/af-user-1280.png) | 最后一轮 AF 工作台 1280×720 验证视口；Lorenz、事件表、四段 RR 并排。 |
| [density-final.png](.impeccable/review/density-final.png) | Demo 模板编辑页的局部滚动视口；R 峰对齐、正负幅值及时间轴完整可见。 |
| [demo-af.png](.impeccable/review/demo-af.png) | 较早的 Demo 表单展开状态，用于字段和状态证据；其表单常开布局已被最终原生 details 折叠方式替代。 |

截图由当前构建产生，详细交互与验证范围见 [validation.md](.impeccable/review/validation.md)。截图不是完整产品的可访问性或临床有效性认证。

## Colors

主色是克制的临床青绿，中性色为带蓝调的岩板灰；测量区保持浅色背景，颜色首先承担操作和数据含义。

### Primary

- **临床青绿**：沿用 `teal-600` 作为全局选择、焦点和控件标记；`teal-700` 用于浅色表面上的动作文字，`teal-500` 支持导航与小型状态标记。
- **浅青绿**：`teal-100` 和 `teal-50` 用于当前项、选择与悬停背景。主按钮现有渐变由 sidecar 保留，不能用单一背景色假装它已被扁平化。
- **概览青绿**：`ov-accent` 只属于概览控件和焦点的局部令牌。

### Secondary

- **心率蓝**：`hr-trace` 是本次概览的全程／小时 HR 曲线颜色。
- **RR 绿**：`rr-trace` 是本次概览及 AF 的 RR 点列颜色。与 HR 配对使用时，同时保留图名、坐标和单位。

**The Overview Measurement Key Rule.** 概览中的蓝色与绿色分别绑定 HR 和 RR；Lorenz 分类色、ECG 心搏类型色和密度色阶各有自己的图例，不能互相替代。

**The State Has a Label Rule.** 状态不能仅靠颜色区分；片段表、确认操作与可撤销修改保留明确状态文字和作用范围。

### Neutral

- **深海军蓝**：`navy-950`、`navy-900`、`navy-800` 支撑全局壳层和深色动作。顶部与侧栏保留现有细微渐变。
- **岩板文字**：`ink-900` 表示主文字，`ink-700` 表示控件与次层内容，`ink-500` 表示元信息。
- **证据表面**：`surface` 是卡片和输入背景，`surface-alt` 是页面底色，`canvas` 是基础画布令牌。细边框使用 `line` 与 `line-soft`。
- **概览表面**：`ov-line`、`ov-ink`、`ov-muted` 与 `ov-paper` 是局部测量区的细边界、标题、轴标和近白底色。

### 局部数据色例外

波形密度使用黑底及绿 → 黄 → 红色阶；颜色表示同一网格的重复次数，以 `log1p(count) / log1p(max)` 显示，空网格为黑色。R 峰对齐在中央，横轴保留 −1 s／0／+1 s，纵轴保留正负幅值。它是模板编辑页的数据编码，不是新的深色主题，也不是 RR 散点图。

交互复核波形保留现有近白底、浅红网格和深色波形。事件待复核／确认、心搏类型及选区采用已有文本与局部标色；这些状态色不能覆盖大面积原始证据。

### 报告纸面例外

报告浏览器纸面复用 `surface` 白底，以 `report-ink` 绘制文字和波形，以 `report-rule` 分隔检查、统计和结论区域。SVG 心电网格使用 `report-grid-minor` 和 `report-grid-major`，上下文条的当前时间段使用 `report-context` 灰色块；这些令牌只描述报告 HTML／SVG。PDF 以黑色文字与波形、灰阶主／次网格及灰色上下文选区实现同一纸面语言，灰度数值由 PDF 绘制器独立定义。

**The Monochrome Report Rule.** 医院参考照片确定报告纸面使用白、黑与灰阶；青绿色保留在纸面外的操作、选择和焦点中。这是报告范围的既定变体，不扩展为全局去色规则。

## Typography

正文和控件使用已安装的平台界面字体，中文回退到苹方或微软雅黑。Windows 的 HTML 界面优先使用 Segoe UI Variable Text / Segoe UI；Canvas 绘图沿用代码中的 SF Pro Text / PingFang SC / Microsoft YaHei UI 栈。两处不是统一的远程字体系统。

层级由字号、粗细和位置建立，没有独立的装饰性 Display 字体。前置信息中记录的 body 是反复出现的表格／控件正文尺度，并不声称根元素设置了统一字号或行高。

- **页面标题**：用于页面级功能识别；沿用 frontmatter 的 page-title。
- **容器标题**：沿用 title；概览测量 lane 的短标题在局部规则中使用较紧凑的字号（12px，部分视口 11px）。
- **正文与按钮**：正文与主控件集中在 body / label；功能内容保持中文直述。
- **坐标与数值**：时间坐标使用 coordinate；统计值和时段采用等宽数字，避免数值变化引起对齐跳动。
- **图内轴标**：现有 Canvas 多使用 10px UI 字体，窄屏降低刻度数量。该值是当前测量组件的事实，不应推广为一般表单、说明或状态文字的字号。

现有零散微小标签、装饰性 eyebrow / kicker 和不一致的字形图标没有被提取为新页面应继承的类型规则。

### 报告纸面字体

浏览器纸面正文、主标题和节标题分别采用 `report-body`、`report-title` 和 `report-section`；宋体栈来自医院纸质报告参考。检查信息和统计块使用 9pt，小时表格与页脚使用 7pt，结论与续页保持 10pt。纸面图条 SVG 当前显式声明 `"Songti SC", SimSun, serif`，未包含正文栈的 Noto 回退；PDF 由 [字体注册入口](ecg_core/report_pdf.py) 使用 `STSong-Light`，不把浏览器字体栈冒充 PDF 嵌入字体。

**The Report Font Scope Rule.** 宋体仅用于报告文档与纸面图条；编排字段、保存／导出动作和应用导航沿用平台界面字体。报告宋体是已确认的局部字体选择，不能据此替换整个工作台的字体。

## Layout

全局以固定顶栏、左侧导航、可滚动页面和有明确边界的工作区组织内容。顶栏沿用 56px；侧栏常规为 76px，在既有较窄桌面断点缩至 70px。一般页面最大宽度为 1720px，常规内距为 14px 20px 24px；局部工作台可为测量内容调整内距。组件间距使用已存在的 4／6／8／10／12／14／18px 步进。

### 概览表面

完整直方图位于工作区上方，随后是全程与小时 HR／RR、原始波形、波形导航。右栏先为片段列表与 Lorenz 组成的散点图复核，再为结论统计；窄屏视觉与 DOM 顺序保持一致。病例信息与波形设置收在原生 disclosure 中。共享时间选区连接这些测量区域；这项关系属于概览的操作模型。

- **大于 1500px**：四条测量 lane 纵向排列；右侧统计／Lorenz rail 常规宽度取可用空间约 31%，且保留最小宽度。
- **1001–1500px**：HR 与 RR 各占一列，全程在上、小时在下；散点复核区内部列表滚动，画布占用控件下的剩余空间，不保留与画布脱节的固定最小图框高度。
- **不大于 1000px**：主工作区改为单列，证据 rail 下移；不将所有图压到同一行。
- **不大于 680px**：概览解除继承的桌面最小宽度，侧栏缩至 52px，控制栏换行，字段单列，坐标刻度简化，内容纵向滚动。此规则以当前活动概览为边界，其他页面的窄屏能力未在本次确认。

### AF / AFL 表面

宽屏使用全程 RR、Lorenz／片段列表、四个有数据覆盖的 15 分钟 RR 面板及原始波形。1001–1500px 采用 Lorenz／事件表／季度 RR 三列，季度面板为两列，事件表内部滚动。选中片段的表单采用原生 details；生成表单时大于 1500px 默认展开，其余宽度默认折叠，用户可手动展开。

1280×720 的最终验证视口可对照四段 RR 与 II、V1 波形，完整 V5 区域仍需下滚。保留页面滚动；这个视口限制不是需要后续页面复制的布局指标。

### 报告纸面与编排表面

纸面采用 `report-sheet` 的固定 A4 纵向尺寸与页内留白；PDF 使用同一纸型和内距。浏览器打印的页级边距为零，留白由纸张内距承担。首页将检查信息、双列分析统计和结论组织为细线框区，后续为小时统计与全宽图条；页眉保留身份与审核状态，页脚保留用途说明及总页码。

每张图条页有三个纵向槽位，浏览器槽位间距为 4mm：1–3 导联占一个槽位，因此常用 II／V1／V5 图条每页最多三张；4–6 导联占两个槽位；7–12 导联独占一页。保持所选顺序，剩余槽位不足时另起一页。

不大于 900px 时，报告动作栏换行、事件列表单列，纸面保留实际宽度并在报告容器内部横向滚动。纸面从容器左侧开始排列，确保窄屏可以到达整张纸；不通过压缩 A4 或把全页横向撑开来容纳报告。报告导航保留独立横向滚动。不大于 600px 时隐藏顶栏搜索和品牌附加文字；这些适配仅在报告页激活时作用于壳层。

## Elevation & Depth

深度来自表面色、细边框和轻阴影。现有壳层、主按钮、弹窗仍使用渐变、阴影以及局部条件模糊，因此不能将当前系统描述为“全站无渐变”或“全站无阴影”。测量图框主要通过细线分隔，操作浮层用更明显的投影区分。

sidecar 保存实际阴影：通用卡片的低层投影、主按钮的小型青绿色投影、菜单与设置面板的浮层投影，以及原生 dialog 的高层投影。标准按钮／导航状态变化约为 0.13–0.15s，页面已有 0.18s 淡入。现有减少动态效果规则只覆盖部分行为；本次没有据此声明全局完全合规。

**The Evidence Surface Rule.** 白色图表和 ECG 纸张保持不透明、坐标可读；模板编辑的黑底密度是明确的数据视图例外。壳层材料不扩展到测量背景。

报告纸面保持平面：浏览器用浅灰外围画布、纸张边界与页间空隙区分页，未添加纸张投影；打印移除屏幕预览边框。纸内用细线和留白建立层级。

## Shapes

常规按钮／字段为小圆角，卡片略大，dialog 更柔和。概览动作和测量 lane 使用较紧的圆角，便于密排；统计、直方图和波形容器沿用现有 8px 局部圆角。边界通常是 1px 细线。圆形与全圆角胶囊只承担头像、状态和微小标记等既有角色，不作为整个页面容器的通用形状。

报告纸张和纸内框区为直角矩形，不继承卡片圆角。心电网格采用 1mm 小格与 5mm 主格的标尺关系；报告设置字段和图条编辑动作仍保留 5px 界面圆角。

## Components

### Buttons

按钮用短动词表达动作。通用按钮高 32px，使用 label 字体与 control 圆角；主动作保留现有青绿渐变和白字，次动作白底细边，深色动作使用 navy。禁用态降低不透明度并保留不可用指针。键盘焦点以 2px 青绿色轮廓和 2px 偏移显示。

概览动作是紧凑局部变体：最小高度 28px、小圆角、白底；按下／选择状态为概览青绿底配白字。lane 内的“操作”更紧凑，其存在保证上下文菜单有显式入口。

### Inputs / Fields

字段使用白底细边，标签位于字段旁或上方。一般对话框字段沿用 8px 圆角和 9px 10px 内距；概览／AF 字段为 5px 圆角和 7px 8px 内距。两者是实际存在的局部变体。概览 caret 与焦点使用青绿；错误信息以文字显示在表单区域。

### Navigation

左侧导航采用 SVG 线形图标与文字，当前项同时有青绿底色、外框和左侧标记。病例任务导航以文字和当前／待复核状态表达位置。这里记录的是导航形态，不固化业务步骤的数量。

### Chips / State

状态胶囊以短文本配浅色底展示待复核、确认、异常或中性状态。紧凑高度仅用于辅助状态标记。可交互选择仍采用按钮或字段语义。

### Cards / Measurement Containers

通用卡片保持白底、细边、低投影和紧凑标题。测量容器进一步压缩标题与间距，宽度允许收缩而不裁掉关键操作。图表通过 Canvas 绘制，带有图名、单位和对应操作入口；sidecar 中的容器预览仅示范外框，不提供病例曲线。

### Context Menus / Dialogs

HR、RR 与 Lorenz 菜单由“操作”按钮、真正的右键及 Shift+F10 进入。菜单使用手动 popover，固定定位并限制在视口内；分组由原生 details 展开。Escape 与外部点击关闭。对话框使用原生 dialog、清晰标题和底部动作区；批量修改先展示作用范围。

### Episode Disclosure

AF 选中片段表单以带摘要的原生 details 呈现，摘要保留时间和复核状态。展开后提供起止、类型、复核状态、备注及保存动作；在中等桌面宽度下可内部滚动。该密度处理限定于 AF 编辑器。

### Report Paper / Evidence Strips

纸面呈现已选证据，编辑入口保留在纸外。导联方案提供常用三导联、全部十二导联和自选导联；新入报默认设置与单条设置分别标明影响范围。图条用可见文字“回看”“上移”“下移”“移除”操作，首末项对应的移位按钮禁用。

时间窗默认 7 秒；按实际可用心搏位置扩展到至少 5 搏。记录本身不足 5 搏时显示实际数量和不足提示。每条纸面标明实际时长与根据该时长计算的时间标尺（mm/s）；时间窗延长后不保留不真实的固定走纸速度标注。

未验证电压校准时，逐导联自适应幅度，脉冲示意旁标记设备单位 `u`，并明确写出“电压未校准”；它不能作为跨导联电压比较的固定增益。仅校准标记明确为真时使用 mm/mV；校准波形超框时提示降低增益。图条保留心搏分类、HR／RR、导联名称以及 II 导联上下文条中的时间选区。

长图注在图条上显示编号和首行摘要，完整内容移到“图条说明（完整图注）”续页，每页最多 44 行；原图注不被删改。结论首页最多 15 行，超出内容以每页最多 48 行继续，保留签名区域。小时统计每页最多 25 个时段，总计只在最后一张统计页出现。浏览器、打印与 PDF 共享这些分页规则，各自使用对应的渲染实现。

## Do's and Don'ts

### Do:

- **Do** 保留深色导航、浅色证据表面与青绿操作的既有关系。
- **Do** 为测量保留名称、单位、时段与选择状态，并用明确文字表达复核状态。
- **Do** 根据所处表面使用全局令牌或已命名的概览局部令牌。
- **Do** 给高频图表操作保留可见入口和键盘入口。
- **Do** 让工作区通过重排、局部滚动与按需展开适应空间。
- **Do** 在报告纸面使用已确认的宋体、灰阶网格与固定 A4 几何，纸外保留青绿操作。
- **Do** 在报告中显示实际时间标尺、可用心搏数与幅度单位，并把长图注完整保留在编号续页。

### Don't:

- **Don't** 将医院概览截图的整页组合推广为其他产品页面的固定模板。
- **Don't** 把 HR／RR 测量色、心搏分类色和密度次数色阶混为同一状态色。
- **Don't** 将黑底密度图扩展为全局主题，或把壳层模糊叠到原始证据上。
- **Don't** 把验证截图或截图中的医学数值加入前端资产或设计令牌。
- **Don't** 继承未提取的微小装饰标签，或把本页窄屏验证解释为全产品已通过验收。
- **Don't** 将报告宋体和单色纸面推广为应用壳层的新字体或新配色。
- **Don't** 将未校准设备单位标为 mV，或把延长后的图条仍标为未经计算的固定走纸速度。
