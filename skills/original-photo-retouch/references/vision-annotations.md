# ChatGPT 视觉标注 → 原尺寸 Photoshop 蒙版

识别由当前 ChatGPT/Codex 视觉模型完成：实际打开原片基线和局部图，判断可见物体、受光和轮廓，然后写数据。脚本不内置另一个识别模型，不训练用户照片，不调用 PS 自动识别，也不把生成参考图的轮廓套到原片上。模型坐标有误差；预览及原生蒙版检查是工作流程的一部分。

先用 Photoshop `prepare` 产生方向正确、全尺寸的 `_baseline.jpg`。RAW 保留原文件作为最终像素来源，标注基线仅提供坐标系。初始化：

```text
python -X utf8 scripts/photo_annotations.py init --source 原片.CR2 --baseline PS基线_baseline.jpg --prepared-report PS基线_execution.json --out 标注草稿.json
```

普通已正确显示的 JPEG 可用自身作基线，无需 `--prepared-report`。先 `view_image` 查看基线。初始化文件只有空区域；它不代表完成识别。

`canvas` 是未裁切的、方向已正确显示的 PS 文档宽高。`views` 默认含整图 `baseline`。细节较难时，用 `inspection_images.py --bounds 左 上 右 下 --out 新局部.png` 从同一基线取不重采样的局部，再查看。把该图加入 `views`，记录真实绝对路径、文件 SHA256、像素 `size` 和基线上的整数 `native_bounds`。工具验证局部图像素确实对应这块基线，尺寸相同但位置错误的局部会被拒绝。不要使用相机预览或 image2 图来精确映射原生文档。

每个 `region` 保存：

- 唯一 `id`、可见部位 `label`、本次光影用途 `intent`、`confidence:high/medium/low`、具体 `edge_notes`，以及 `feather_px`。羽化按原尺寸像素，最大 250；不是预览屏幕像素。
- `contours` 内每个形状指定 `view_id` 和 `operation:add/subtract`。坐标在该观察图中归一化为 0..1，工具按局部边界映射回整幅。合并全部 add 后扣除全部 subtract，可表达多块主体和手臂之间的背景空隙。
- 多边形：`kind:polygon, points:[[x,y],...]`。
- 闭合平滑曲线：`kind:bezier, nodes:[{anchor:[x,y], in:[x,y], out:[x,y]},...]`。相邻锚点之间由当前 out 和下个 in 定义三次曲线，缺少手柄时使用锚点。工具按原尺寸最多 0.5 像素的几何误差细分；此数值仅指曲线计算，不能代表模型识别精度。
- 柔和局部光影可用 `kind:ellipse, bounds:[左,上,右,下]`。需要主体轮廓时用实际轮廓，不能用矩形或大椭圆冒充精细分割。发丝/毛帽细节要看局部；不确定的半透明边缘不应作硬切色温的边界。

示意区域（坐标须由实际看图确定，不是默认人像预设）：

```json
{
  "id":"face_light", "label":"帽檐下面部", "intent":"沿现场受光柔和加光",
  "confidence":"medium", "edge_notes":"光影区域，不作为皮肤或头发的精细轮廓",
  "feather_px":120,
  "contours":[{"view_id":"baseline","kind":"ellipse","operation":"add","bounds":[0.32,0.31,0.54,0.47]}]
}
```

生成、查看并修正预览，逐张确认位置、空隙、边缘和用途：

```text
python -X utf8 scripts/photo_annotations.py overlay 标注草稿.json --out 标注预览_v1.png
```

预览上的编号对应同名 `.annotation-review.json` 的图例；`+` 为增加区域，`-` 为扣除。预览只显示几何边界，不显示最终羽化/调整强度。用 `view_image` 实际查看后，记录判断并形成新的已复核文件：

```text
python -X utf8 scripts/photo_annotations.py accept 标注草稿.json --review-report 标注预览_v1.annotation-review.json --notes "实际位置与边缘判断" --out 标注已复核.json
```

accept 是模型复核记录，不要求用户点确认；用户已授权时自主执行。文件、形状或羽化改变后，复核摘要失效，须生成并查看新预览。不能批量自动 accept 没看过的标注。`compile` 可输出归一化几何用于诊断，配方必须仍引用已复核原始标注。

把已复核文件写入配方 `annotations`，步骤用 `region.kind:annotation` 和区域 `id`。多个曲线层可复用一个区域；源 PSD 始终来自原片。PS 文档必须与标注 canvas 一致，最终裁切在所有区域执行后发生。坐标选择、抗锯齿、羽化和调整图层蒙版均由本地 Photoshop 原生 API 完成，无需自动识别或导入重画的图像像素。

原生蒙版形成后继续检查适屏及 100%：几何轮廓是否偏移，颜色是否溢到皮肤/白帽，山脊或头发是否有亮边，原焦点和纹理是否保留。必要时重新标注局部、减弱调整、加大柔和光影过渡或手工完善；预览复核不能代替成片验收。

## 光影羽化与主体边缘分开控制

旧配方默认 `feather_mode:combined`：先合并/扣除，再应用区域的 `feather_px`。
需要宽光影渐变、窄主体保护时，明确设置区域 `feather_mode:per_contour, feather_px:0`，并为每条轮廓提供原生像素 `feather_px`。例如 add 光影250px、subtract主体40px。每条轮廓在Photoshop选择时羽化，最后不再整体模糊。数值必须根据实际毛发/光影判断；硬边或外扩主体轮廓仍可能造成光圈，独立羽化不能自动纠正错误轮廓。

几何预览通过后，可在已运行且零文档的Photoshop中执行：

```text
python -X utf8 scripts/inspect_annotation_masks.py 标注已复核.json 新诊断目录 区域ID1 区域ID2
```

每次最多3个区域，生成原生尺寸灰度PNG与哈希证明，然后请求正常退出Photoshop。它使用与精修相同的原生选区引擎；白色代表选中、黑色代表保护。仅作蒙版诊断，不得作为原片或成片像素来源。调用遵守NativeGuard、16GiB空间与项目时限；结果未知时先检查保存文件，禁止直接重跑。结合原生100%原片裁切检查实际覆盖，必要时修正轮廓并重新复核。

## 大尺度光场与窄岸线保护

宽水面亮区需要超过单次250px的过渡时，可以显式使用 `broad_feather_px`。它只允许 `feather_mode:per_contour`、区域 `feather_px:0`，且恰好一个 `feather_px:0` 的 add 轮廓。数值范围为1至 `min(1000, 短边/3)` 原生像素；不接受多个正轮廓、隐含二次羽化或未复核的参数修改。

引擎先用多次不超过250px的Photoshop原生羽化拓宽正光场，再扣除各自窄羽化的岸线/主体保护。次数为 `ceil((broad/250)^2)`，单次半径为 `broad/sqrt(次数)`。这是近似过渡尺度，不是测得的高斯sigma，也不保证Photoshop不同版本的响应完全一致。旧标注没有此字段时行为不变。

例：湖面add轮廓0px，`broad_feather_px:700`；山岸/前景subtract轮廓18px。坐标、宽度和强度仍须按本片观察选择。实际原生蒙版、整图、湖岸100%及同次光层开关都要检查；宽羽化不能自动修复错误标注，也不能拿来复制参考波纹。
