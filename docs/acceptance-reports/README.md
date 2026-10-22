# 当前验收状态

更新日期：**2026-10-22**。本页仅列当前交付、步骤状态和未关闭项。

## 当前交付

主目录配对程序为 `2026-10-22-module-status`。系统诊断已移除构建与许可详情；模块清单改为检查实际路由、数据表、依赖和只读查询响应，显示软件可用／异常／未启用／无检测权限／未检测及检测时间。内部ASGI调用沿用当前会话和进程密钥，不启动设备、不写业务数据；最多4项并行、每项3秒超时，刷新失败清除旧结果，硬件另验。39项后端和浏览器／实际QA桌面各4组通过，18模块均实测HTTP200；异常、停用、权限和超时均有故障用例。主目录配对已备份更新，schema23及用户库保持，关闭重开生效；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-module-status/verification.json)。

此前主目录配对程序为 `2026-10-22-maintenance-header`。备份与维护的状态／刷新操作组保持与标题居中，标题行下方增加12px留白，避免按钮底边贴分隔线。仅修改局部CSS；前端及正式／QA构建通过，浏览器与实际QA桌面各3组／4种明暗及大小布局通过，中心偏差0、分隔间距12px，刷新及失败重试正常，无维护写请求。主目录配对已备份更新，后端字节和用户库保持，关闭重开生效；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-maintenance-header/verification.json)。

此前主目录配对程序为 `2026-10-22-maintenance-simple`。备份与维护参照旧版精简为备份数据库、整理数据库、清理记录文件三项，额外仅保留备份记录／校验和默认收起的管理员诊断。移除WAL、优化、恢复演练、过期备份／临时文件清理及维护历史界面入口，既有API与记录保持兼容。25项后端、浏览器及实际QA桌面各5组／4布局通过；实际备份、校验、整理及日志清理均在隔离库完成，保留当前／近期日志及临时文件，诊断仅展开时请求。主目录配对已备份更新，schema23及用户库保持，关闭重开生效；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-maintenance-simple/verification.json)。

此前主目录配对程序为 `2026-10-22-about-maintenance`。“帮助 → 关于软件”只保留名称、版本和版权，版权按开发合同第8.1条归湖北华祥地质环境检测科技有限公司。诊断移至“系统管理 → 备份与维护”，仅maintenance.write可查看及请求；普通启动／关于页不做完整诊断，只读审计员保留备份查看。25项后端、浏览器及实际QA桌面各6组／4布局通过，含刷新、失败恢复和拒绝越权。schema23及用户库保持，根目录配对已备份更新，关闭重开生效；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-about-maintenance/verification.json)。

此前主目录配对程序为 `2026-10-22-offline-help-images`。离线帮助保留33个精简主题、约8千字符正文，仅在方法参数、分析谱线、预录样号、色散定位、样品分析和标准曲线6处加入新版局部示例截图，图片合计约124KiB。配图随程序离线提供，可点击或回车放大、关闭或Esc返回；其余主题保持短文字。后端5项、浏览器与实际隔离QA桌面各7组通过，含33主题、6图、13旧地址、检索、离线阅读、大小明暗窗口及放大图，未知图片键和外部URL不能加载。配对程序已备份更新，原CHM及用户库保留，安装包未更新。见[本批验证](S24/artifacts/2026-10-22-offline-help-images/verification.json)。

此前主目录配对程序为 `2026-10-22-offline-help-compact`。离线帮助按旧CHM“使用手册 → 软件介绍 → 常用操作”重排为33主题，正文由19242缩至8065字符，减少58.1%。保留必要步骤、参数表和当前控件名称；曝光合入方法参数，校线／质控／合并结果合入样品分析，去掉重复解释。已有库重开后停用被合并的目录项，13个旧主题地址及错误码仍兼容。后端5项、浏览器与实际隔离QA桌面各5组通过，各2种明暗／大小窗口无溢出。主目录配对已备份更新，原CHM及用户库保留，安装包未更新。见[本批验证](S24/artifacts/2026-10-22-offline-help-compact/verification.json)。

