# 功能菜单图标

- [图标对应表](图标对应表.md)、[28枚功能图标总览](icon-catalogue.png)、[实际桌面菜单](menu-preview.png)、[验证](verification.json)。
- 八枚顶栏资源保持；六枚旧菜单图标参照FmMain.dfm重绘，十四枚缺少旧图标的功能补绘；关于沿用已选B棱镜方案。
- Qwen生成文件：legacy为六枚旧菜单，system为八枚工作台/系统/迁移/设备，tools为六枚转角/汞灯/重算/维护/帮助/工具。每组保存reference、sheet、prompt、workflow与真实任务回执。
- 正式资源位于`app/frontend/src/assets/menu/`，唯一映射与组件为`app/frontend/src/components/FunctionIcon.tsx`。菜单中文名称及顶栏悬停提示保持。
- 主目录配对程序已更新；关闭旧窗口后重开GeoSpectrum.exe载入。
