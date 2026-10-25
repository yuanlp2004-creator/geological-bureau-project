# 摄谱工作台高清图标

本地 `D:/Flux` ComfyUI / Qwen Image 2.1 INT8 ConvRot 参照旧版原图标重绘；最终12枚256×256透明PNG，界面显示20 CSS像素，采用平滑缩放。

- `crosshair / box-zoom / pan / fit / zoom-x-in / zoom-x-out / zoom-y-in / zoom-y-out`：来自 `Spec Source/Source/Common/DmResource.dfm` 的 `IlGlobal`，索引4、6、5、7、11、12、24、25；作用经 `FmView.dfm/.pas` 交叉核对。
- `lock`：来自 `Spec Source/Res/Images/Lock.bmp`。新版用于观察点位锁定，悬停名称和按下状态明确当前动作；不冒充旧版的谱线锁定。
- `capture / preheat / stop`：来自 `Spec Source/Source/Main/mmAnalyze/FmDockGuideIgnit.dfm` 的 `IlIgnit`，索引0、3、4；保留闪电＋绿色箭头、蓝色B、蓝色停止圆形的识别特征。

生成使用四列三行1536×1152参考图、30步、CFG1、Euler/Simple、seed2026102512。首轮“适合图像”误成单向箭头，已用原图单独参考重绘为正确双向箭头，768×768、seed2026102513。仅去除与边缘相连的近白底，保留内部白色箭头、加减号等。

三类实时采集页面使用图标观察工具；其他谱图页面保持原呈现。所有观察工具保留中文无障碍名称与悬停说明，采集控制保留可见文字、原权限和动作。原始资源只读保留；默认Qwen工作流及服务配置保持。

提示词、参考图、生成原图、工作流、功能对应和验收结果见 `docs/acceptance-reports/S24/artifacts/2026-10-25-capture-icons/`。
