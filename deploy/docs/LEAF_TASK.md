# 剑叶分析（task_type = leaf）说明

本系统原来只有一种分析（水稻**茎秆**横切面），现在引入了"分析类型"维度，新增**剑叶**横切面分析。
两种类型可以并存，各自用各自的模型、标签体系、可视化配色和 Excel 指标口径。

> ⚠️ **2026-09-15 更正**：本文档下面关于 `exp12` / `exp61` / `OUR-best` 的 IoU
> （0.324 / 0.266 / 0.321）是在**检测头未修复**的情况下测的，已失效。
> 这三个权重含有训练好的 MaskRefinement 分支（4 个 `mask_refine.*` 张量），
> 官方 ultralytics 的 `Segment` 头没有该模块，加载时被静默丢弃，导致掩膜偏胖约 1.7 倍、
> 小维管束大量丢失。现已融合带 refinement 的检测头（运行时 `.ultra_refine`），
> 详见 `deploy/REFINE_HEAD.md`；这三个任务的 IoU/对比结论需按新运行时重测。
> `leaf`(exp59) 与 `leaf_v11`(exp08) 不含 refinement，数值不受影响。

---

## 一、改了什么

| 位置 | 内容 |
|---|---|
| `app/core/tasks.py`（新增） | 任务注册表：每个分析类型登记模型路径、配色、绘制层次、是否平滑、是否内嵌原图、指标口径、是否自动识别比例尺 |
| `app/models/analysis.py` | `analyses` 表新增 `task_type`（默认 `stem`） |
| 数据库 | `ALTER TABLE analyses ADD COLUMN task_type VARCHAR NOT NULL DEFAULT 'stem'` + 索引（无 Alembic，需手工执行一次，已在本机执行） |
| `app/api/endpoints/analysis_router.py` | `POST /upload`、`POST /upload/batch` 新增表单字段 `task_type`；`GET /history` 新增 `?task_type=` 且返回 `taskType`；新增 `GET /tasks` |
| `app/services/analysis_service.py` | 后台任务按 `task_type` 选模型与后处理参数 |
| `app/services/yolo_inference.py` | 配色表、绘制层次、平滑开关、是否内嵌原图全部参数化（默认值＝原茎秆行为） |
| `app/services/excel_download.py` | 指标按类型分表；新增剑叶指标；**统一改为自动识别比例尺** |
| `app/api/endpoints/excel_router.py` | `GET /columns?task_type=`；导出按记录类型取口径；混合类型批量导出直接 400 |
| 前端 | 左栏"选择模型"（原本只打日志、从未生效）改为真实的"分析类型"下拉；历史列表加类型徽标与筛选；Excel 弹窗列改为按类型向后端获取 |

**模型文件**（都在 `RiceAnylaze/models_yolo/`，均被 `.gitignore` 忽略，需单独备份）：

| 任务 key | 界面名称 | 权重 | 来源 | 实测总 IoU |
|---|---|---|---|---|
| `leaf` | 剑叶（默认） | `leaf-v11-p2-exp59.pt` | `yolov11_p2_best(exp59).pt` | **0.700** |
| `leaf_v11` | 剑叶 · YOLOv11-best | `leaf-v11-exp08.pt` | `yolov11_best(exp08).pt` | 0.669 |
| `leaf_our` | 剑叶 · OUR-best | `leaf-our-best.pt` | `OUR-best.pt` | **0.321** |

> **为什么默认不用 OUR-best.pt**：在 3 张带人工标注的剑叶图（`data_out_excel\测试数据`）上实测，
> `OUR-best.pt` 的总 IoU 只有 0.321，而且**会把两条侧脉合并成一个大区域**
> （side1 面积 5.27 倍、side2 只剩 0.23 倍，side2 IoU = 0.000）；
> `yolov11_p2_best(exp59)` 则达到 0.700，两条侧脉都能正确分开（side1/side2 IoU 0.67/0.47）。
> 复现脚本：`python deploy/eval_leaf_models.py 640 3`。
>
> 另外已确认：**这 5 个剑叶权重都不需要 `D:\Code\ultralytics-main\ultralytics\nn\Addmodules`
> 或改过的 `head.py`** —— 解包 `.pt` 内部的 pickle 引用，它们只引用原版类
> （`head.Segment`、`block.C3k2/C2PSA/SPPF/Proto/DFL`、`tasks.SegmentationModel`），
> 且加载时零告警、673 个张量全部对上。需要那些自定义模块的是 `Rice-SVBDete-best.pt`、
> `Subtle-YOLO-best.pt`（缺 `ultralytics.nn.Addmodules`）和 `SOD-YOLO-best.pt`（缺 `C2f_Faster_EMA`），
> 它们在本环境里根本加载不了。

---

## 二、剑叶模型的 11 个标签（notail 版）

