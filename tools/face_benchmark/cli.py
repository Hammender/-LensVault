from __future__ import annotations

import argparse
from pathlib import Path

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
    evaluate.add_argument("--model", default="buffalo_l", help="InsightFace 检测模型包")
    evaluate.add_argument("--recognition-onnx", type=Path, help="InsightFace 兼容的候选识别 ONNX")
    evaluate.add_argument("--provider", choices=["auto", "cpu", "cuda"], default="auto")
    evaluate.add_argument("--detection-size", type=int, default=640)
    evaluate.add_argument("--flip-tta", action="store_true")
    evaluate.add_argument("--threshold", type=float, default=0.45)
    evaluate.add_argument("--min-margin", type=float, default=0.08)
    evaluate.add_argument("--final-holdout", action="store_true")
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
    else:
        from .evaluate import evaluate_snapshot

        path = evaluate_snapshot(
            args.snapshot,
            model_name=args.model,
            recognition_onnx=args.recognition_onnx,
            provider=args.provider,
            detection_size=args.detection_size,
            flip_tta=args.flip_tta,
            threshold=args.threshold,
            min_margin=args.min_margin,
            final_holdout=args.final_holdout,
        )
        print(f"评测报告已生成：{path}")


if __name__ == "__main__":
    main()
