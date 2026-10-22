# 旧版快捷栏图标

从 `Spec Source/Source/Main/FmMain.dfm` 的 `ImageListMain.Bitmap` 只读提取，使用原图像和原单色透明蒙版。每个图标为 16×16 PNG；界面按 24×24 显示并保持像素边缘。未使用用户截图作为裁切源，未改写历史工程。

| 文件 | ImageIndex | 旧动作 |
|---|---:|---|
| new-method.png | 0 | ActNew |
| open-method.png | 1 | ActOpen |
| save-as.png | 2 | ActSaveAs |
| conditions.png | 5 | ActMtdCfg |
| lines.png | 6 | ActMtdLines |
| acquisition.png | 10 | ActAcqSam |
| samples.png | 14 | ActInputSamp |
| analysis.png | 15 | ActAnaSam |

按钮文案、排版与目标见 `layout/QuickAccessBar.tsx`。样品流程按预录、摄谱、分析的操作顺序排列；磁盘图标沿用旧版“另存为”含义。
