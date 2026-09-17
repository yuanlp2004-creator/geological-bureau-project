import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// 用法：node build.mjs <marked 模块入口路径>。只生成本目录上一级的离线手册。
const root = path.dirname(fileURLToPath(import.meta.url));
const markedModule = process.argv[2];
if (!markedModule) throw new Error('请指定 marked 模块入口路径');
const { marked } = await import(pathToFileURL(path.resolve(markedModule)).href);
const original = fs.readFileSync(path.join(root, '../GeoSpectrum_使用说明.md'), 'utf8');
const manifest = JSON.parse(fs.readFileSync(path.join(root, '../../../app/manifest.generated.json'), 'utf8'));
const sections = original.split('\n');
function take(title) {
  const index = sections.findIndex(line => /^#+ /.test(line) && line.replace(/^#+ /, '').trim() === title);
  if (index < 0) throw new Error(`缺少原说明章节：${title}`);
  const level = sections[index].match(/^#+/)[0].length;
  let end = index + 1;
  while (end < sections.length && !new RegExp(`^#{1,${level}} `).test(sections[end])) end++;
  return sections.slice(index + 1, end).join('\n').trim()
    .replace(/^#### /gm, '## ').replace(/^### /gm, '## ')
    .replace('“重复质控”', '“重复性质控”');
}

const groups = [
  {id:'start', title:'开始使用'},
  {id:'workspace', title:'工作台'},
  {id:'methods', title:'光谱方法'},
  {id:'conditions', title:'分析条件'},
  {id:'analysis', title:'分析测试'},
  {id:'data', title:'数据处理'},
  {id:'tools', title:'工具'},
  {id:'system', title:'系统管理'},
  {id:'help', title:'帮助与故障排查'},
  {id:'reference', title:'文件与术语参考'},
];
const topics = [];
function add(id, group, title, body, options = {}) {
  topics.push({id, group, title, body, ...options});
}

add('welcome','start','手册首页',`
这份手册面向 GeoSpectrum 0.1.0 Windows 桌面版，帮助您从启动软件走到采集、分析、质控和报告输出。

## 从这里开始

- **第一次使用：**先阅读[启动软件](#launch)与[创建管理员和登录](#login)，再按[首次使用路线](#first-run)建立工作环境。
- **已经有方法：**按[日常分析流程](#daily)执行样品采集和结果输出。
- **按菜单查阅：**展开左侧目录，八组业务菜单与当前软件对应。
- **遇到问题：**输入“菜单灰色”“标准曲线”“报告”等关键词搜索，或进入[故障排查](#faq-menu)。

## 如何浏览

左侧目录支持逐级展开、收起，点击主题后在右侧阅读。正文中的蓝色文字可以跳到相关说明。页面底部提供“上一页 / 下一页”，上方提供阅读历史的“后退 / 前进”。

每篇说明尽量按“从哪里进入 → 如何操作 → 完成后检查”的顺序编排。搜索覆盖标题和正文；按 **/** 可将焦点移到搜索框。字号按钮调整阅读大小，“打印本页”可打印或另存为 PDF。

## 适用范围

按 2026-09-05 当前源码、功能清单及同日桌面复验记录编写。当前版本为内部测试版，真实转角与汞灯协议、现场硬件和正式发布验证仍有外部依赖。相关章节会明确说明模拟操作的范围。

本手册是独立的离线 HTML 文件，双击后在浏览器中阅读；不需要登录软件、启动服务或联网。它借鉴旧 DIRECT.CHM 的层级目录与主题跳转形式，内容按当前软件重新组织。
`, {lead:'按任务学习，按菜单查阅。', related:['first-run','daily','navigation','files']});

add('launch','start','启动软件与正常退出',take('一、启动前须知')+'\n\n## 启动步骤\n\n'+take('1. 启动软件')+'\n\n## 正常退出\n\n'+take('14.3 正常退出'), {lead:'只双击主程序，配套后端由软件管理。',related:['login','faq-start','files']});
add('login','start','创建管理员和登录','## 首次创建管理员\n\n'+take('2. 第一次使用时创建管理员')+'\n\n## 使用已有账户\n\n'+take('3. 已经初始化过的电脑')+'\n\n## 登录后检查\n\n确认工作台可以打开，顶部显示当前账户。需要切换账户时，使用顶部“退出登录”按钮；采集运行中应先完成安全停止。', {related:['users','navigation','faq-password']});
add('first-run','start','首次使用路线',`
首次使用可分为四个阶段。下面每一项都可以点击打开详细步骤。

## 1. 建立本机环境

1. [启动软件并登录](#login)。
2. [设置目录、显示和日志](#settings)。
3. [检查本地服务与数据库](#overview)。
4. 有旧数据时，执行[旧方法与配置迁移](#migrate-methods)；没有旧数据可直接新建方法。

## 2. 准备方法与样品

1. 使用[设备实时调试](#devices)检查模拟采集。
2. 需要时建立[色散校准](#dispersion)。
3. [新建方法](#method-create)，设置[方法参数](#conditions)、[分析谱线](#lines)与[标准点名称](#standard-names)。
4. [预览、发布并设为当前](#method-publish)。
5. 建立[样品队列](#queue)，核对重复次数。

## 3. 采集、分析与质控

1. 为标准样和未知样分别[创建采集任务](#capture-create)，并[完成全部采集](#capture-run)。
2. [查看谱图](#spectra)，检查样号、峰位和重复数据。
3. [定量分析与慢进](#analysis)。
4. [重复性质控](#quality) → [标准曲线](#curves) → [合并样品结果](#results)。

## 4. 输出与保留记录

1. [建立、预览并确认报告](#reports)。
2. [选择输出格式并保存](#exports)。
3. [创建在线备份并校验](#backup)。
4. 正常关闭主窗口。

**完成标志：**报告来源可追溯到方法版本、采集数据与曲线快照，输出文件可打开，备份校验通过。单独完成“分析运行”还不等于已经得到可输出的最终报告。
`,{related:['daily','standard-names','faq-report']});
add('daily','start','日常分析流程',take('四、日常分析的最短操作顺序')+'\n\n## 开始前核对\n\n- 当前方法名称与版本正确，方法未暂停。\n- 标准样与未知样的类型、名称和重复次数正确。\n- 本轮使用的数据、曲线和报告来源对应同一套方法口径。\n\n## 流程跳转\n\n[样品队列](#queue) → [创建采集](#capture-create) → [执行采集](#capture-run) → [分析](#analysis) → [质控](#quality) → [曲线](#curves) → [合并结果](#results) → [报告](#reports) → [备份](#backup)。',{related:['first-run','capture-run','reports']});

add('navigation','workspace','认识界面与菜单',`
## 界面分区

- **左侧导航：**工作台、光谱方法、分析条件、分析测试、数据处理、工具、系统管理、帮助。
- **顶部：**当前方法、刷新服务状态、退出登录及账户入口。
- **中央工作区：**所选功能的列表、参数、曲线或结果。
- **运行消息：**记录操作结果、告警与错误，排查问题时优先保留原始提示。

## 使用层级菜单

将鼠标移到左侧分组可展开右侧子菜单；点击分组可固定展开。选择子项进入对应页面或内部视图，按 Esc 或点击外部区域收起。长菜单可滚动，键盘方向键可辅助切换焦点。

## 为什么入口不同

**入口不显示：**当前账户没有所需权限。**入口显示但不可用：**通常尚未选择当前方法、方法已暂停，或页面内还缺少必要输入。先查看禁用原因，不要反复点击。

“方法参数”“分析谱线”等入口会打开当前方法的对应视图；“方法库与当前方法”用于先选择、新建或切换方法。后处理和报告页允许先进入，再在页面内选取来源记录。
`,{entry:'左侧导航与顶部工具栏',related:['faq-menu','method-publish','users']});
add('overview','workspace','工作台概览',take('第 1 步：检查工作台和本地服务')+`

## 当前版本的显示提示

工作台“服务通道”中的“事件流：待连接”和“桌面壳：构建中”仍有固定文本显示问题，不能仅凭这两项判断桌面程序未启动或采集失败。请结合本地服务“已连接”、REST API 在线状态、[关于与诊断](#about)以及实际任务消息判断。

## 完成后检查

本地服务已连接、当前方法符合本次任务，近期消息没有未处理错误。服务离线时先按[服务连接排查](#faq-service)处理。
`,{entry:'工作台 → 工作台概览',related:['messages','about','faq-service']});
add('messages','workspace','阅读与保存运行消息',`
## 查看消息

在工作台查看运行消息；在采集、校准和分析任务中同时检查本任务的消息或轨迹。区分普通信息、警告和错误，记录发生时间、任务编号、错误码及原始错误说明。

## 保存证据

需要导出运行消息时使用界面提供的导出入口，在桌面“另存为”对话框中选择位置。保存后核对实际文件名；取消对话框不会产生文件。

## 出错后怎么做

先确认任务是否已安全停止，再根据提示修正输入、恢复任务或重新建立任务。不要只截取“失败”二字，也不要反复提交同一个无效输入。报告问题时可使用[故障信息清单](#faq-evidence)。
`,{entry:'工作台 → 工作台概览；各任务的运行消息区域',related:['capture-run','faq-evidence','exports']});

add('method-create','methods','新建与复制方法',take('6.1 新建方法')+`

## 复制已有方法

在方法列表中选择参考方法，点击“复制”，输入新名称并确认。复制后先检查新方法的参数、谱线和标准点，再保存与发布。不要仅改名称就假定它适合另一类样品。

## 下一步

依次完成[方法参数](#conditions)、[分析谱线](#lines)、[预览与发布](#method-publish)。新建草稿不会自动成为当前运行方法。
`,{entry:'光谱方法 → 方法库与当前方法',related:['conditions','lines','method-publish']});
add('method-publish','methods','发布、切换与暂停方法',take('6.4 预览、发布并设为当前方法')+`

## 暂停、恢复与删除

选择方法后，通过“暂停方法”或“恢复方法”图标改变启用状态。暂停当前方法后，依赖它的入口会变为不可用。软删除会要求确认，历史版本仍保留以支持已有数据追溯。

## 容易混淆的状态

- **列表选中：**正在查看或编辑这条方法。
- **保存草稿：**保存编辑内容，不等于发布。
- **发布版本：**产生不可变版本。
- **设为当前：**指定后续相关操作使用的运行方法。

顶部当前方法与列表选中项不一定相同，采集前务必核对。
`,{entry:'光谱方法 → 方法库与当前方法',related:['method-create','preview','faq-menu']});
add('print-settings','methods','页面与打印机设置',`
## 操作步骤

1. 进入方法打印设置，选择要输出的方法。
2. 核对打印机、纸张、方向、边距和版式。
3. 保存相关设置，然后打开[参数预览与打印](#preview)。
4. 查看页数、中文、单位、表格边界和分页，再执行打印或 PDF 输出。

## 检查要点

页面参数与目标打印机纸张应一致。文件输出与实体打印是不同操作：生成 PDF 成功，不代表打印机已经出纸。需要实体打印时选择可用的 Windows 打印机，并检查打印队列。
`,{entry:'光谱方法 → 页面与打印机设置',related:['preview','exports']});
add('conditions','conditions','设置方法参数',take('6.2 配置方法条件')+`

## 数值输入与保存

输入框可以暂时清空以便重新填写；提交时仍需满足有效范围。出现字段错误时按提示修正，不能把空值当作零值或已保存。采样周期、帧数、重复次数和保存区间会影响采集内容，应在发布前统一核对。

入口显示“方法参数”，页面内部对应“方法条件”编辑区域。只改草稿不改变已发布版本。
`,{entry:'分析条件 → 方法参数',related:['lines','method-publish','interval']});
add('lines','conditions','配置分析谱线',take('6.3 配置分析谱线和标准点')+`

## 谱线类型

- **分析线：**参与待测元素定量。
- **内标线：**用于已配置的内标关系。
- **定位线：**辅助谱线定位。
- **基线：**用于方法中的背景/基线相关处理。

波长必须是有效数值且满足检测范围。保存失败时查看字段提示；不要在非法输入后继续发布方法。内标引用、CCD 与校准范围应一致。
`,{entry:'分析条件 → 分析谱线',related:['standard-names','conditions','profiles']});
add('standard-names','conditions','标准点与标准样名称对应',`
## 核心规则

方法分析线里的标准点名称，要与采集得到的**标准样品名称完全对应**。例如标准点使用 S1、S2、S3、S4，采集时也使用这些名称，并将样品类型设为“标准样”。

未知样品使用独立名称，例如 QA-1。不要把未知样品命名为某个标准点，也不要仅靠队列顺序代替名称匹配。

## 操作检查

1. 在分析谱线中保存标准点名称和已知标准值。
2. 建立队列或采集任务时核对样名、类型和重复次数。
3. 完成采集、分析及重复性质控。
4. 打开标准点视图，确认每个启用点都能获得有效强度。
5. 再拟合并发布标准曲线。

示例名称只用于说明对应规则，不提供通用标准浓度。实际标准值应来自您采用的标准样资料。
`,{entry:'分析条件 → 分析谱线；分析测试 → 标准曲线与样品结果',related:['queue','capture-create','curves','faq-curves']});
add('preview','conditions','参数预览与打印',`
## 操作步骤

1. 确认当前方法和要查看的版本。
2. 进入“参数预览与打印”，检查方法条件、谱线、内标关系与标准点。
3. 如需调整版式，进入[页面与打印机设置](#print-settings)。
4. 生成预览，检查页数、边距、表格与中文显示。
5. 使用方法 PDF 输出或打印入口，并核对保存位置或打印结果。

## 发布前检查

预览用于复核，不会替代保存草稿和发布。待修正项为 0 后，仍需在方法操作栏执行“发布”和“设为当前”。
`,{entry:'分析条件 → 参数预览与打印',related:['method-publish','print-settings','exports']});

add('queue','analysis','样号与样品队列',take('第 7 步：建立样品队列'),{section:'准备与采集',entry:'分析测试 → 样号与样品队列',related:['standard-names','capture-create','formats']});
add('dispersion','analysis','色散摄谱与校准',take('第 5 步：需要时建立色散校准'),{section:'准备与采集',entry:'分析测试 → 色散摄谱与校准',related:['devices','conditions','mercury']});
add('capture-create','analysis','创建蒸发或样品采集任务',take('8.1 建立任务')+'\n\n## 创建后检查\n\n任务列表出现新任务，方法版本、样品类型、保存模式与重复次数正确。创建任务不等于已经采集，下一步选中任务并启动。',{section:'准备与采集',entry:'分析测试 → 蒸发与样品摄谱',related:['capture-run','queue','standard-names']});
add('capture-run','analysis','执行、暂停与停止采集',take('8.2 执行任务'),{section:'准备与采集',entry:'分析测试 → 蒸发与样品摄谱',related:['spectra','analysis','messages']});
add('hardware','analysis','自动转角采集与异常处置',`
## 当前可用范围

该页面提供转角计划和异常处置的软件流程。真实转角协议与现场证据尚缺，真实串口档案启动会记录延后状态，不发送猜测命令。以下用于模拟检查，不作为真实设备操作规程。

## 模拟操作步骤

1. 选择已发布当前方法，进入“自动转角采集”。
2. 填写任务名称，选择模拟设备档案和 CCD 布局。
3. 按本次模拟方案选择“短波 → 长波”或“关键波段优先”，设置异常策略及有限重试上限。
4. 核对页面中的转角计划与波段内容，点击“创建任务”。计划输入需要符合界面和方法约束；不要把测试脚本当作真实串口命令。
5. 选中任务，点击“启动”，通过“单步”检查进度、当前计划步、原始帧和轨迹。
6. 发生人工接管时，先检查当前帧和失败原因，再选择接受、重试、恢复或停止；损坏帧不能被接受。
7. 结束后检查处置决定、结果和安全收尾记录。

## 真实设备前置条件

必须先取得已确认的现场协议和硬件验收条件，再安排真实采集；不能通过修改异常策略绕过缺失条件。
`,{section:'准备与采集',entry:'分析测试 → 自动转角采集',related:['devices','capture-run','hardware-limit']});
add('spectra','analysis','谱图查看、叠加与定位',take('第 9 步：查看采集谱图'),{section:'查看与分析',entry:'分析测试 → 谱图查看',related:['capture-run','analysis','exports','interval']});
add('analysis','analysis','定量分析与逐谱线慢进',take('第 10 步：执行定量分析和慢进复核'),{section:'查看与分析',entry:'分析测试 → 定量分析与慢进',related:['profiles','quality','faq-analysis']});
add('quality','analysis','重复性质控',take('11.1 重复质控')+'\n\n## 完成后检查\n\n确认有效重复次数、提示接受与剔除决定正确，再重新统计形成可用快照。不要为了让曲线可发布而无依据地剔除数据。',{section:'质控、曲线与结果',entry:'分析测试 → 重复性质控',related:['analysis','curves','results']});
add('curves','analysis','拟合并发布标准曲线',take('11.2 标准点和曲线'),{section:'质控、曲线与结果',entry:'分析测试 → 标准曲线与样品结果',related:['standard-names','quality','results','faq-curves']});
add('results','analysis','合并并保存样品结果',take('11.3 合并样品结果')+'\n\n## 为什么还要合并\n\n分析运行中的原始结果、曲线拟合结果和最终报告来源是不同阶段。只有完成相应质控与曲线发布，再“合并并保存”，报告才有可追溯的最终结果可用。',{section:'质控、曲线与结果',entry:'分析测试 → 标准曲线与样品结果 → 样品结果',related:['curves','reports','faq-report']});

add('interval','data','全时区间处理',`
## 开始前

选择确实保存了全时帧的记录。只有平均谱的记录不能凭空恢复每一帧。采集时是否保存全时数据，参见[方法参数](#conditions)和[采集任务](#capture-create)。

## 操作步骤

1. 进入“全时区间处理”，选择 EDT/CMT 或支持的全时采集记录。
2. 核对 CCD，设置起始帧和结束帧后读取区间。
3. 检查所选区间的曲线、来源与范围。
4. 需要进行 EDT 转换时，明确选择记录、目标 CCD 布局和方法版本，再执行转换。
5. 核对处理记录和结果信息；原件保持只读。

## 常见限制

缺少原始帧、区间越界或布局不匹配时应修正选择，不要通过改文件扩展名绕过校验。
`,{entry:'数据处理 → 全时区间处理',related:['spectra','recalculate','formats']});
add('recalculate','data','结果重算与矩阵导出',`
## 明确输入

精确重算需要源记录、确切方法版本、计算档案和已发布曲线快照。先确定这些绑定，再执行；同名方法不能代替版本一致性。

## 操作步骤

1. 进入“结果重算与矩阵导出”，选择来源记录。
2. 选择目标方法版本、计算档案和适用的已发布曲线快照。
3. 执行重算，检查处理状态和结果；任一来源失败时，先修正阻断原因再重试整批。
4. 选择要输出的原始强度、处理强度或结果矩阵。
5. 选择 TXT、CSV 或 Excel 格式，填写已存在且可写的输出目录与文件名。
6. 导出后按界面返回的最终路径检查文件。

旧结果只读迁移与精确重算是两个步骤。导入成功不代表已经具备所有重算条件。
`,{entry:'数据处理 → 结果重算与矩阵导出',related:['profiles','curves','migrate-results','exports']});
add('reports','data','建立、确认与输出分析报告',take('第 13 步：建立、预览、确认和导出报告'),{entry:'数据处理 → 分析报告',related:['results','exports','faq-report']});
add('exports','data','文件保存、导出与打印',`
## 两种保存方式

**弹出“另存为”对话框：**常见于运行消息、方法 PDF、谱图 CSV/PDF、SAM 队列等前端生成的文件。选择位置并确认保存；取消不会产生文件。浏览器开发模式使用浏览器下载行为。

**页面内填写输出目录：**报告和后处理矩阵使用对应页面的目录与文件名设置。先确认目录已存在、可写，再导出，以成功提示中的实际路径为准。

## 选择格式

| 需要做什么 | 常用格式与入口 |
|---|---|
| 查看和提交排版结果 | 报告 PDF、方法 PDF、谱图 PDF |
| 继续整理表格数据 | 报告或矩阵 CSV / Excel |
| 简单文本交换 | 报告或矩阵 TXT |
| 交换样品队列 | 样品队列 SAM |
| 保存故障上下文 | 运行消息 LOG |

## 输出前后检查

1. 确认方法版本、样品、元素、CCD 和所选范围。
2. 报告先预览并确认；方法和谱图按当前预览或可见范围输出。
3. 执行保存，等待明确的成功提示。
4. 打开最终文件检查内容和文件名。同名文件可能增加后缀，应记录实际路径。

实体打印还需选择可用 Windows 打印机并检查打印队列。不要把生成 PDF 与纸张已打印混为一谈。
`,{entry:'各页面的保存、导出或打印入口',related:['reports','print-settings','spectra','queue']});

add('devices','tools','设备参数与实时调试',take('第 4 步：连接模拟设备并做实时诊断'),{entry:'工具 → 设备参数与实时调试',related:['dispersion','capture-create','hardware-limit']});
add('mercury','tools','汞灯与光学校准',`
## 与色散校准的区别

汞灯页面比较汞线的期望位置与实测峰位，生成光学偏移建议及版本记录；结果独立于色散方法版本。不要把“应用建议”当作重新发布色散曲线。

## 模拟检查步骤

1. 进入“汞灯与光学校准”，输入会话名称。
2. 选择模拟设备档案、CCD 布局及汞线，核对稳定帧数与模拟峰偏移；正常流程的故障脚本选“无”。
3. 点击“建立校准会话”，选中会话后“启动”，通过“单步”推进到稳定采集阶段。
4. 查看实时汞谱、期望位置、实测位置、校正前后偏移和残差 RMS。
5. 仅在状态允许且结果经复核后使用“应用建议”；需要撤销时按页面提供的“回滚”恢复版本。
6. 结束后确认安全态及调试轨迹；异常安全关闭的会话不应作为已应用校准。

## 当前限制

真实汞灯协议、抓包与现场硬件仍缺失。选择真实档案可能进入延后状态，不会发送猜测的控制字节。本节是软件模拟流程，真实汞灯的开关、预热和保护时间必须以设备确认资料为依据。
`,{entry:'工具 → 汞灯与光学校准',related:['dispersion','devices','hardware-limit']});
add('migrate-methods','tools','旧方法与配置迁移',take('3.1 迁移旧方法和配置')+'\n\n## 数据保护\n\n原始 MTD、CFG、OPT 保持只读。先检查暂存报告再提交，读取器失败时保存诊断，不通过修改历史原件解决。迁移后检查方法草稿与已发布状态，再选择适合的当前方法。',{section:'旧版数据迁移',entry:'工具 → 旧方法与配置迁移',related:['method-publish','formats','migrate-spectra']});
add('migrate-spectra','tools','旧谱数据迁移',`
## 支持的文件

本入口处理 CDT、CMT、EDT、WDT 旧谱数据。DAT/PDT 结果文件使用[旧结果迁移](#migrate-results)，SAM 使用[样品队列](#queue)导入。

## 操作步骤

1. 选择旧谱文件，执行暂存与校验。
2. 检查格式、CCD 布局、记录数、数据块、坏帧和源文件指纹。
3. 报告无阻断问题后原子提交。
4. 到[谱图查看](#spectra)核对样品和曲线；全时数据需要时进入[全时区间处理](#interval)。

解析在临时副本中进行，原件不回写。遇到未知格式、截断或损坏数据，应保留原件和报告，不更改扩展名来尝试导入。
`,{section:'旧版数据迁移',entry:'工具 → 旧谱数据迁移',related:['formats','spectra','interval']});
add('migrate-results','tools','旧结果迁移',`
## 操作步骤

1. 在旧结果迁移页选择 DAT 或 PDT 文件。
2. 执行只读暂存和校验。
3. 检查样品、谱线、矩阵维度、方法匹配状态和源文件指纹。
4. 无阻断问题后原子提交，核对迁移后的记录。

## 方法匹配与后续使用

无法匹配方法的结果应保留其来源和诊断，不要随意套用同名方法。精确重算还需指定确切方法版本、计算档案和已发布曲线快照，详见[重算与矩阵导出](#recalculate)。

只读迁移不会覆盖旧 DAT/PDT，也不会把重新计算的结果写回旧格式。
`,{section:'旧版数据迁移',entry:'工具 → 旧结果迁移',related:['formats','recalculate','migrate-methods']});

add('settings','system','软件设置',take('第 2 步：设置目录、显示、日志和打印默认值')+'\n\n## 目录含义\n\n默认业务目录和导出目录不等于 SQLite 数据库位置。修改默认目录不会搬迁数据库；实际数据库路径以“关于与诊断”为准。保存后重新检查设置值，错误提示未消失前不要认为已经生效。',{entry:'系统管理 → 软件设置',related:['files','backup','exports']});
add('users','system','用户与权限',`
## 账户和角色

系统内置系统管理员、方法管理员、分析员、只读审计员等角色。管理员主要负责本机设置与身份管理，方法管理员负责方法配置，分析员执行分析流程，只读审计员查阅已授权记录。角色名称不等于拥有全部业务操作权限，以页面实际列出的权限为准。

## 新建账户

1. 使用具备用户管理权限的账户进入本页。
2. 在创建用户区域填写用户名、至少 8 位的初始密码及角色。
3. 点击创建按钮，刷新后核对账户列表、角色和启用状态。
4. 新账户登录后检查所需入口是否可见。

## 启用与停用

在账户列表中对其他账户使用启用/停用按钮。当前界面不提供停用自身账户的操作。停用影响后续访问，不删除其历史操作记录。

## 角色维护的边界

本页可以查看角色权限，具备权限时可创建自定义角色。当前界面没有完整的既有用户角色改配或密码重置表单；不要按旧软件菜单寻找不存在的“重置密码”按钮。需要这些操作时联系维护人员，先保护现有数据。
`,{entry:'系统管理 → 用户与权限',related:['login','faq-menu','faq-password','audit']});
add('audit','system','审计记录',`
## 查阅步骤

1. 进入“审计记录”，点击“刷新”。
2. 按时间倒序查看记录，核对操作者、动作、目标和详情。
3. 对需要进一步解释的详情使用展开控件，记录对应时间及对象编号。

## 与运行消息的区别

运行消息主要帮助理解当前运行情况；审计用于追溯身份、方法、采集、分析、输出和维护等变更。审计记录不可在本页任意编辑或删除。

当前桌面审计页以刷新和倒序列表为主，没有独立的日期/动作筛选表单。查找大量记录时不要把其他页面的搜索功能当作本页筛选能力。
`,{entry:'系统管理 → 审计记录',related:['users','messages','faq-evidence']});
add('backup','system','在线备份与恢复演练',take('14.1 创建并校验备份')+`

## 恢复演练的含义

“恢复演练”在隔离副本中验证备份，不会直接把当前业务库切换为旧备份。演练成功后，当前库仍是原来的库。需要正式恢复时，先与维护人员确认恢复范围及切换步骤。

备份应放在合适的独立目录，并定期确认文件可读取、校验通过。不要为了重置账户而删除业务数据库。
`,{entry:'系统管理 → 备份与维护',related:['maintenance','files','faq-password']});
add('maintenance','system','数据库、日志与临时文件维护',`
## 执行前检查

确认有维护权限，近期在线备份已校验，当前没有需要继续运行的采集任务。查看数据库状态和外键检查结果，先处理异常再安排维护。

## 可用操作

- **WAL checkpoint：**处理数据库事务日志的检查点。
- **优化：**执行数据库维护优化。
- **受控回收：**按程序约束回收数据库空间，不代表删除业务结果。
- **日志与临时文件清理：**按保留策略清理程序管理的相应文件。

每次执行后检查页面结果和操作记录。维护失败时保留错误信息，不直接在资源管理器中删除正在使用的数据库、WAL 或备份。
`,{entry:'系统管理 → 备份与维护',related:['backup','audit','files']});

add('builtin-help','help','软件内的离线帮助',`
## 使用方式

登录后进入“帮助 → 离线帮助”，在搜索框输入主题、关键词或错误码，选择左侧匹配主题阅读简要说明。清空搜索可恢复主题列表。

## 与本手册的关系

软件内帮助是当前内置的简要主题页；本文件提供更细的操作步骤、树形目录及正文跳转。软件内“关联模块”当前显示模块路径文本，并非本手册的可点击导航。

查找具体操作时可在本手册搜索框中输入“样品队列”“合并”“报告”等词。
`,{entry:'帮助 → 离线帮助',related:['faq-evidence','navigation','about']});
add('about','help','关于与诊断',`
## 查看内容

进入本页并刷新，核对产品名称、版本、构建信息、API 信息、数据库路径、SQLite 诊断及能力清单。实际路径以本机显示为准。

## 出现问题时记录

保留版本、构建标识、发生时间和相关诊断结果，结合[运行消息](#messages)说明具体操作。不要向无关人员发送密码、会话信息或完整业务数据库。

如果账户看不到此入口，先确认权限；不要将页面不可见等同于服务离线。
`,{entry:'帮助 → 关于与诊断',related:['overview','files','faq-evidence']});
for (const [id,title,source,related] of [
  ['faq-start','双击后没有窗口','1. 双击后没有窗口',['launch','faq-service']],
  ['faq-service','本地服务离线','2. 显示本地服务离线',['overview','about']],
  ['faq-menu','菜单灰色或找不到入口','3. 菜单灰色或不能进入',['method-publish','users']],
  ['faq-curves','标准曲线无法拟合或发布','4. 标准曲线无法拟合或发布',['standard-names','quality','curves']],
  ['faq-report','报告为空或不能输出','5. 报告列表为空或不能输出',['results','reports','exports']],
  ['faq-password','忘记密码怎么办','6. 忘记管理员密码',['users','backup']],
]) add(id,'help',title,take(source),{section:'常见问题',related});
topics.find(t=>t.id==='faq-service').body += '\n\n## 重新启动后检查\n\n等待本地服务显示“已连接”，再进入关于与诊断刷新。工作台的事件流和桌面壳固定状态文字不作为故障判断依据。若仍无法连接，保留版本、时间和错误提示后联系维护人员，不通过删除数据库重试。';
// 现有桌面没有既有用户角色编辑与密码重置表单，避免旧说明让读者寻找不存在的入口。
topics.find(t=>t.id==='faq-menu').body = topics.find(t=>t.id==='faq-menu').body.replace('请让管理员在“用户与权限”中授予所需最小角色或权限。','请让管理员核对账户与角色权限；当前界面的角色修改能力有限，必要时联系维护人员处理。');
topics.find(t=>t.id==='faq-password').body = '软件没有通用默认密码。当前桌面没有可直接操作的密码重置表单，请联系维护人员制定恢复方案。不要删除 `%LOCALAPPDATA%\\cn.geospectrum.desktop` 来重新初始化，这会使本机业务数据丢失。先保留现有数据与已验证备份。';
add('faq-analysis','help','分析没有完成或表单报错',`
1. 确认至少选择一个已完成采集的样品，输入属于同一个方法版本。
2. 核对慢进超时等数值，修正表单中的持久错误提示；提交失败后不会自动产生有效运行。
3. 建立并锁定输入后，选中运行再点击“开始”。
4. 慢进状态需要处理检查点并推进，不是等待一段时间就一定会自动完成。
5. 失败时保留错误说明和运行编号，再决定修正输入、重新采集或建立新运行。

不要将旧包的现象直接当作当前包的结论。报告问题时附上“关于与诊断”的版本与构建信息。
`,{section:'常见问题',related:['analysis','quality','faq-evidence']});
add('hardware-limit','help','真实设备与模拟器的区别',take('7. 真实转角或汞灯功能')+'\n\n## 模拟器可以验证什么\n\n可用于熟悉界面、验证状态推进、样品数据处理和错误反馈。模拟帧与随机种子可支持重复验证，但不会证明真实串口连接、光学条件、仪器保护或测量性能已通过现场验收。',{section:'常见问题',related:['devices','hardware','mercury']});
add('faq-evidence','help','如何记录和反馈故障',`
## 建议保留的信息

1. 软件版本、构建标识和发生时间。
2. 从哪个菜单进入、点击了什么、期望结果与实际结果。
3. 方法及版本、任务或报告编号；必要时记下样品与 CCD。
4. 完整错误码、原始错误内容及相关运行消息。
5. 是否使用模拟器，是否只在某个输入或某个账户下发生。

## 先做的检查

确认任务已安全停止；保存消息和必要截图；检查输入及目录权限。不要先删除数据库、修改历史原件或反复覆盖输出文件。

对外提供资料前去除密码和无关业务数据；优先提供最小可复现步骤与诊断信息。
`,{section:'常见问题',related:['messages','about','backup']});

add('files','reference','程序、数据库与备份在哪里',`
| 内容 | 默认位置或说明 |
|---|---|
| 直接启动的主程序 | 项目主文件夹中的 GeoSpectrum.exe |
| 配套后端 | 与主程序同目录的 geospectrum-backend.exe，由主程序启动 |
| 本机构建安装包 | app/.local/releases/0.1.0/ |
| 正常运行数据库及相关数据 | %LOCALAPPDATA%\\cn.geospectrum.desktop；以关于与诊断显示为准 |
| 报告与矩阵导出 | 对应页面指定的输出目录 |
| 在线备份 | 备份与维护页面实际使用的目录 |
| 本手册 | docs/使用与说明/GeoSpectrum_使用手册.html |

## 打开用户数据目录

在资源管理器地址栏输入 \`%LOCALAPPDATA%\\cn.geospectrum.desktop\` 并回车。只查看和定位即可，不要在程序运行时移动数据库及其日志文件。

## 升级或复制程序

主程序和后端必须来自同一次构建，并成对放置。移动程序不会自动搬迁用户数据库。便携演示版通过自己的启动脚本使用 demo-data，不能把演示数据库误认为正常账户的业务库。
`,{related:['launch','backup','settings']});
add('formats','reference','旧文件与输出格式速查',`
| 文件类型 | 当前入口 | 处理方式 |
|---|---|---|
| DIRECT.MTD / DIRECT.CFG / DIRECT.OPT | 旧方法与配置迁移 | 只读暂存、校验、提交 |
| CDT / CMT / EDT / WDT | 旧谱数据迁移 | 保留原件和来源指纹 |
| DAT / PDT | 旧结果迁移 | 保留结果与方法匹配诊断 |
| SAM | 样号与样品队列 | 导入或导出样品队列 |
| CSV / TXT / Excel | 报告或矩阵输出 | 按所选结果和范围导出 |
| PDF | 方法、谱图、曲线或报告 | 按对应预览/页面设置生成 |
| LOG | 运行消息 | 保存操作与排错信息 |

迁移旧 Access 类格式不会回写原件，也不生成可供旧版回读的 Access 文件。不要根据相似扩展名推断支持范围。
`,{related:['migrate-methods','migrate-spectra','migrate-results','exports']});
add('profiles','reference','计算档案与常用术语',`
## 计算档案

- **modern_v1：**现代计算口径；高斯模式保存峰高、中心、Sigma 和面积，并以面积参与定量。
- **legacy_2_0_2：**旧版兼容口径，用于复现旧版相关计算行为。

它们不是可以随意互换的显示选项。重算时明确选择，报告应保留所用档案，比较结果时同时核对档案和方法版本。

## 常用术语

| 术语 | 使用时的含义 |
|---|---|
| 草稿 / 发布版本 | 可编辑准备状态 / 后续数据引用的不可变版本 |
| 当前方法 | 当前运行选用的方法；不一定等于正在浏览的列表项 |
| CCD / 点位 / 波长 | 检测阵列、采样位置与经校准对应的波长坐标 |
| 燃烧帧 / 暗帧 | 采集阶段的原始帧类型，查看与处理时需区分 |
| 平均谱 / 全时区间 | 平均结果 / 保留逐帧过程的数据 |
| 标准点 / 标准样 | 方法中已知数值点 / 与之名称对应的实际采集样品 |
| RSD | 相对标准偏差，结合方法阈值和有效重复次数检查 |
| 快照 | 某次质控、曲线、合并或报告结果的固定记录 |
| SHA-256 | 文件或数据内容指纹，用于核对来源与完整性 |
| 恢复演练 | 在隔离副本中验证备份，不等于切换当前数据库 |
`,{related:['analysis','standard-names','backup','method-publish']});
add('protection','reference','数据保护与使用边界',take('六、文件和数据保护原则')+'\n\n## 本手册的使用边界\n\n手册中的模拟操作不代替真实设备说明、现场安全操作规程或正式发布验收。遇到界面与文档不同，先核对版本并保留提示；不要为了照着文档执行而绕过产品校验。',{related:['hardware-limit','backup','faq-evidence']});

const ids = new Set(topics.map(t => t.id));
if (ids.size !== topics.length) throw new Error('主题 ID 重复');
for (const topic of topics) {
  for (const id of topic.related || []) if (!ids.has(id)) throw new Error(`无效关联 ${id}`);
  for (const match of topic.body.matchAll(/\]\(#([^)]+)\)/g)) if (!ids.has(match[1])) throw new Error(`无效跳转 ${match[1]}`);
  // 中文标点紧接文字时，显式处理加粗，避免 Markdown 分隔符直接显示在正文中。
  topic.html = marked.parse(topic.body.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>'));
  delete topic.body;
}
const entryToTopic = {
  '工作台概览':'overview','软件设置':'settings','关于与诊断':'about','用户与权限':'users','审计记录':'audit',
  '方法库与当前方法':'method-create','页面与打印机设置':'print-settings','方法参数':'conditions','分析谱线':'lines','参数预览与打印':'preview',
  '旧方法与配置迁移':'migrate-methods','样号与样品队列':'queue','旧谱数据迁移':'migrate-spectra','旧结果迁移':'migrate-results','谱图查看':'spectra',
  '设备参数与实时调试':'devices','色散摄谱与校准':'dispersion','蒸发与样品摄谱':'capture-create','自动转角采集':'hardware',
  '汞灯与光学校准':'mercury','定量分析与慢进':'analysis','重复性质控':'quality','标准曲线与样品结果':'curves',
  '全时区间处理':'interval','结果重算与矩阵导出':'recalculate','分析报告':'reports','备份与维护':'backup','离线帮助':'builtin-help',
};
const entries=manifest.modules.flatMap(m=>m.navigation_entries||[]);
for(const entry of entries) if(!ids.has(entryToTopic[entry.label])) throw new Error(`未覆盖菜单：${entry.label}`);
const data = JSON.stringify({groups,topics,version:'0.1.0',date:'2026-09-05'}).replace(/</g,'\\u003c');
const template = fs.readFileSync(path.join(root,'template.html'),'utf8');
const destination = path.join(root,'../GeoSpectrum_使用手册.html');
fs.writeFileSync(destination,template.replace('/*__MANUAL_DATA__*/',data),'utf8');
console.log(JSON.stringify({file:destination,groups:groups.length,topics:topics.length,menuEntries:entries.length,bytes:fs.statSync(destination).size}));