此前主目录配对程序为 `2026-10-22-offline-help`。软件内离线帮助已参照旧版DIRECT.CHM及当前控件改写为36主题／8章，正文约1.9万字符，补齐入口、编号步骤、参数用途、后续结果及故障处理。支持段落目录、参数表、继续阅读和全文检索；已知错误码优先定位业务主题，修复无匹配时搜索框隐藏及过期搜索响应覆盖。已有库重开程序自动更新产品帮助，无新schema迁移。后端5项、浏览器和实际隔离QA桌面各9组验证通过，36主题均可读，明色大窗口／深色最小窗口无溢出。配对程序已备份更新，原CHM和现有用户库保留，安装包未更新。见[本批验证](S24/artifacts/2026-10-22-offline-help/verification.json)。

此前主目录配对程序为 `2026-10-22-method-single-save`。已删除方法页底部重复的“保存方法”按钮及整条保存栏，仅保留上方工具栏“保存”。TypeScript/Vite及正式/QA Tauri构建通过，浏览器与实际桌面各5项、各2种明暗/大小窗口布局验证通过；顶部保存、无效输入保护及历史版本保持正常。配对程序已备份更新，保留现有工作台布局、后端与用户库；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-method-single-save/verification.json)。

此前主目录配对程序为 `2026-10-22-workspace-bottom-align`。工作台双栏时，左侧运行消息卡片底边与右侧服务通道卡片底边对齐；消息数量增减、筛选及底栏展开／收起均保持对齐，较多记录在卡片内部滚动。1120px及以下保留原上下排列。只修改工作台局部CSS，内容、业务和用户数据保留；TypeScript/Vite、正式与QA构建、浏览器和实际桌面各4组／36布局通过。配对程序已备份更新，重开生效；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-workspace-bottom-align/verification.json)。

此前主目录配对程序为 `2026-10-22-workspace-log-levels`。恢复工作台原有“当前运行方法＋运行消息”及右侧信息排布，复用rebuild消息卡片并保留本项目真实服务状态和权限；工作台既有样式保持。全局底栏首次升级默认收起，之后记住用户选择。精简保留完成／警告／错误，默认显示普通信息，详细显示全部记录及真实来源／任务／状态细节；分类计数同步级别与文字过滤。后端61项、前端15项、浏览器与实际桌面各16组检查及50入口布局、16设备调试布局通过；实际分析消息验证三级差异。后端与schema23保持，用户库及当前窗口保留，根目录配对程序已备份更新；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-workspace-log-levels/verification.json)。

此前主目录配对程序为 `2026-10-22-method-save-hint`。已移除方法保存栏的版本及保存后提示，仅保留右侧“保存方法”按钮。TypeScript/Vite、正式/QA Tauri构建通过；浏览器及实际桌面各5项检查、明色大窗口/深色小窗口各2种布局通过，保存与无效输入保护正常。配对程序已备份更新，后端及用户库保持；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-method-save-hint/verification.json)。

此前主目录配对程序为 `2026-10-22-global-messages`。信息记录已移至跨页面底部，保留“常规信息／通信命令”两个分类及日志级别、过滤、暂停显示、清屏；支持收起与高度调整。接入现有采集、分析和设备公开事件，不记录HTTP请求。清屏不删除持久日志或审计，暂停不停止任务。后端61项、前端15项、浏览器及实际打包WebView2各14组检查通过，各25入口在大窗口明色／最小窗口深色共50布局通过。配对程序已备份更新，schema23及用户库保留；安装包未更新。见[本批验证](S24/artifacts/2026-10-22-global-messages/verification.json)。

此前主目录配对程序为 `2026-10-21-page-spacing`。按蒸发摄谱参考图，将各页面主标题下方的主内容间距统一为24px，共用同一变量；去掉色散任务额外的16px顶部留白，保留原有左右缩进与操作归属。TypeScript/Vite、正式/QA构建通过；生产静态预览与实际桌面各25入口、明色舒适1440×1000及深色紧凑1060×680各50布局通过，均测得24px；已完成色散任务及列表收起/展开检查通过。配对程序已备份更新，后端、既有图标和用户数据保持，安装包未更新。见[本批验证](S24/artifacts/2026-10-21-page-spacing/verification.json)。

