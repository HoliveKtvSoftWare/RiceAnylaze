"""Compare baseline archive and migrated inference without database access."""
import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))
os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT / '.ultralytics'))
os.environ['YOLO_OFFLINE'] = 'True'
os.environ['YOLO_AUTOINSTALL'] = 'false'


def run_one(args):
    spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
    if args.fork:
        sys.path.insert(0, os.environ['RICE_FORK_PROJECT'])
    if args.mode == 'baseline':
        with zipfile.ZipFile(ROOT / '.run/architecture-baseline-20260922.zip') as archive:
            for name, path in [('app.services.mask_geometry', 'app/services/mask_geometry.py'),
                               ('baseline_inference', 'app/services/yolo_inference.py')]:
                module = types.ModuleType(name)
                module.__file__ = str(ROOT / path)
                sys.modules[name] = module
                exec(compile(archive.read(path).decode('utf-8-sig'), str(ROOT / path), 'exec'), module.__dict__)
        runner = sys.modules['baseline_inference'].run_system
    else:
        from app.infrastructure.inference.runner import run_system as runner
    runner(model_path=spec['model_path'], image_path=args.image,
           output_path=args.output, output_basename='comparison',
           smooth=spec['smooth'], smooth_exclude=tuple(spec['smooth_exclude']),
           embed_image=spec['embed_image'], colors={k: tuple(v) for k,v in spec['colors'].items()},
           draw_first=tuple(spec['draw_first']), outline_labels=tuple(spec['outline_labels']),
           imgsz=spec['predict_imgsz'], conf=spec['conf'], iou=spec['iou'],
           retina_masks=spec['retina_masks'], preview_smooth=spec['preview_smooth'],
           preserve_mask_topology=spec['preserve_mask_topology'],
           validate_side_bundles=spec['validate_side_bundles'])


def compare(image_path):
    from app.core.config import settings
    from app.features.task_catalog import get_task
    image = Path(image_path).resolve()
    assert image.is_file()
    output = ROOT / '.run/inference-comparison'
    output.mkdir(exist_ok=True)
    reports = []
    for key in ['leaf', 'leaf_our']:
        task = get_task(key)
        spec_path = output / (key + '-spec.json')
        spec_path.write_text(json.dumps(dataclasses.asdict(task)), encoding='utf-8')
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['PYTHONPATH'] = settings.FORK_PYLIBS + os.pathsep + str(ROOT)
        env['RICE_FORK_PROJECT'] = settings.FORK_PROJECT
        for mode in ['baseline', 'migrated']:
            dest = output / key / mode
            dest.mkdir(parents=True, exist_ok=True)
            python = settings.FORK_PYTHON if task.runtime == 'fork' else sys.executable
            if mode == 'migrated' and task.runtime == 'fork':
                cmd = [python, '-B', settings.SIDECAR_SCRIPT, '--spec', str(spec_path),
                       '--image', str(image), '--out-dir', str(dest), '--basename', 'comparison',
                       '--result-json', str(dest / 'sidecar-result.json')]
            else:
                cmd = [python, '-B', str(Path(__file__).resolve()), '--mode', mode,
                       '--spec', str(spec_path), '--image', str(image), '--output', str(dest)]
                if task.runtime == 'fork':
                    cmd.append('--fork')
            print('Running', key, mode, flush=True)
            with (dest / 'run.log').open('w', encoding='utf-8') as log:
                subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)
        baseline = output / key / 'baseline'
        migrated = output / key / 'migrated'
        old = json.loads((baseline / 'comparison.json').read_text())
        new = json.loads((migrated / 'comparison.json').read_text())
        assert old == new, key + ': LabelMe changed'
        assert (baseline / 'comparison.jpg').read_bytes() == (migrated / 'comparison.jpg').read_bytes(), key + ': preview changed'
        report = {'task': key, 'runtime': task.runtime, 'shapes': len(new['shapes']),
                  'labelme_identical': True, 'preview_identical': True,
                  'json_sha256': hashlib.sha256((migrated / 'comparison.json').read_bytes()).hexdigest()}
        if task.runtime == 'fork':
            meta = json.loads((migrated / 'sidecar-result.json').read_text(encoding='utf-8'))
            assert meta['ok'] and meta['mask_refine'] is True
            report['mask_refine'] = meta['mask_refine']
        reports.append(report)
        print(json.dumps(report), flush=True)
    (output / 'report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode')
    parser.add_argument('--spec')
    parser.add_argument('--image', required=True)
    parser.add_argument('--output')
    parser.add_argument('--fork', action='store_true')
    args = parser.parse_args()
    run_one(args) if args.mode else compare(args.image)
