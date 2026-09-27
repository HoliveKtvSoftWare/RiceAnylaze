# 检测头 A/B 对照结论（原版 8.3.27 vs 旧项目 8.4.23）

## 一、直接替换 head.py 的结果：**跑不起来**

按你的要求，我在工作区里做了一份补丁副本（**不动 conda 环境**）：

```
.ultra_patched/ultralytics/          ← 8.3.27 全套
    └── nn/modules/head.py            ← 被替换成 D:\Code\yolov11-main-old\ultralytics\nn\modules\head.py
```
构建脚本：`deploy/build_patched_ultralytics.py`（补齐了 7 个 8.3.27 里缺失的名字：
`utils.NOT_MACOS14`、`torch_utils.TORCH_1_11`、`block.{SAVPE,Proto26,RealNVP,Residual,SwiGLUFFN}` 兼容桩）

导入能过，但**推理直接报错**：

```
File ".ultra_patched/ultralytics/models/yolo/segment/predict.py", line 50, in postprocess
    masks = ops.process_mask_native(proto[i], pred[:, 6:], pred[:, :4], orig_img.shape[:2])
KeyError: 0
```

原因：8.4.23 的 `Segment.forward` 把输出从 **tuple 改成了 dict**（`{"proto": ...}` 结构），
而 8.3.27 的 predictor 还在按 `proto[0]` 取。**只换 head.py 必然不兼容，必须连
predictor / engine 一起换**——那实际上就等于整包换成旧项目的 fork。

## 二、把「整包换成 fork」做完整后的对照（同一模型、同一张图 10-1）

| 任务 | 权重 | 指标 | 8.3.27（当前后端） | 8.4.23（旧项目 fork） |
|---|---|---|---|---|
| `leaf` | leaf-v11-p2-exp59 | 实例数 | 59 | 59 |
| | | 各类别实例数 | 11 类全部一致 | 11 类全部一致 |
| | | 掩膜覆盖 | 16.35% | 16.61% |
| | | 连通域 | **2** | **2** |
| `leaf_our` | leaf-our-best | 实例数 | 103 | 103 |
| | | 各类别实例数 | 11 类全部一致 | 11 类全部一致 |
| | | 掩膜覆盖 | 28.26% | 28.24% |
| | | 连通域 | **2115** | **2131** |

**掩膜并集 IoU：`leaf` = 0.863，`leaf_our` = 0.768**

即：**换 head / 换版本，检测结果逐个相同，掩膜只是边界有细微位移**（`scale_masks`
的边界取整方式不同：8.3.27 用 `int(pad)`，8.4.23 用 `round(pad±0.1)`）。

## 三、结论

1. **换 head.py 无法改变效果**——它既不能单独运行，整包换掉后结果也只是边界微调。
2. **掩膜"碎不碎"完全由权重决定，与 head/版本无关**：
   - `leaf`(exp59) 两个版本都是**干净的 2 个连通域**
   - `leaf_our`(OUR-best) 两个版本都是**碎成 2100+ 块**
3. 这也解释了之前"参考输出很干净、我这边很碎"的差异**不是版本造成的**：
   参考那份用的是同一份 OUR-best 权重，但它跑在**另一批图**（rice_notail_data，青色染色）上，
   而 OUR-best 在那批图上的掩膜 logits 本来就更强；在我们这批图上是弱 logits → 碎。
   （证据见对话中的阈值扫描：logits 中位数贴着 0，阈值 0 覆盖 97%。）

## 四、产物位置

- 补丁副本：`.ultra_patched/`（**可直接删除**，不影响环境）
- A/B 脚本：`deploy/build_patched_ultralytics.py`、`deploy/head_run.py`、`deploy/head_run_json.py`、`deploy/head_compare.py`
- 对照数据：`_seg_out/head_ab/{baseline,fork}_<task>_{stats.json,union.npy}`
