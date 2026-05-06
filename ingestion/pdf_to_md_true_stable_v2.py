import os
import sys
import re
import json
import argparse
from pathlib import Path

# ==================================================
# 依赖检查
# ==================================================
try:
    import fitz
except ImportError:
    print("请安装 pymupdf")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("请安装 pillow")
    sys.exit(1)

try:
    from paddleocr import PPStructureV3
except ImportError:
    print("请安装 paddleocr paddlepaddle")
    sys.exit(1)

# ==================================================
# 路径配置
# ==================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PDF_DIR = BASE_DIR / "data" / "raw" / "pdf"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output" / "raw_md"

# ==================================================
# OCR 初始化（全局仅一次）
# ==================================================
pipeline = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False
)

# ==================================================
# 工具函数
# ==================================================
def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def quote_all_text(text):
    lines = text.splitlines()
    result = []
    for line in lines:
        if line.strip():
            result.append("> " + line)
        else:
            result.append(">")
    return "\n".join(result)


# ==================================================
# PDF -> PNG
# ==================================================
def pdf_to_images(pdf_path: Path, out_dir: Path, dpi=200):
    ensure_dir(out_dir)
    doc = fitz.open(str(pdf_path))
    img_paths = []
    for i in range(len(doc)):
        page = doc[i]
        scale = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img_path = out_dir / f"{pdf_path.stem}_p{i+1:03d}.png"
        pix.save(str(img_path))
        img_paths.append(img_path)
    doc.close()
    return img_paths


# ==================================================
# 单图 OCR 文本提取
# ==================================================
def ocr_image_to_text(image_path: Path, save_dir: Path):
    ensure_dir(save_dir)
    output = pipeline.predict(input=str(image_path))
    texts = []
    for res in output:
        res.print()
        res.save_to_json(save_path=str(save_dir))
        res.save_to_markdown(save_path=str(save_dir))
        md_file = save_dir / f"{image_path.stem}.md"
        if md_file.exists():
            txt = md_file.read_text(encoding="utf-8").strip()
            if txt:
                texts.append(txt)
    return "\n\n".join(texts).strip()


# ==================================================
# 图片分块导出（核心修复）
# ==================================================
def export_image_blocks(json_path: Path, page_img: Path, save_dir: Path):
    ensure_dir(save_dir)
    if not json_path.exists():
        print("      警告: JSON文件不存在", json_path.name)
        return
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    blocks = None
    if isinstance(data, dict):
        if "parsing_res_list" in data:
            blocks = data["parsing_res_list"]
        elif "res" in data and isinstance(data["res"], dict):
            blocks = data["res"].get("parsing_res_list")
    if blocks is None:
        print("      警告: 无法获取图片块数据")
        return
    img = Image.open(page_img)
    count = 0
    for block in blocks:
        if block.get("block_label") != "image":
            continue
        bbox = block.get("block_bbox", None)
        if not bbox:
            continue
        x1, y1, x2, y2 = map(int, bbox)
        crop = img.crop((x1, y1, x2, y2))
        out_name = f"img_in_image_box_{x1}_{y1}_{x2}_{y2}.jpg"
        out_path = save_dir / out_name
        crop.save(out_path, quality=95)
        count += 1
    if count:
        print("      导出图片块:", count, "张")


# ==================================================
# Markdown 内嵌图片递归 OCR
# ==================================================
def process_markdown_images(md_path: Path):
    if not md_path.exists():
        return
    md_path = Path(md_path).resolve()
    base_dir = md_path.parent
    content = md_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'(<div[^>]*>.*?<img[^>]*src=["\'](.*?)["\'][^>]*>.*?</div>)',
        re.S | re.I
    )
    matches = list(pattern.finditer(content))
    processed = {}
    offset = 0
    for match in matches:
        img_rel = match.group(2)
        img_abs = (base_dir / img_rel).resolve()
        if not img_abs.exists():
            continue
        if img_abs in processed:
            ocr_text = processed[img_abs]
        else:
            print("      识别图片:", img_abs.name)
            ocr_text = ocr_image_to_text(img_abs, base_dir)
            processed[img_abs] = ocr_text
        if not ocr_text.strip():
            continue
        quoted_text = quote_all_text(ocr_text)
        insert_text = f"""

> 📌 图片内容识别：
>
{quoted_text}

"""
        insert_pos = match.end() + offset
        content = (
            content[:insert_pos]
            + insert_text
            + content[insert_pos:]
        )
        offset += len(insert_text)
    md_path.write_text(content, encoding="utf-8")
    print("      处理完成:", md_path.name)


