# 独立离线手册维护

先改 [操作说明](../GeoSpectrum_使用说明.md)。如果菜单或主题编排变化，再同步 `build.mjs` 中的主题和覆盖映射。生成脚本读取 [导航清单](../../../app/manifest.generated.json)，检查所有正式菜单映射和主题间跳转。输出文件为 [GeoSpectrum_使用手册.html](../GeoSpectrum_使用手册.html)。

在项目根目录使用 PowerShell。以下命令将生成和测试依赖装在系统临时目录，浏览器验证需要 Microsoft Edge。

```powershell
$manualDeps = "$env:TEMP\geospectrum-manual-deps"
npm.cmd install --prefix $manualDeps --no-audit --no-fund --ignore-scripts marked@15.0.12 playwright@1.65.1
node 'docs/使用与说明/手册源文件/build.mjs' "$manualDeps\node_modules\marked\lib\marked.esm.js"
node 'docs/使用与说明/手册源文件/verify.mjs' "$manualDeps\node_modules\playwright\index.mjs"
```

验证脚本打开本地 HTML，检查主题导航、正文链接、搜索、打印样式和窄窗。软件内置帮助的单独流程见 [内置帮助维护](../离线帮助维护说明.md)。
