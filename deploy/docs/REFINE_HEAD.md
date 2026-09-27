# 检测头融合（mask_refine）说明

## 一、根因：三个剑叶权重的 refinement 分支一直被丢弃

`OUR-best` / `exp12` / `exp61` 这三个权重训练时用的是**带 Mask Refinement Block 的检测头**，
权重里存着 4 个张量：

```
model.29.mask_refine.0.weight (32,32,3,3)   model.29.mask_refine.0.bias
model.29.mask_refine.2.weight (32,32,3,3)   model.29.mask_refine.2.bias
```

而**任何官方发行版**的 `ultralytics.nn.modules.head.Segment` 都没有 `mask_refine`
子模块（已逐个核对：envs/fastapi 8.3.27、envs/yolo 8.3.167、ultralytics-main 8.3.133、
旧 fork 8.4.23 全部没有）。加载权重时这 4 个张量被**静默忽略**，refinement 完全不参与推理。

后果（同一张图 notail `10-1.tif`，与参考输出 `output/output_OUR-best` 对比）：

| 方案 | 覆盖率 | 与参考二值 IoU | 逐类像素 |
|---|---|---|---|
| **带 refinement（正确）** | **0.2026**（参考 0.2021） | **0.9229** | **11 类全部一致，实例数 105=105** |
| 官方头（丢 refinement） | 0.3475 | 0.4675 | side1 偏大 2.9×、side1_big 只有 2.4%、body2 只有 25% |

即：掩膜整体偏胖约 1.7 倍，小维管束（`*_small` / `*_big`）大量丢失。
**`deploy/LEAF_TASK.md` 里 exp12 / exp61 / OUR-best 的旧 IoU（0.32 / 0.27 / 0.32）是在
丢 refinement 的情况下测的，已失效，需重测**；不带 refinement 的 exp59(0.700) / exp08(0.669)
不受影响。

## 二、集成方案

```
deploy/heads/head_mask_refine.py          带 MaskRefinement 的检测头（项目内保存，MD5 578396A9…）
deploy/build_refine_ultralytics.py        构建下面的运行时（可重复执行）
D:\Code\Rice_system\RiceAnylaze\.ultra_refine\        项目自有的 ultralytics 运行时（自包含，勿手工改）
    ultralytics/                          内核 = 旧项目 fork 8.4.23（含 nn/Addmodules）
      nn/modules/head.py                  = head_mask_refine.py + 3 处适配补丁
      models/yolo/segment/predict.py      = proto 返回结构兼容补丁
```

后端改动：

| 文件 | 改动 |
|---|---|
| `app/core/config.py` | 新增 `FORK_PROJECT`（默认 `.ultra_refine`） |
| `app/services/analysis_service.py` | 传 `RICE_FORK_PROJECT` 环境变量给旁路子进程 |
| `deploy/sidecar_infer.py` | 从 `RICE_FORK_PROJECT` 取运行时目录；启动时打印 `mask_refine=` 自检；结果 JSON 带 `runtime`/`mask_refine` |
| `app/core/tasks.py` | `leaf_our` / `leaf_v11_head` / `leaf_v11_p2_head` 的 runtime 由 `native` 改为 `fork` |

为什么走子进程：内核必须是 8.4.23 fork（对比方法权重的 `nn/Addmodules`、`C2f_Faster_EMA`
都在里面），而后端环境是 8.3.27。子进程用 `settings.FORK_PYTHON` + `.pylibs`，与后端环境隔离。

## 三、运行时里对头做的 3 处适配（都由 build 脚本自动施加）

1. **YOLO26 别名**：本头是 8.3 代次，没有 `Segment26/OBB26/Pose26/YOLOESegment26`，
   而 8.4.23 内核的 `nn/modules/__init__.py`、`nn/tasks.py` 会 import 它们 →
   别名到基类即可。项目内**所有权重都不含 YOLO26 结构**（已逐个扫描 pickle：无
   `one2one` / `Segment26`），因此无副作用。
2. **经典代次 proto 兼容**（`models/yolo/segment/predict.py`）：8.4.23 预测器按
   `protos = preds[0][1]` 取原型掩膜（新式头返回 `((det, proto), …)`），而本头返回
   `(det, (feats, mc, proto))`。不兼容时表现为
   `AttributeError: 'list' object has no attribute 'shape'`。补丁让两种结构都能识别。
3. **refinement 条件执行**：对比方法（ASF/SVBDete/SOD/Subtle）的权重里**没有**
   `mask_refine`，反序列化后的 `Segment` 实例自然也没有该子模块，直接调用会
   `AttributeError: 'Segment' object has no attribute 'mask_refine'`。补丁改成
   `if hasattr(self, "mask_refine"):` —— 有权重的照跑 refinement，没有的跳过。

## 四、验证

```bat
:: 1) 运行时自检（应输出 mask_refine 生效: True）
D:\Anaconda\envs\yolo\python.exe deploy\build_refine_ultralytics.py --check

:: 2) 端到端：真实旁路通道跑全部任务（后端环境）
D:\Anaconda\envs\fastapi\python.exe deploy\verify_refine_tasks.py
```

实测结果（2026-09-15）：

* 7 个 fork 任务全部通过：`leaf_our` 103 shapes / `leaf_v11_head` 62 / `leaf_v11_p2_head` 61 /
  `leaf_asf` / `leaf_svbdet` 103 / `leaf_sod` 102 / `leaf_subtle` 102，
  sidecar 日志均报 `ultralytics=8.4.23 runtime=.ultra_refine mask_refine=True`，
  单张 5.8~9.8 s。
* 原生任务不受影响：`leaf`（exp59）59 shapes、`leaf_v11`（exp08）61 shapes。
* 与参考输出复现：覆盖率 0.2026 vs 0.2021，逐类实例数 105=105，二值 IoU 0.9229。

## 五、重建 / 回退 / 复现

```bat
:: 重建（头有改动时执行；会清空 .ultra_refine）
D:\Anaconda\envs\yolo\python.exe deploy\build_refine_ultralytics.py

:: 用项目运行时复现参考输出（命令行，与 output_OUR-best 逐类一致）
set PYTHONPATH=D:\Code\Rice_system\RiceAnylaze\.ultra_refine
D:\Anaconda\envs\yolo\python.exe deploy\yolov11_seg_mask10_patched.py ^
    --images "D:\BaiduNetdiskDownload\rice_notail_data(20260701)" --only 10-1 --save <输出目录>

:: 回退某个任务：把 app/core/tasks.py 里对应 runtime 改回 "native"（会丢 refinement）
```

`FORK_PROJECT` 可在 `RiceAnylaze\.env` 里覆盖，例如临时指向别的运行时做 A/B。

> 历史：早期曾用 `deploy/build_patched_ultralytics.py` 把 fork 的 8.4.23 头装进
> 8.3.27 内核生成 `.ultra_patched`（结论见 `HEAD_AB_RESULT.md`）。那条路线只能改掩膜边界、
> 且拿不到 refinement，已被本方案取代，相关脚本与目录已清理。工作区总览见根目录 `README.md`。

## 六、待办

- 重测 exp12 / exp61 / OUR-best 的 IoU（`deploy/eval_leaf_models.py`），更新
  `deploy/LEAF_TASK.md` 与 `tasks.py` 里的 note。
- 若日后拿到不含 refinement 的新权重，无需改代码，运行时会自动跳过。

