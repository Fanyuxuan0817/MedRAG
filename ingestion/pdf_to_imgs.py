import sys
import argparse
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("错误: 需要安装 PyMuPDF")
    print("请运行: pip install pymupdf")
    sys.exit(1)

# ==================================================
# 路径配置（与你原项目一致）
# ==================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PDF_DIR = BASE_DIR / "data" / "raw" / "pdf"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output" / "pdf_imgs"


# ==================================================
# PDF -> 图片
# ==================================================
def pdf_to_images(pdf_path: Path, output_dir: Path, dpi: int = 200) -> list[Path]:
    """
    将单个 PDF 每页转成 PNG 图片
    """
    doc = fitz.open(str(pdf_path))
    img_paths = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]

        scale = dpi / 72
        matrix = fitz.Matrix(scale, scale)

        pix = page.get_pixmap(matrix=matrix)

        img_name = f"{pdf_path.stem}_p{page_idx + 1:03d}.png"
        img_path = output_dir / img_name

        pix.save(str(img_path))
        img_paths.append(img_path)

    doc.close()
    return img_paths


# ==================================================
# 批量处理单个PDF
# ==================================================
def process_pdf(pdf_path: Path, output_root: Path, dpi: int = 200):
    pdf_name = pdf_path.stem

    pdf_output_dir = output_root / pdf_name
    pdf_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print("处理 PDF:", pdf_path.name)
    print(f"{'='*60}")

    img_paths = pdf_to_images(pdf_path, pdf_output_dir, dpi=dpi)

    print(f"已导出 {len(img_paths)} 张图片")
    print("输出目录：", pdf_output_dir)

    return img_paths


# ==================================================
# 主程序
# ==================================================
def main():
    parser = argparse.ArgumentParser(
        description="批量 PDF 转图片工具（pdf_to_imgs）"
    )

    parser.add_argument(
        "-i", "--input-dir",
        type=str,
        default=str(DEFAULT_PDF_DIR),
        help="PDF输入目录"
    )

    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="图片输出目录"
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="输出清晰度，默认200"
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="指定PDF文件"
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 指定文件
    if args.files:
        pdf_files = [Path(f) for f in args.files]

    # 扫描目录
    elif input_dir.is_dir():
        pdf_files = sorted(input_dir.glob("*.pdf"))

    else:
        print("错误：目录不存在", input_dir)
        sys.exit(1)

    if not pdf_files:
        print("未找到 PDF 文件")
        sys.exit(1)

    print(f"找到 {len(pdf_files)} 个 PDF 文件")
    print("输出目录：", output_dir)

    total = 0

    for pdf_path in pdf_files:
        try:
            imgs = process_pdf(
                pdf_path=pdf_path,
                output_root=output_dir,
                dpi=args.dpi
            )
            total += len(imgs)

        except Exception as e:
            print(f"处理失败 {pdf_path.name}: {e}")

    print(f"\n{'='*60}")
    print(f"全部完成，共导出 {total} 张图片")
    print("输出目录：", output_dir)
    print(f"{'='*60}")


if __name__ == "__main__":
    main()