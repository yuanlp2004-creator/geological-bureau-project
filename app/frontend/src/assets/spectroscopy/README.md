# 摄谱工作台完整高清图标

本地 `D:/Flux` ComfyUI / Qwen Image 2.1 INT8 ConvRot 参照旧版原图标完整重绘40枚256×256透明PNG；覆盖主窗口27个、右侧摄谱窗口7个、左侧样品窗口4个图标控件位置，另有记录解锁状态和点位锁定。界面显示20 CSS像素，平滑缩放；原始旧资源只读。

- `crosshair / box-zoom / pan / fit / zoom-x-in / zoom-x-out / zoom-y-in / zoom-y-out`：来自 `Spec Source/Source/Common/DmResource.dfm` 的 `IlGlobal`，索引4、6、5、7、11、12、24、25；作用经 `FmView.dfm/.pas` 交叉核对。
- `lock`：来自 `Spec Source/Res/Images/Lock.bmp`。新版用于观察点位锁定，悬停名称和按下状态明确当前动作；不冒充旧版的谱线锁定。
- `capture / preheat / stop`：来自 `Spec Source/Source/Main/mmAnalyze/FmDockGuideIgnit.dfm` 的 `IlIgnit`，索引0、3、4；保留闪电＋绿色箭头、蓝色B、蓝色停止圆形的识别特征。

本批将40枚分为五张1536×768四列两行参考图，30步、CFG1、Euler/Simple、seed2026102540至2026102544；每枚均重新生成，包括首批12枚。已核对左右/上下箭头、1:1、1:4、10、B及锁定/解锁区别。仅去除与边缘相连的近白底，保留内部白色箭头、加减号、纸张和数字。

三类摄谱工作台恢复左侧当前任务谱带/帧记录、中间谱图及工具、右侧样号与激发控制。共用谱图查看、色散谱线与拟合、样号表和分析控制中的对应操作复用同一高清资源。所有工具保留中文无障碍名称与悬停说明，采集控制保留文字及原权限。

旧版不同文件类型会隐藏/禁用部分动作：图标资源齐全不代表应在采集中执行所有测量、校正或拟合。色散预热不开放正式曲线处理；真实协议缺失不会因更换图标而改变。

提示词、参考图、生成原图、40枚来源清单、功能对应和验收结果见 `docs/acceptance-reports/S24/artifacts/2026-10-25-full-spectroscopy/`。上一批记录仍保留。
