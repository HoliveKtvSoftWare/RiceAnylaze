# -*- coding: utf-8 -*-
"""旁路推理：在「另一套 ultralytics 运行时」里执行一次分割任务。

背景
----
两类权重不能在后端环境（ultralytics 8.3.27）里直接跑：

1. ASF-YOLO / Rice-SVBDete / SOD-YOLO / Subtle-YOLO 等对比方法，自定义模块在
   `ultralytics/nn/Addmodules/*`，依赖旧项目 fork；
2. OUR-best / exp12 / exp61 三个剑叶权重，训练时用的是带 **Mask Refinement Block**
   的检测头（权重里有 4 个 `mask_refine.*` 张量），而任何官方发行版的 `Segment`
   头都没有这个模块 —— 加载时会被静默丢弃、refinement 不生效，掩膜明显偏胖。

两者统一由项目自有的运行时副本 `.ultra_refine`（内核 8.4.23 fork + 带 refinement 的
检测头）承担，见 deploy/runtime/build_refine_ultralytics.py。为了不破坏后端已验证的环境，
后端在遇到 runtime="fork" 的任务时，用**另一个解释器**把本脚本作为子进程启动，
由它完成推理并写出结果文件。

本脚本**只依赖 numpy / PIL / torch / ultralytics**，不导入后端的配置模块
（那个环境可能没有 pydantic 等包），任务参数由后端以 JSON 文件传入。

进程间通信用文件（不依赖管道 stdio），因为受限环境下管道的 stdio 可能被拒绝。

用法由后端拼装，一般不需要手工调用：
    <fork python> sidecar_infer.py --spec <任务参数.json> --image <图片>
        --out-dir <输出目录> --basename <基名> --result-json <结果文件>
"""
import argparse
import json
import os
import sys
import traceback

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
WORKSPACE = os.path.dirname(BACKEND_DIR)
# 推理运行时：项目自有的 ultralytics 副本（内核 8.4.23 fork + 带 mask_refine 的检测头），
# 由 deploy/runtime/build_refine_ultralytics.py 生成，自包含、不依赖任何活目录。
# 后端通过环境变量 RICE_FORK_PROJECT 指定；缺省用下面这个。
DEFAULT_FORK_PROJECT = os.path.join(BACKEND_DIR, '.ultra_refine')
FORK_PROJECT = os.environ.get('RICE_FORK_PROJECT') or DEFAULT_FORK_PROJECT
APP_DIR = BACKEND_DIR    # 复用后端的推理实现 yolo_inference.py


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', required=True, help='任务参数 JSON（后端写出）')
    ap.add_argument('--image', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--basename', required=True)
    ap.add_argument('--result-json', required=True)
    args = ap.parse_args()

    result = {'ok': False}
    try:
        with open(args.spec, encoding='utf-8') as f:
            spec = json.load(f)

        # fork 的 ultralytics 优先（与“脚本同目录那份会遮蔽 pip 版”的行为一致）
        sys.path.insert(0, FORK_PROJECT)
        sys.path.insert(0, APP_DIR)
        os.chdir(APP_DIR)
        os.environ.setdefault('YOLO_CONFIG_DIR', os.path.join(BACKEND_DIR, '.ultralytics'))
        os.environ.setdefault('YOLO_OFFLINE', 'True')
        os.environ.setdefault('YOLO_AUTOINSTALL', 'false')

        import ultralytics
        from app.infrastructure.inference.runner import run_system

        print(f'[sidecar] ultralytics {ultralytics.__version__} ({os.path.dirname(ultralytics.__file__)})')
        # 关键自检：检测头是否带 mask_refine（OUR-best/exp12/exp61 必须为 True）
        try:
            import inspect
            from ultralytics.nn.modules.head import Segment
            has_refine = 'mask_refine' in inspect.getsource(Segment.__init__)
        except Exception as e:                                   # noqa: BLE001
            has_refine = f'检测失败({type(e).__name__})'
        print(f'[sidecar] 运行时目录 {FORK_PROJECT}')
        print(f'[sidecar] 检测头 mask_refine={has_refine}')
        print(f'[sidecar] 任务 {spec.get("key")} / {spec.get("name")} / 权重 {spec.get("model_path")}')

        annotated, json_path = run_system(
            model_path=spec['model_path'],
            image_path=args.image,
            output_path=args.out_dir,
            output_basename=args.basename,
            smooth=spec.get('smooth', True),
            smooth_exclude=tuple(spec.get('smooth_exclude', ())),
            embed_image=spec.get('embed_image', True),
            colors={k: tuple(v) for k, v in spec['colors'].items()} if spec.get('colors') else None,
            draw_first=tuple(spec.get('draw_first', ())),
            outline_labels=tuple(spec.get('outline_labels', ())),
            imgsz=spec.get('predict_imgsz'),
            conf=spec.get('conf', 0.25),
            iou=spec.get('iou', 0.7),
            retina_masks=spec.get('retina_masks', False),
            preview_smooth=spec.get('preview_smooth', False),
            preserve_mask_topology=spec.get('preserve_mask_topology', False),
            validate_side_bundles=spec.get('validate_side_bundles', False),
        )
        result = {
            'ok': True,
            'ultralytics': ultralytics.__version__,
            'runtime': FORK_PROJECT,
            'mask_refine': has_refine,
            'annotated_image_path': annotated,
            'result_json_path': json_path,
        }
        print(f'[sidecar] 完成: {annotated}')
    except Exception as e:                                   # noqa: BLE001
        result = {'ok': False, 'error': f'{type(e).__name__}: {e}',
                  'traceback': traceback.format_exc()[-2000:]}
        print('[sidecar] 失败:', result['error'])
        traceback.print_exc()

    with open(args.result_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
