import re
import sys
from pathlib import Path
from io import StringIO

try:
    import pandas as pd
except ImportError:
    print("错误: 需要安装 pandas 库")
    print("请运行: pip install pandas tabulate")
    sys.exit(1)


def html_to_markdown_table(table_html: str) -> str:
    """将 HTML 表格转换为 Markdown 表格"""
    try:
        # header=0 表示第一行作为表头
        df = pd.read_html(StringIO(table_html), header=0)[0]
        # 清理空值显示
        df = df.fillna('')
        return df.to_markdown(index=False)
    except Exception as e:
        print(f"警告: 转换表格失败 - {e}")
        return table_html


def clean_markdown(text: str) -> str:
    """清理和规范化 Markdown 文本"""
    # 1. 先提取 <html><body> 中的内容（包含表格），保留内容
    text = re.sub(r"<html><body>(.*?)</body></html>", r"\1", text, flags=re.S)

    # 2. 提取表格并转换为 markdown
    tables = re.findall(r"<table.*?>.*?</table>", text, flags=re.S)
    for table_html in tables:
        md_table = html_to_markdown_table(table_html)
        text = text.replace(table_html, md_table)

    # 3. 清理 <div> 等标签，保留内容
    text = re.sub(r'<div[^>]*>\s*</div>', r"", text, flags=re.S)
    text = re.sub(r'<div[^>]*>(.*?)</div>', r"\1", text, flags=re.S)

    # 4. 标题规范化 - 把（一）、（二）等转为 ## 标题
    text = re.sub(r"\n（([一二三四五六七八九十]+)）", r"\n## （\1）", text)

    # 5. 规范化主项名称、子项名称等
    text = re.sub(r"^主项名称：", r"\n**主项名称：**", text, flags=re.M)
    text = re.sub(r"^子项名称：", r"\n**子项名称：**", text, flags=re.M)

    # 6. 清理多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 7. 清理行首空格
    text = re.sub(r"^ +", "", text, flags=re.M)

    return text.strip()


def main():
    input_file = "pp_structure_v3_demo.md"
    output_file = "pp_structure_v3_demo_clean.md"

    # 支持命令行参数
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]

    input_path = Path(input_file)
    if not input_path.exists():
        print(f"错误: 文件不存在 - {input_file}")
        sys.exit(1)

    print(f"读取文件: {input_file}")
    with open(input_file, "r", encoding="utf-8") as f:
        text = f.read()

    print("正在转换...")
    cleaned_text = clean_markdown(text)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

    print(f"清洗完成! 输出文件: {output_file}")


if __name__ == "__main__":
    main()