此前 `2026-10-21-device-debug-merge` 将软件参数、设备参数、调试对中、汞灯调试合并为一个入口，共25个正式入口；后端32项及浏览器/桌面验证通过。该批切换限制已由最新布局批次取消。见[合并验证](S24/artifacts/2026-10-21-device-debug-merge/verification.json)。

此前配对程序为 `2026-10-21-icon-size`。顶栏与展开菜单图标从24px缩为20px；顶栏点击区域保持36×34px，菜单按钮至少42px高，文字与原始高清图标保持。浏览器和实际桌面各4组/各4种明暗与大小窗口验证通过，打开方法仍直接弹出选择框。配对程序已备份更新，后端字节、schema23、其他源码与用户数据保留，安装包未更新。 见[本批验证](S24/artifacts/2026-10-21-icon-size/verification.json)。

此前配对程序为 `2026-10-21-toolbar-actions`。左侧一级导航改为纯文字，展开菜单图标保留。顶栏打开方法直接弹出方法选择框，确认即载入并设为当前方法；新建/另存为直接打开表单并可完成建立，参数/谱线直达，预录样号聚焦输入并支持回车录入。取消、失败重试、未保存内容和重复请求保护保留，写入型方法按钮按权限显示。浏览器/实际桌面各9组与各4种布局通过。配对程序已备份更新，后端字节、schema23、图标资源和用户数据保留，安装包未更新。 见[本批验证](S24/artifacts/2026-10-21-toolbar-actions/verification.json)。

此前配对程序为 `2026-10-21-menu-icons`。七组导航、26个功能入口已补齐统一图标；菜单、顶栏与工作台同功能共用资源，保留八枚既有高清快捷图标，新增六枚旧菜单重绘和十四枚功能设计，关于沿用B棱镜图标。长菜单限制在窗口内，展开时缩放仍可查看全部入口。前端与正式/QA构建、浏览器和实际桌面各7组及各24种菜单布局通过。配对程序已备份更新，后端字节、schema23、权限/方法门禁和用户数据保留，安装包未更新。 见[本批验证](S24/artifacts/2026-10-21-menu-icons/verification.json)。

此前配对程序为 `2026-10-20-prism-app-icon`。采用用户选定的Qwen第二版“棱镜分光”，统一Windows程序/默认窗口图标、侧栏、登录/初始化、加载、关于页和浏览器图标。原始10个ICO尺寸帧保持，256px帧前置避免窗口读取16px放大；实际窗口确认使用256×256资源。前端及正式/QA构建、浏览器6组/实际桌面7组及各4种明暗/窗口布局通过。配对程序已备份更新，后端字节、schema23、快捷栏和用户数据保留，安装包未更新。 见[本批验证](S24/artifacts/2026-10-20-prism-app-icon/verification.json)。

此前配对程序为 `2026-10-20-qwen-toolbar-icons`。八枚快捷图标已用本地Qwen Image 2.1参照原图重绘为256×256透明PNG，工具栏仍显示24 CSS像素，改为平滑缩放，深色主题提升方法参数线条亮度；按用户追加要求只显示图标，名称和用途在鼠标悬停时显示。原16×16资源和快捷栏分组、动作、权限保持。前端构建、浏览器和实际打包桌面各9组、各4个明暗/大小窗口布局通过；配对程序已备份更新，后端字节、schema23和用户数据保留，安装包未更新。 见[本批验证](S24/artifacts/2026-10-20-qwen-toolbar-icons/verification.json)。

此前配对程序为 `2026-10-20-legacy-shortcuts`。顶栏新增旧版原图标快捷栏，分为方法操作、参数设置、样品流程三组；新建/打开/另存为接入已有方法界面，样品操作按预录、摄谱、分析排列。中文名称、悬停提示、当前入口高亮、权限及当前方法门禁保留。前端15项、浏览器和实际打包桌面各9组、各4个明暗/大小窗口布局通过；已有分析工作区适配顶栏高度。配对程序已备份更新，后端字节、schema23和用户数据保留，安装包未更新。 见[本批验证](S24/artifacts/2026-10-20-legacy-shortcuts/verification.json)。

