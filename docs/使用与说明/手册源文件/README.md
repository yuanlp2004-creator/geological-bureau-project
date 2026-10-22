# 离线手册的维护与验证

输出文件为上一级 `GeoSpectrum_使用手册.html`。独立 HTML 仅借鉴 `Spec Source/Bin/DIRECT.CHM` 的树形目录、主题页和交叉跳转形式，未复制旧程序帮助脚本或插图。

## 内容依据

- `../GeoSpectrum_使用说明.md`：已存在的操作步骤。
- `../../../app/manifest.generated.json` 和 `../../../app/frontend/src/navigation.ts`：七组菜单、27 个正式入口及页面上下文。
- `../../../app/frontend/src/` 中各页面、`../../../app/backend/` 中相应实现：按钮、操作能力、数据目录和帮助/维护边界。
- [最新实施清单](../../acceptance-reports/S24/artifacts/2026-10-16-legacy-ten-completion/实施清单.md) 与 [参数复查实施结果](../../acceptance-reports/S24/artifacts/2026-10-16-parameter-followup/实施清单.md)：当前功能入口和验证边界。

`build.mjs` 重新组织主题并补充说明；对已有文案中的角色改配、密码重置、审计筛选、内置帮助关联路径及恢复演练作出范围澄清。构建会校验主题唯一性、相关链接、正文跳转与菜单覆盖；没有修改产品代码和原始说明 PDF。

## 文件职责

- `build.mjs`：提取原文字说明，编排 9 章、55 个主题，校验菜单覆盖并生成独立手册。
- `template.html`：页面、分层目录、搜索、历史、页内跳转、打印及响应式样式。
- `verify.mjs`：使用 Edge 无头浏览器验证本地 `file://` 手册，不连接产品后端。

## 生成与验证

使用已安装的 Node.js，并将现有 `marked` 与 `playwright` 模块入口作为参数传入，无须在此目录安装重复依赖：

```powershell
node build.mjs <marked模块入口的绝对路径>
node verify.mjs <playwright模块入口的绝对路径>
```

本次使用工作区运行时中的 `marked/lib/marked.esm.js` 与 `playwright/index.mjs`。源码依赖路径按本 README 所在目录计算，执行时不依赖当前工作目录。

## 当前手册验证

当前输出为9章、55个主题，覆盖27个正式菜单入口；主题及正文链接、搜索、导航、打印样式和小屏检查通过。浏览器没有页面脚本错误或外部HTTP请求。验证截图留在系统临时目录。

本手册是外部离线文档，不替换软件内置帮助，不重建EXE、CHM或安装包。

---

[文档维护](../../参考资料/文档维护.md)
