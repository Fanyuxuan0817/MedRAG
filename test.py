import re
from pathlib import Path
from paddleocr import PPStructureV3

# ==================================
# 1. 初始化OCR
# ==================================
pipeline = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False
)

# ==================================
# 2. 图片OCR识别
# ==================================
def ocr_image_to_text(image_path, save_dir):
    output = pipeline.predict(input=str(image_path))

    texts = []

    for res in output:
        res.print()
        res.save_to_json(save_path=save_dir)
        res.save_to_markdown(save_path=save_dir)

        md_file = Path(save_dir) / f"{Path(image_path).stem}.md"

        if md_file.exists():
            txt = md_file.read_text(encoding="utf-8").strip()
            if txt:
                texts.append(txt)

    return "\n\n".join(texts).strip()


# ==================================
# 3. 全部引用格式
# ==================================
def quote_all_text(text):
    """
    每一行都加 > 实现整段引用
    """
    lines = text.splitlines()
    result = []

    for line in lines:
        if line.strip():
            result.append("> " + line)
        else:
            result.append(">")

    return "\n".join(result)


# ==================================
# 4. markdown图片递归识别
# ==================================
def process_markdown_images(md_path):
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

        # 去重
        if img_abs in processed:
            ocr_text = processed[img_abs]
        else:
            print("识别图片：", img_abs)
            ocr_text = ocr_image_to_text(img_abs, base_dir)
            processed[img_abs] = ocr_text

        if not ocr_text.strip():
            continue

        # ===== 全部引用 =====
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
    print("处理完成：", md_path)


# ==================================
# 5. 主流程
# ==================================
if __name__ == "__main__":

    # 第一步：生成主markdown
    output = pipeline.predict(input="./test.png")

    for res in output:
        res.print()
        res.save_to_json(save_path="./")
        res.save_to_markdown(save_path="./")

    # 第二步：递归识别markdown中的图片
    process_markdown_images("./test.md")