2026-10-19 已将可用旧数据接入本机正式用户库：方法20个、样号907项、谱带2548条、旧PDT/DAT矩阵7份；准备3条已完成旧谱分析、1条慢进草稿、标准样三次重复和4份有内容的报告，另有重算、EDT转换及离线摄谱草稿。原有1026条记录保持，数据库完整性及外键检查通过；4份结构异常文件未强制导入，QCT类原件保留。本批仅准备数据；当前程序修复见下。见 [本批验证](S24/artifacts/2026-10-19-legacy-data/verification.json)，操作入口见 [使用说明](../使用与说明/GeoSpectrum_使用说明.md)。

此前配对程序为 `2026-10-19-report-no-unit`。已移除DAT报告的单位填写框与前后端必填限制，打开当前文件后可直接建立报告；未记录的单位保持空值并注明来源，不猜测或修改原数值。已有报告与明确传入的历史单位保持。后端7项、前端15项、浏览器12组和实际QA桌面12组及各2个窗口布局通过；包含新建无单位报告的预览、确认、Excel/PDF真实输出和旧报告回归。配对程序及后端已重建、备份更新，用户库和schema23保留，安装包未更新。见 [本批验证](S24/artifacts/2026-10-19-report-no-unit/verification.json)。

此前样号编辑与满幅表格、方法保存和色散/转角分析链保持，见 [样号编辑验证](S24/artifacts/2026-10-18-sample-edit/verification.json)。

此前方法页将保存草稿/发布合为“保存”，使用“打开方法/另存为”，移除暂停/恢复按钮；失败回滚、历史版本、旧任务绑定、权限和审计保留。其后端339、前端15、浏览器/QA桌面各10组验证结论沿用，见 [方法操作验证](S24/artifacts/2026-10-17-method-save/verification.json)。等高面板、转角两组排列及CCD自动带入均保留。

此前 D05 当前点位拟合、严格误差门禁、自动转角正式样品分析链和20位样号按列排列均已保留。

此前用户与角色流程整理已保留：创建用户在账户列表旁，角色用途与权限摘要两列展示，自定义角色复制模板后按业务组及单项调整；收起和创建失败保留草稿。

此前保守紧凑布局、共用摄谱工作台和打印修复均已保留。保守布局批次巡视27个入口，调整设置、用户创建、方法打印、色散条件及报告来源的短字段排列；其浏览器/实际桌面各54个布局、各6项交互检查通过，长路径、来源列表及结果表保留主宽度。

同一交付保留方法页紧凑分组：基本信息同排，谱板与激发并排，转角独立成行，重复与误差合组；原波段、CCD布局显示和误差折叠均已由最新授权精简覆盖。