| 标签 | 含义 |
|---|---|
| `body1` | **主脉**整条外轮廓（实心，含空腔） |
| `body2` | 主脉内部的**空腔**轮廓 |
| `side1` / `side2` | **两条侧脉**的带状区域轮廓（细长、来回折返） |
| `body_big` / `body1_small` | 主脉内的大 / 小维管束（注意前缀不对称，是上游命名遗留） |
| `body2_small` | 空腔小维管束 |
| `side1_big` / `side1_small` | 侧脉1 内的大 / 小维管束 |
| `side2_big` / `side2_small` | 侧脉2 内的大 / 小维管束 |

> 与完整标注体系（`data.yaml` 的 19 类）相比，notail 模型**没有** `first1/first2/end1/end2`
> （侧脉带子的起止点标记）以及 `tail*` 类，因此参考脚本里那列"维管束排列顺序（B/S 串）"**无法计算**。
> 这也正是本期不做该列的原因。

---

## 三、剑叶指标（35 列）

记 `k` = 像素当量（µm/px，自动识别，见第五节）；`A_x` = 区域 x 的多边形面积（px²）；
`P_x` = 区域 x 的多边形周长（px）；`a_i` = 第 i 个维管束的面积（px²）；
`cf` = 单位换算系数（µm=1、mm=1000、cm=10000）。

| 列 key | 中文名 | 公式 |
|---|---|---|
| `filename` | 样本名称 | 结果 JSON 的文件名 |
| `scaleUmPerPx` | 比例尺(µm/px) | `k` |
| `sectionArea` | 截面面积(含腔) | `(A_body1 + A_side1 + A_side2) × k² / cf²` |
| `tissueArea` | 组织净面积 | `(A_body1 − A_body2 + A_side1 + A_side2) × k² / cf²` |
| `body1Area` / `body2Area` / `side1Area` / `side2Area` | 主脉 / 空腔 / 侧脉1 / 侧脉2 面积 | `A_x × k² / cf²` |
| `body1Perimeter` / `body2Perimeter` / `side1Perimeter` / `side2Perimeter` | 各自周长 | `P_x × k / cf` |
| `side1HalfPerimeter` / `side2HalfPerimeter` | 侧脉1 / 侧脉2 周长÷2 | `P_sideX × k / cf / 2` |
| `bodyBigCount` / `bodySmallCount` / `cavitySmallCount` | 主脉大 / 主脉小 / 空腔小维管束**数目** | 实例计数（`body_big` / `body1_small` / `body2_small`） |
| `side1BigCount` / `side1SmallCount` / `side2BigCount` / `side2SmallCount` | 侧脉1/2 的大 / 小维管束数目 | 实例计数 |
| `bodyBigTotalArea` 等 7 个 `*TotalArea` | 各类维管束**总面积** | `Σa_i × k² / cf²` |
| `bodyBigAvgArea` 等 7 个 `*AvgArea` | 各类维管束**平均面积** | `(Σa_i / n) × k² / cf²`（n=0 时为 0） |

面积用鞋带（格林）公式，周长用逐段弦长求和（含闭合段），与 `cv2.contourArea` / `cv2.arcLength` 等价，
不依赖 OpenCV。

---

## 四、相对参考脚本（`4-30-2026侧脉代码.py`）的口径修正

| 项 | 参考脚本 | 本系统 | 原因 |
|---|---|---|---|
| 截面面积 | `body1 + side1 + side2 + body2` | `body1 + side1 + side2`（另给"组织净面积"= `body1 − body2 + side1 + side2`） | 空腔 100% 位于主脉内部，原式把空腔**重复计入**（130/130 样本验证，差约 15%） |
| 截面周长 | `P_body1 + P_side1 + P_side2 − 连接长度`（实测仅减 ~15px） | 直接输出各区域周长，并按文档额外给"侧脉周长÷2" | 原"减连接长度"的魔改与文档"周长除以2"完全不符，且新旧两版实现还不一致 |
| 大小维管束 | 大维管束按标签重算、小维管束用骨架投影结果（**口径不同源**，会出"数目>0 面积=0"的矛盾行） | 统一按标签直接统计 | 消除自相矛盾；代价是与旧结果数值不完全可比 |
| 比例尺 | `k = 500 / 比例尺像素长度` | 同 | 一致（本系统自动化了） |

**上游参考数据本身的问题（本系统不受影响）**：`label_position_report.txt` 记录 31 处标注错位
（`side1_small` 落在 side2 等），且修正前就已进入旧导出结果（如 17-2 的侧脉小维管束系列不可用）。
本系统用的是模型预测，不存在标注错位问题，但模型自身若把 side1/side2 混淆，目前**不做几何校验**。

---

## 五、比例尺自动识别（重要行为变更）

