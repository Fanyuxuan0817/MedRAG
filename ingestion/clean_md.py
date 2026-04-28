import re
import sys
import argparse
from pathlib import Path
from io import StringIO

try:
    import pandas as pd
except ImportError:
    pd = None


def html_to_markdown_table(table_html: str) -> str:
    if pd is None:
        return table_html
    try:
        df = pd.read_html(StringIO(table_html), header=0)[0]
        df = df.fillna('')
        return df.to_markdown(index=False)
    except Exception:
        return table_html


def clean_markdown(text: str,
                   convert_tables: bool = True,
                   strip_html: bool = True,
                   normalize_blanks: bool = True,
                   bold_labels: bool = False,
                   label_patterns: list[str] | None = None,
                   chinese_headers: bool = False) -> str:
    text = text.strip()

    if strip_html:
        text = re.sub(r"<html><body>(.*?)</body></html>", r"\1", text, flags=re.S)

        if convert_tables:
            tables = re.findall(r"<table.*?>.*?</table>", text, flags=re.S)
            for table_html in tables:
                md_table = html_to_markdown_table(table_html)
                text = text.replace(table_html, md_table)

        text = re.sub(r'<div[^>]*>\s*</div>', "", text, flags=re.S)
        text = re.sub(r'<div[^>]*>(.*?)</div>', r"\1", text, flags=re.S)
        text = re.sub(r'<span[^>]*>(.*?)</span>', r"\1", text, flags=re.S)
        text = re.sub(r'<p[^>]*>(.*?)</p>', r"\1", text, flags=re.S)
        text = re.sub(r'<br\s*/?>', "\n", text, flags=re.I)
        text = re.sub(r'<strong[^>]*>(.*?)</strong>', r"**\1**", text, flags=re.I)
        text = re.sub(r'<b[^>]*>(.*?)</b>', r"**\1**", text, flags=re.I)
        text = re.sub(r'<em[^>]*>(.*?)</em>', r"*\1*", text, flags=re.I)
        text = re.sub(r'<i[^>]*>(.*?)</i>', r"*\1*", text, flags=re.I)
        text = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>(.*?)</h\1>',
                      lambda m: "#" * int(m.group(1)) + " " + m.group(2),
                      text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", "", text)

    if chinese_headers:
        text = re.sub(r"\n（([一二三四五六七八九十]+)）", r"\n## （\1）", text)

    if bold_labels and label_patterns:
        for pattern in label_patterns:
            text = re.sub(f"^({pattern})", r"**\1**", text, flags=re.M)

    if normalize_blanks:
        text = re.sub(r"[ \t]+$", "", text, flags=re.M)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"^ +", "", text, flags=re.M)

    return text.strip()


def main():
    BASE_DIR = Path(__file__).resolve().parent.parent
    DEFAULT_INPUT_DIR = BASE_DIR / "output" / "raw_md"
    DEFAULT_OUTPUT_DIR = BASE_DIR / "output" / "clean_md"

    parser = argparse.ArgumentParser(
        description="通用 Markdown 清理工具 - 清理 HTML 标签、转换表格、规范化格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python clean_md.py                                  # 清理 output/raw_md/ 下所有 md -> output/clean_md/
  python clean_md.py -i ./raw_md/ -o ./clean_md/      # 自定义路径
  python clean_md.py file.md -o out.md                # 单文件处理
  python clean_md.py --bold-labels                    # 自动加粗常见标签字段
  python clean_md.py --chinese-headers                # 规范化中文数字标题
  python clean_md.py --no-tables                      # 不转换 HTML 表格
        """)
    parser.add_argument("-i", "--input-dir", type=str,
                        default=str(DEFAULT_INPUT_DIR),
                        help=f"输入目录 (默认: {DEFAULT_INPUT_DIR})")
    parser.add_argument("-o", "--output-dir", type=str,
                        default=str(DEFAULT_OUTPUT_DIR),
                        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--suffix", default="", help="输出文件后缀 (默认无)")
    parser.add_argument("--no-tables", action="store_true", help="不转换 HTML 表格")
    parser.add_argument("--no-strip-html", action="store_true", help="保留 HTML 标签")
    parser.add_argument("--bold-labels", action="store_true", help="自动加粗常见标签字段")
    parser.add_argument("--labels", nargs="*", metavar="LABEL",
                        help="自定义需要加粗的标签模式")
    parser.add_argument("--chinese-headers", action="store_true",
                        help="将（一）（二）等转为 ## 标题")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="递归处理子目录")
    parser.add_argument("files", nargs="*",
                        help="指定要处理的文件（可选，默认处理整个目录）")
    args = parser.parse_args()

    DEFAULT_LABELS = [
        "主项名称：", "子项名称：", "事项名称：", "事项描述：",
        "办理条件：", "办理材料：", "办理流程：", "办理时限：",
        "办理地点：", "咨询电话：", "监督电话："
    ]

    label_patterns = args.labels if args.labels else (
        DEFAULT_LABELS if args.bold_labels else None
    )

    def process_file(input_path: Path, output_dir: Path) -> Path | None:
        if not input_path.exists():
            print(f"  [跳过] 文件不存在: {input_path}")
            return None

        try:
            with open(input_path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(input_path, "r", encoding="gbk") as f:
                text = f.read()

        cleaned = clean_markdown(
            text,
            convert_tables=not args.no_tables,
            strip_html=not args.no_strip_html,
            bold_labels=bool(label_patterns),
            label_patterns=label_patterns,
            chinese_headers=args.chinese_headers
        )

        rel_path = input_path.relative_to(Path(args.input_dir))
        if args.suffix:
            stem = input_path.stem + args.suffix
            out_path = output_dir / rel_path.parent / f"{stem}{input_path.suffix}"
        else:
            out_path = output_dir / rel_path

        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(cleaned)

        print(f"  [完成] {rel_path}")
        return out_path

    inputs = []
    if args.files:
        for f in args.files:
            p = Path(f)
            if p.suffix.lower() == ".md":
                inputs.append(p)
    else:
        input_dir = Path(args.input_dir)
        pattern = "**/*.md" if args.recursive else "*.md"
        inputs.extend(sorted(input_dir.glob(pattern)))

    if not inputs:
        print("错误: 没有找到可处理的 .md 文件")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"共发现 {len(inputs)} 个 Markdown 文件")
    print(f"输入目录: {args.input_dir}")
    print(f"输出目录: {args.output_dir}")
    print("开始清理...\n")

    count = 0
    for inp in inputs:
        if process_file(inp, output_dir):
            count += 1

    print(f"\n处理完成! 共处理 {count}/{len(inputs)} 个文件 -> {output_dir}")


if __name__ == "__main__":
    main()