- [最新准备页验证与程序哈希](S24/artifacts/2026-10-18-analysis-aligned/verification.json)
- [准备页实际桌面](S24/artifacts/2026-10-18-analysis-aligned/analysis-preparation-single.png)
- [此前样品分析UI与程序哈希](S24/artifacts/2026-10-18-analysis-ui/verification.json)
- [新布局实际桌面](S24/artifacts/2026-10-18-analysis-ui/analysis-1440-1000-light.png)
- [此前样品分析整合验证及程序哈希](S24/artifacts/2026-10-18-analysis-workspace/verification.json)
- [实际桌面布局](S24/artifacts/2026-10-18-analysis-workspace/analysis-1440-1000-light.png)
- [此前摄谱/曲线分离验证及程序哈希](S24/artifacts/2026-10-18-spectroscopy-separate/verification.json)
- [右侧采后重命名实际桌面](S24/artifacts/2026-10-18-spectroscopy-separate/rename-sidebar.png)
- [独立蒸发曲线实际桌面](S24/artifacts/2026-10-18-spectroscopy-separate/evaporation-curves.png)
- [此前摄谱布局验证及配对程序哈希](S24/artifacts/2026-10-18-spectroscopy-layout/verification.json)
- [色散摄谱实际桌面](S24/artifacts/2026-10-18-spectroscopy-layout/dispersion-1440-1000-light.png)
- [样品摄谱实际桌面](S24/artifacts/2026-10-18-spectroscopy-layout/sample-acquisition-1440-1000-light.png)
- [蒸发摄谱实际桌面](S24/artifacts/2026-10-18-spectroscopy-layout/evaporation-acquisition-1440-1000-light.png)
- [此前样号表格验证及配对程序哈希](S24/artifacts/2026-10-18-sample-edit/verification.json)
- [12位表格实际桌面](S24/artifacts/2026-10-18-sample-edit/grid-12-four.png)
- [样号编辑实际桌面](S24/artifacts/2026-10-18-sample-edit/edit-20.png)
- [20位表格实际桌面](S24/artifacts/2026-10-18-sample-edit/grid-20-four.png)
- [此前方法页布局验证](S24/artifacts/2026-10-17-method-layout-rows/verification.json)
- [方法页实际桌面效果](S24/artifacts/2026-10-17-method-layout-rows/methods-1440-light.png)
- [误差控制直接显示](S24/artifacts/2026-10-17-method-layout-rows/quality-1440-light.png)
- [此前D05与合同软件缺口修复操作及范围](S24/artifacts/2026-10-17-legacy-d05-contract/实施清单.md)
- [用户与角色流程验证](S24/artifacts/2026-10-17-users-roles/verification.json)
- [用户与权限页实际桌面截图](S24/artifacts/2026-10-17-users-roles/users-1440-light-default.png)
- [保守紧凑布局验证与前后对照](S24/artifacts/2026-10-16-conservative-density/verification.json)
- [方法页紧凑布局专项验证](S24/artifacts/2026-10-16-method-compact/verification.json)
- [摄谱工作台验证与配对 EXE 哈希](S24/artifacts/2026-10-16-spectroscopy-workbench/verification.json)
- [此前打印修复验证](S24/artifacts/2026-10-16-windows-printing/verification.json)
- [本次验收记录](S24/验收报告.md)
- [此前十四项补齐记录](S24/artifacts/2026-10-16-legacy-fourteen-completion/实施清单.md)
- [当前使用说明](../使用与说明/GeoSpectrum_使用说明.md)

本批未更新安装包，仍为未签名内部测试版。Windows 驱动接通和原生取消不代表实体纸面打印验收。

## 步骤状态

| 步骤 | 当前状态 |
|---|---|
| S00 | passed |
| S01 | deferred_external |
| S02 | passed |
| S03 | passed |
| S04 | passed |
| S05 | passed |
| S06 | passed |
| S07 | passed |
| S08 | passed |
| S09 | passed |
| S10 | passed |
| S11 | passed |
| S12 | passed |
| S13 | passed |
| S14 | deferred_external |
| S15 | deferred_external |
| S16 | passed |
| S17 | passed |
| S18 | passed |
| S19 | passed |
| S20 | passed |
| S21 | deferred_external |
| S22 | passed |
| S23 | passed |
| S24 | passed |

步骤状态沿用已有结论，文档整理不增加用户确认或关闭门禁。

## 未关闭项

- S01、S14、S15、S21的外部项仍需按实际条件完成，尤其是真实转角/汞灯协议与硬件、代码签名、干净Windows安装升级。
- 本批已验证打印专用 Windows 原生保存窗口与取消；实体打印、其他原生保存/剪贴板和正式验收仍需相应证据。
- 旧EXE算法第二判据、物理校准及完整行为等价性按对应要求确认。模拟器与软件测试不替代真实设备证据。

状态值：`not_started`、`in_progress`、`passed`、`failed`、`deferred_external`。任务执行仍遵守 [AGENTS.md](../../AGENTS.md) 与 [PLAN.md](../../PLAN.md)。

---

[文档维护](../参考资料/文档维护.md)
