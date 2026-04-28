import os
import sys
import argparse
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("错误: 需要安装 PyMuPDF")
    print("请运行: pip install pymupdf")
    sys.exit(1)

try:
    from paddleocr import PPStructureV3
except ImportError:
    print("错误: 需要安装 PaddleOCR")
    print("请运行: pip install paddleocr paddlepaddle")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PDF_DIR = BASE_DIR / "data" / "raw" / "pdf"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output" / "raw_md"


def pdf_to_images(pdf_path: Path, output_dir: Path, dpi: int = 200) -> list[Path]:
    doc = fitz.open(str(pdf_path))
    img_paths = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        scale = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img_name = f"{pdf_path.stem}_p{page_idx + 1:03d}.png"
        img_path = output_dir / img_name
        pix.save(str(img_path))
        img_paths.append(img_path)
    doc.close()
    return img_paths


def ocr_images_to_markdown(image_paths: list[Path], pipeline, output_dir: Path) -> str:
    all_md_parts = []

    for img_path in image_paths:
        result = pipeline.predict(input=str(img_path))

        for res in result:
            res.save_to_markdown(save_path=str(output_dir))

            md_file = output_dir / f"{img_path.stem}.md"
            if md_file.exists():
                txt = md_file.read_text(encoding="utf-8").strip()
                if txt:
                    all_md_parts.append(txt)

    return "\n\n".join(all_md_parts)


def process_pdf(pdf_path: Path, output_dir: Path,
                pages_per_chunk: int = 7, dpi: int = 200) -> list[Path]:
    pdf_name = pdf_path.stem
    pdf_output_dir = output_dir / pdf_name
    pdf_output_dir.mkdir(parents=True, exist_ok=True)

    temp_img_dir = pdf_output_dir / "_temp_images"
    temp_img_dir.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"处理 PDF: {pdf_path.name}")
    print(f"{'='*60}")

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    doc.close()
    print(f"总页数: {total_pages}, 每组页数: {pages_per_chunk}")

    img_paths = pdf_to_images(pdf_path, temp_img_dir, dpi=dpi)
    print(f"已渲染 {len(img_paths)} 张图片")

    pipeline = PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False
    )

    output_files = []
    total_chunks = (len(img_paths) + pages_per_chunk - 1) // pages_per_chunk
    for chunk_idx in range(total_chunks):
        start = chunk_idx * pages_per_chunk
        end = min(start + pages_per_chunk, len(img_paths))
        chunk_imgs = img_paths[start:end]

        chunk_num = chunk_idx + 1
        out_filename = f"{pdf_name}_part{chunk_num:02d}.md"
        out_path = pdf_output_dir / out_filename

        page_range = f"第{start+1}-{end}页"
        print(f"\n  [{chunk_num}/{total_chunks}] OCR {page_range} ...")

        md_content = ocr_images_to_markdown(chunk_imgs, pipeline, temp_img_dir)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        output_files.append(out_path)
        print(f"  -> {out_path.name}")

    for img_path in temp_img_dir.glob("*.png"):
        img_path.unlink()
    if not any(temp_img_dir.iterdir()):
        temp_img_dir.rmdir()

    return output_files


def main():
    parser = argparse.ArgumentParser(
        description="批量 PDF 转 Markdown 工具 - 使用 PaddleOCR PP-StructureV3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python pdf_to_md.py                              # 处理 data/raw/pdf/ 下所有 PDF
  python pdf_to_md.py -p 5                         # 每组 5 页
  python pdf_to_md.py -i ./my_pdf/ -o ./output/    # 自定义路径
  python pdf_to_md.py file1.pdf file2.pdf          # 指定文件
        """)
    parser.add_argument("-i", "--input-dir", type=str,
                        default=str(DEFAULT_PDF_DIR),
                        help=f"PDF 输入目录 (默认: {DEFAULT_PDF_DIR})")
    parser.add_argument("-o", "--output-dir", type=str,
                        default=str(DEFAULT_OUTPUT_DIR),
                        help=f"Markdown 输出目录 (默认: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("-p", "--pages-per-chunk", type=int, default=7,
                        help="每组处理的页数 (默认: 7)")
    parser.add_argument("--dpi", type=int, default=200,
                        help="渲染 DPI，越高越清晰但越慢 (默认: 200)")
    parser.add_argument("files", nargs="*", help="指定要处理的 PDF 文件（可选）")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.files:
        pdf_files = [Path(f) for f in args.files]
    elif input_dir.is_dir():
        pdf_files = sorted(input_dir.glob("*.pdf"))
    else:
        print(f"错误: 目录不存在 - {input_dir}")
        sys.exit(1)

    if not pdf_files:
        print("未找到任何 PDF 文件")
        sys.exit(1)

    print(f"找到 {len(pdf_files)} 个 PDF 文件")
    print(f"输出目录: {output_dir}")

    all_outputs = []
    for pdf_path in pdf_files:
        try:
            out_files = process_pdf(
                pdf_path, output_dir,
                pages_per_chunk=args.pages_per_chunk,
                dpi=args.dpi
            )
            all_outputs.extend(out_files)
        except Exception as e:
            print(f"  [错误] 处理失败 {pdf_path.name}: {e}")

    print(f"\n{'='*60}")
    print(f"全部完成! 共生成 {len(all_outputs)} 个 Markdown 文件")
    print(f"输出目录: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
