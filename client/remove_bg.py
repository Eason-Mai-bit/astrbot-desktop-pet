import argparse
from pathlib import Path

from rembg import new_session, remove


def remove_background(
    input_path: Path,
    output_path: Path,
    model: str = "u2netp",
    alpha_matting: bool = False,
) -> None:
    data = input_path.read_bytes()
    session = new_session(model)
    kwargs: dict = {}
    if alpha_matting:
        kwargs.update(
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=10,
            alpha_matting_erode_size=10,
        )
    result = remove(data, session=session, **kwargs)
    output_path.write_bytes(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="为桌宠立绘去背景并导出透明 PNG")
    parser.add_argument("input", type=Path, help="输入图片路径")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("enterprise_transparent.png"),
        help="输出透明 PNG 路径",
    )
    parser.add_argument(
        "--model",
        default="u2netp",
        choices=["u2net", "u2netp", "u2net_human_seg", "isnet-general-use", "silueta"],
        help="rembg 模型（默认 u2netp，换 isnet-general-use 更精准）",
    )
    parser.add_argument(
        "--alpha-matting",
        action="store_true",
        help="启用 Alpha Matting 后处理，保护边缘不被过度切除",
    )
    args = parser.parse_args()

    remove_background(args.input, args.output, model=args.model, alpha_matting=args.alpha_matting)
    print(f"已输出：{args.output}（模型: {args.model}，Alpha Matting: {args.alpha_matting}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
