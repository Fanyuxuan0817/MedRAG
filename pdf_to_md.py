import os
import fitz  # PyMuPDF
from paddleocr import PPStructureV3

# ========= 配置 =========
pdf_path = r"test.pdf"
page_num = 5   # 第5页（人类页码）
output_dir = "output"
os.makedirs(output_dir, exist_ok=True)

# ========= 第一步：PDF第5页转图片 =========
doc = fitz.open(pdf_path)

# Python索引从0开始，所以第5页 = index 4
page = doc[page_num - 1]

# 高清渲染
pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))

img_path = os.path.join(output_dir, "page5.png")
pix.save(img_path)

doc.close()

print("PDF第5页已转图片:", img_path)

# ========= 第二步：OCR解析成Markdown =========
pipeline = PPStructureV3()

result = pipeline.predict(input=img_path)

for res in result:
    res.save_to_markdown(save_path=output_dir)
    res.save_to_json(save_path=output_dir)

print("第5页已输出 Markdown")