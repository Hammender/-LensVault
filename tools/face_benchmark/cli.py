from __future__ import annotations

import argparse
from pathlib import Path

from face_runtime import available_adapters

from .config import REPO_ROOT, SourceConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="独立人脸识别评测工具")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="从主程序只读抽取冻结评测快照")
    create.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    create.add_argument("--output", type=Path, default=REPO_ROOT / "data" / "face-benchmark")
    create.add_argument("--workspace-id", type=int)
    create.add_argument("--face-count", type=int, default=1000)
    create.add_argument("--detection-count", type=int, default=150)
    create.add_argument("--seed", type=int, default=20260731)
    create.add_argument("--snapshot-id")
    label = commands.add_parser("label", help="启动独立本地标注页面")
    label.add_argument("snapshot", type=Path)
    label.add_argument("--host", default="127.0.0.1")
    label.add_argument("--port", type=int, default=8765)
    evaluate = commands.add_parser("evaluate", help="运行候选模型离线评测")
    evaluate.add_argument("snapshot", type=Path)
    evaluate.add_argument("--adapter", choices=available_adapters(), default="buffalo_l")
    evaluate.add_argument("--model-path", type=Path, help="适配器对应的官方 ONNX 权重")
    evaluate.add_argument("--detector-pack", default="buffalo_l", help="InsightFace 检测模型包")
    evaluate.add_argument("--provider", choices=["auto", "cpu", "coreml", "cuda"], default="auto")
    evaluate.add_argument("--detection-size", type=int, default=640)
    evaluate.add_argument("--flip-tta", action="store_true")
    evaluate.add_argument("--threshold", type=float, default=0.45)
    evaluate.add_argument("--min-margin", type=float, default=0.08)
    evaluate.add_argument("--final-holdout", action="store_true")
    evaluate.add_argument("--no-cache", action="store_true", help="本次评测不读取或写入缓存")
    compare = commands.add_parser("compare", help="按基线安全约束比较 calibration 结果")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("candidates", type=Path, nargs="+")
    compare.add_argument("--output", type=Path)
    compare.add_argument("--min-labels", type=int, default=100)
    compare.add_argument("--min-people", type=int, default=20)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "create":
        from .snapshot import create_snapshot

        path = create_snapshot(
            SourceConfig.from_env(args.env),
            args.output,
            workspace_id=args.workspace_id,
            face_target=max(0, args.face_count),
            detection_target=max(0, args.detection_count),
            seed=args.seed,
            snapshot_id=args.snapshot_id,
        )
        print(f"评测快照已生成：{path}")
    elif args.command == "label":
        from .server import serve

        serve(args.snapshot, args.host, args.port)
    elif args.command == "evaluate":
        from .evaluate import evaluate_snapshot

        path = evaluate_snapshot(
            args.snapshot,
            adapter_id=args.adapter,
            model_path=args.model_path,
            detector_pack=args.detector_pack,
            provider=args.provider,
            detection_size=args.detection_size,
            flip_tta=args.flip_tta,
            threshold=args.threshold,
            min_margin=args.min_margin,
            final_holdout=args.final_holdout,
            use_cache=not args.no_cache,
        )
        print(f"评测报告已生成：{path}")
    else:
        from .compare import compare_results

        path = compare_results(
            args.baseline,
            args.candidates,
            output_dir=args.output,
            min_labels=max(1, args.min_labels),
            min_people=max(1, args.min_people),
        )
        print(f"候选比较报告已生成：{path}")


if __name__ == "__main__":
    main()