# ==================================================
# 单页处理
# ==================================================
def process_page(img_path: Path, page_dir: Path):
    ensure_dir(page_dir)
    print("   页面:", img_path.name)
    output = pipeline.predict(input=str(img_path))
    for res in output:
        res.print()
        res.save_to_json(save_path=str(page_dir))
        res.save_to_markdown(save_path=str(page_dir))
    json_path = page_dir / f"{img_path.stem}_res.json"
    if not json_path.exists():
        for candidate in page_dir.rglob(f"{img_path.stem}*.json"):
            json_path = candidate
            break
    md_path = page_dir / f"{img_path.stem}.md"
    if not md_path.exists():
        for candidate in page_dir.rglob(f"{img_path.stem}.md"):
            md_path = candidate
            break
    imgs_dir = md_path.parent / "imgs"
    ensure_dir(imgs_dir)
    export_image_blocks(json_path, img_path, imgs_dir)
    if md_path.exists():
        process_markdown_images(md_path)
    return md_path


# ==================================================
# 合并 Markdown
# ==================================================
def merge_markdowns(md_files, out_md):
    ensure_dir(out_md.parent)
    parts = []
    for md in md_files:
        if md.exists():
            txt = md.read_text(encoding="utf-8").strip()
            if txt:
                parts.append(txt)
    out_md.write_text("\n\n".join(parts), encoding="utf-8")


# ==================================================
# 单 PDF 处理
# ==================================================
def process_pdf(pdf_path: Path, output_dir: Path, pages_per_chunk=7, dpi=200):
    pdf_name = pdf_path.stem
    pdf_dir = output_dir / pdf_name
    ensure_dir(pdf_dir)
    page_img_dir = pdf_dir / "_pages"
    ensure_dir(page_img_dir)
    print("\n" + "=" * 60)
    print("处理 PDF:", pdf_path.name)
    print("=" * 60)
    img_paths = pdf_to_images(pdf_path, page_img_dir, dpi=dpi)
    total_pages = len(img_paths)
    total_chunks = (total_pages + pages_per_chunk - 1) // pages_per_chunk
    print("总页数:", total_pages)
    outputs = []
    for chunk_idx in range(total_chunks):
        start = chunk_idx * pages_per_chunk
        end = min(start + pages_per_chunk, total_pages)
        print(f"\n[{chunk_idx+1}/{total_chunks}] 第{start+1}-{end}页")
        chunk_imgs = img_paths[start:end]
        md_files = []
        for img_path in chunk_imgs:
            page_dir = pdf_dir / img_path.stem
            md_file = process_page(img_path, page_dir)
            md_files.append(md_file)
        out_md = pdf_dir / f"{pdf_name}_part{chunk_idx+1:02d}.md"
        merge_markdowns(md_files, out_md)
        outputs.append(out_md)
        print("输出:", out_md.name)
    return outputs


# ==================================================
# 主程序
# ==================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--input-dir",
        default=str(DEFAULT_PDF_DIR)
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR)
    )
    parser.add_argument(
        "-p", "--pages-per-chunk",
        type=int,
        default=7
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200
    )
    parser.add_argument(
        "files",
        nargs="*"
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        print("输入目录不存在:", input_dir)
        sys.exit(1)

    ensure_dir(output_dir)

    if args.files:
        pdf_files = [Path(f) for f in args.files]
    else:
        pdf_files = sorted(input_dir.glob("*.pdf"))

    if not pdf_files:
        print("未找到PDF")
        return

    all_outputs = []
    for pdf in pdf_files:
        try:
            outs = process_pdf(
                pdf_path=pdf,
                output_dir=output_dir,
                pages_per_chunk=args.pages_per_chunk,
                dpi=args.dpi
            )
            all_outputs.extend(outs)
        except Exception as e:
            print("失败:", pdf.name, e)

    print("\n全部完成")
    print("生成文件数:", len(all_outputs))
    print("输出目录:", output_dir)


if __name__ == "__main__":
    main()