从图像**右下象限**找纯红/纯蓝像素，取"单行红+蓝像素数"的最大值 `s` 作为 500µm 比例尺线条长度，
则 `k = 500 / s`（µm/px）。识别失败时回退到接口参数 `scale`。

实测：

| 图片 | 识别结果 |
|---|---|
| 剑叶 `10-1.tif` | `s = 337` → **1.4837 µm/px**（与参考脚本文档记载的 337 一致） |
| 茎秆 `21c-02.png` | **1.9455 µm/px** |

> ⚠️ **这修掉了一个老 bug**：历史实现里 `scale` 前端从不传、后端默认写死 `500`（µm/px），
> 使茎秆面积虚高约 66000 倍——同一张茎秆图面积为 `847,487,308,529 µm²`（0.85 m²，物理上不可能），
> 修正后为 `12,831,190 µm²`（≈12.83 mm²，对应约 3.6mm 直径，合理）。
>
> 因此**历史茎秆 Excel 的面积/周长数值不可再与本系统结果直接比较**，需要重算。
> 若确实要退回旧行为：把 `app/core/tasks.py` 中 stem 的 `auto_scale` 改为 `False`（一行）。

---

## 六、怎么用

**界面**：左栏"分析类型"选 `茎秆截面` 或 `剑叶` → 上传图片 → 历史列表可按类型筛选（全部/茎秆/剑叶），
每条记录带类型徽标 → 完成后导出 JSON / Excel，Excel 的列会随类型自动切换。

**接口**：

```bash
# 任务列表
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:5173/api/analysis/tasks

# 上传（task_type 不传等价于 stem，兼容旧客户端）
curl -H "Authorization: Bearer $TOKEN" -F "file=@10-1.tif" -F "task_type=leaf" \
     http://127.0.0.1:5173/api/analysis/upload

# 历史（按类型过滤）
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:5173/api/analysis/history?task_type=leaf"

# 列定义 / 导出
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:5173/api/excel/columns?task_type=leaf"
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"selectedColumns":["filename","side1Area","side1BigCount"],"unit":"um"}' \
     "http://127.0.0.1:5173/api/excel/<analysis_id>"
```

**验证脚本**：`python deploy/smoke_test_leaf.py [剑叶图] [茎秆图]` —— 覆盖登录、任务列表、列定义、
剑叶上传→推理→标注图→Excel 指标、茎秆回归、混合类型批量导出被拒，实测 **18/18 通过**。

---

## 七、已知限制 / 后续可做

1. **无"维管束排列顺序"列**：需要含 `first1/end1/first2/end2` 的 19 类权重（现有权重里没有）；
   也可以改用几何方法自动确定带子起点，但口径与旧结果不同，需另行确认。
2. **`.tif` 原图在浏览器里显示不了**：历史列表的"原图"直接用 `<img src=originalImageUrl>`，
   TIFF 不被浏览器支持。建议上传时另存一份 PNG/JPG 预览图。
3. **side1/side2 几何校验已启用**：仅当维管束中心点明确位于另一侧外轮廓、且距离优势超过阈值时才自动改类；
   重分类原因写入 JSON 的 `flags.side_reassigned_from` / `side_reassigned_by`，模糊点保持模型原分类。
4. **剑叶预览平滑与量测分离**：预览使用轮廓简化 + Chaikin 平滑，量测仍使用未平滑的拓扑轮廓；
   外环、内孔和有效连通域均保存在 JSON 中，Excel 面积扣除内孔、周长统计所有真实边界。
5. **极小孤岛会被过滤**：每个掩码保留最大连通域，并保留达到最大面积 0.1% 或至少 16 px² 的其他连通域；
   因此不会再用细线连接孤岛，也不会在预览中产生跨空白区域的长斜线。
6. **推理分辨率**：任务默认**不指定** `imgsz`，交给 ultralytics 使用权重自带的训练分辨率
   （茎秆权重自带 **1280**、剑叶权重自带 **640**）。这是踩过坑的结论：
   - 强行把茎秆模型压到 640 → 小维管束数目 32 掉到 21、分割质量下降；
   - 把 640 训练的剑叶模型放大到 1920/2560 → 预测数 108→165、匹配数 44→5，小目标被碎成大量假目标。
   需要时可在 `app/core/tasks.py` 的 `predict_imgsz` 单独指定。
7. **其余剑叶权重**：`yolov11_head_best(exp12)`（总 IoU 0.324）与 `yolov11_p2_head_best(exp61)`（0.266）
   实测更差，未登记；要做对比实验时在 `LEAF_MODEL_VARIANTS` 里加一行即可（同一套 11 类标签）。
8. **剑叶可视化**：四个区域**只描彩色轮廓**（实心填充会把整个切片染成一片色块、反而看不清结构），
   维管束用半透明填充，轮廓线宽按图像短边自适应。茎秆的配色与绘制层次完全未变
   （回归验证：标注图字节数与改造前一致，均为 351887 字节）。

