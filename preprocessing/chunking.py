"""
粗颗粒度切分模块 - 章节级PDF处理
根据MedRAG数据处理方案实现
"""

import os
import json
import re
import base64
import requests
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import pdfplumber
from PyPDF2 import PdfReader


@dataclass
class OutlineItem:
    """大纲条目"""
    title: str
    page: Optional[int]
    level: int


@dataclass
class Chapter:
    """章节结构"""
    chapter_id: str
    title: str
    start_page: Optional[int]
    sections: List[Dict[str, Any]]


@dataclass
class CoarseChunk:
    """粗颗粒块"""
    chunk_id: str
    content: str
    metadata: Dict[str, Any]


class BaiduOCR:
    """百度OCR客户端"""
    
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.access_token = None
        self._get_access_token()
    
    def _get_access_token(self):
        """获取百度OCR访问令牌"""
        url = f"https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key
        }
        response = requests.post(url, params=params, timeout=30)
        if response.status_code == 200:
            result = response.json()
            self.access_token = result.get("access_token")
            print(f"[BaiduOCR] Access token获取成功")
        else:
            raise Exception(f"获取access_token失败: {response.text}")
    
    def recognize(self, image_path: str) -> str:
        """
        识别图片中的文字
        支持通用文字识别（高精度版）
        """
        if not self.access_token:
            self._get_access_token()
        
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={self.access_token}"
        
        # 读取图片并转为base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = {'image': image_data}
        
        response = requests.post(url, data=data, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if 'words_result' in result:
                words = [item['words'] for item in result['words_result']]
                return '\n'.join(words)
            else:
                print(f"[BaiduOCR] 识别结果为空: {result}")
                return ""
        else:
            print(f"[BaiduOCR] 请求失败: {response.status_code}, {response.text}")
            return ""


class PDFStructureExtractor:
    """PDF结构提取器：梳理手册层级结构"""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.outlines: List[OutlineItem] = []
        self.chapters: List[Chapter] = []
        
    def extract_outline(self) -> List[OutlineItem]:
        """提取PDF大纲/书签结构"""
        try:
            reader = PdfReader(self.pdf_path)
            outlines = reader.outline if hasattr(reader, 'outline') else []
            
            def parse_outline(outline_list, level=0):
                """递归解析大纲层级"""
                result = []
                for item in outline_list:
                    if isinstance(item, list):
                        result.extend(parse_outline(item, level + 1))
                    else:
                        # 获取页码
                        page_num = None
                        if hasattr(item, 'page'):
                            if hasattr(item.page, 'id'):
                                page_num = item.page.id
                            else:
                                page_num = item.page
                        
                        title = item.title if hasattr(item, 'title') else str(item)
                        result.append(OutlineItem(
                            title=title,
                            page=page_num,
                            level=level
                        ))
                return result
            
            self.outlines = parse_outline(outlines)
            print(f"[PDFStructureExtractor] 提取到 {len(self.outlines)} 个大纲条目")
            return self.outlines
        except Exception as e:
            print(f"[PDFStructureExtractor] 提取大纲失败: {e}")
            # 如果提取失败，返回空列表
            self.outlines = []
            return self.outlines
    
    def build_chapter_index(self) -> List[Chapter]:
        """构建章节索引，为粗颗粒块打标签"""
        chapters = []
        current_chapter = None
        
        # 如果没有大纲，尝试从内容中提取章节
        if not self.outlines:
            print("[PDFStructureExtractor] 无大纲，将尝试从内容识别章节")
            return self._build_chapters_from_content()
        
        for outline in self.outlines:
            if outline.level == 0:  # 一级标题 = 章
                current_chapter = Chapter(
                    chapter_id=f"第{len(chapters)+1}章",
                    title=outline.title,
                    start_page=outline.page,
                    sections=[]
                )
                chapters.append(current_chapter)
            elif outline.level == 1 and current_chapter:  # 二级标题 = 节
                section = {
                    'section_id': f"{current_chapter.chapter_id}-{outline.title[:10]}",
                    'title': outline.title,
                    'page': outline.page
                }
                current_chapter.sections.append(section)
        
        self.chapters = chapters
        print(f"[PDFStructureExtractor] 构建完成，共 {len(chapters)} 个章节")
        return chapters
    
    def _build_chapters_from_content(self) -> List[Chapter]:
        """从内容中提取章节（备用方案）"""
        chapters = []
        
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                current_chapter = None
                chapter_pattern = re.compile(r'^(第[一二三四五六七八九十\d]+章|第\d+章|Chapter\s+\d+)', re.IGNORECASE)
                
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    lines = text.split('\n')
                    
                    for line in lines[:10]:  # 只检查每页前10行
                        match = chapter_pattern.match(line.strip())
                        if match:
                            if current_chapter:
                                chapters.append(current_chapter)
                            
                            current_chapter = Chapter(
                                chapter_id=f"第{len(chapters)+1}章",
                                title=line.strip(),
                                start_page=page_num,
                                sections=[]
                            )
                            break
                
                if current_chapter:
                    chapters.append(current_chapter)
        except Exception as e:
            print(f"[PDFStructureExtractor] 从内容提取章节失败: {e}")
        
        # 如果还是没找到章节，就按页划分
        if not chapters:
            try:
                with pdfplumber.open(self.pdf_path) as pdf:
                    total_pages = len(pdf.pages)
                    chunk_size = max(1, total_pages // 5)  # 分成约5个部分
                    
                    for i in range(0, total_pages, chunk_size):
                        chapters.append(Chapter(
                            chapter_id=f"第{(i//chunk_size)+1}章",
                            title=f"文档部分{(i//chunk_size)+1}",
                            start_page=i,
                            sections=[]
                        ))
            except Exception as e:
                print(f"[PDFStructureExtractor] 按页划分失败: {e}")
        
        self.chapters = chapters
        print(f"[PDFStructureExtractor] 从内容提取到 {len(chapters)} 个章节")
        return chapters


class ImageProcessor:
    """图片处理器：生成文本描述，实现可检索"""
    
    def __init__(self, ocr_client: Optional[BaiduOCR] = None):
        self.ocr_client = ocr_client
        
    def extract_images_from_page(self, page, page_num: int, output_dir: str) -> List[Dict[str, Any]]:
        """从PDF页面提取图片"""
        images = []
        
        try:
            # pdfplumber获取图片信息
            if hasattr(page, 'images') and page.images:
                for img_idx, img in enumerate(page.images):
                    # 提取图片区域
                    try:
                        cropped = page.within_bbox((img['x0'], img['top'], img['x1'], img['bottom']))
                        im = cropped.to_image()
                        
                        # 保存图片
                        img_filename = f"page_{page_num+1}_img_{img_idx+1}.png"
                        img_path = os.path.join(output_dir, img_filename)
                        im.save(img_path)
                        
                        images.append({
                            'path': img_path,
                            'page': page_num + 1,
                            'bbox': (img['x0'], img['top'], img['x1'], img['bottom'])
                        })
                    except Exception as e:
                        print(f"[ImageProcessor] 提取图片失败 page_{page_num+1}_img_{img_idx+1}: {e}")
        except Exception as e:
            print(f"[ImageProcessor] 处理页面图片失败 page {page_num+1}: {e}")
        
        return images
    
    def process_image(self, image_info: Dict[str, Any], surrounding_text: str = "") -> Dict[str, Any]:
        """
        处理图片，生成文本描述
        """
        ocr_text = ""
        
        # 使用OCR提取图片内文字
        if self.ocr_client and os.path.exists(image_info['path']):
            try:
                ocr_text = self.ocr_client.recognize(image_info['path'])
                print(f"[ImageProcessor] OCR识别完成: {image_info['path'][:50]}...")
            except Exception as e:
                print(f"[ImageProcessor] OCR识别失败: {e}")
        
        # 构建可检索的文本块
        searchable_text = f"""
[图表区域]
图片内文字：{ocr_text if ocr_text else "（无文字）"}
关联上下文：{surrounding_text if surrounding_text else "（无上下文）"}
"""
        
        return {
            'type': 'image_chunk',
            'original_image': image_info['path'],
            'searchable_text': searchable_text.strip(),
            'ocr_text': ocr_text,
            'metadata': {
                'has_image': True,
                'page': image_info.get('page'),
                'ocr_text_length': len(ocr_text) if ocr_text else 0
            }
        }


def semantic_split(text: str, max_tokens: int = 2000) -> List[str]:
    """
    语义切分：按语义边界切分文本
    简单实现：按段落分割，然后合并到接近max_tokens
    """
    if not text:
        return []
    
    # 按段落分割
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    
    chunks = []
    current_chunk = []
    current_length = 0
    
    # 估算：中文约1token/字，英文约1token/单词
    def estimate_tokens(t: str) -> int:
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', t))
        english_words = len(re.findall(r'[a-zA-Z]+', t))
        return chinese_chars + english_words
    
    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        
        # 如果当前段落本身超过限制，需要进一步分割
        if para_tokens > max_tokens:
            # 先保存当前累积的内容
            if current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = []
                current_length = 0
            
            # 按句子分割长段落
            sentences = re.split(r'([。！？.!?])', para)
            sentences = [''.join(sentences[i:i+2]) for i in range(0, len(sentences), 2)]
            
            temp_chunk = []
            temp_length = 0
            for sent in sentences:
                sent_tokens = estimate_tokens(sent)
                if temp_length + sent_tokens <= max_tokens:
                    temp_chunk.append(sent)
                    temp_length += sent_tokens
                else:
                    if temp_chunk:
                        chunks.append(''.join(temp_chunk))
                    temp_chunk = [sent]
                    temp_length = sent_tokens
            
            if temp_chunk:
                chunks.append(''.join(temp_chunk))
        else:
            # 正常段落，尝试合并
            if current_length + para_tokens <= max_tokens:
                current_chunk.append(para)
                current_length += para_tokens
            else:
                # 保存当前块，开始新块
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_length = para_tokens
    
    # 保存最后的内容
    if current_chunk:
        chunks.append('\n\n'.join(current_chunk))
    
    return chunks if chunks else [text]


def coarse_chunk_by_chapters(
    pdf_path: str, 
    structure_extractor: PDFStructureExtractor,
    image_processor: Optional[ImageProcessor] = None,
    temp_image_dir: Optional[str] = None
) -> List[CoarseChunk]:
    """
    按章节进行粗颗粒切分
    
    Args:
        pdf_path: PDF文件路径
        structure_extractor: PDF结构提取器
        image_processor: 图片处理器（可选）
        temp_image_dir: 临时图片保存目录
    """
    chunks = []
    
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        
        for i, chapter in enumerate(structure_extractor.chapters):
            start_page = chapter.start_page or 0
            # 下一章起始页作为本章结束（最后一章到文档末尾）
            if i + 1 < len(structure_extractor.chapters):
                end_page = structure_extractor.chapters[i + 1].start_page or total_pages
            else:
                end_page = total_pages
            
            # 确保页码在有效范围内
            start_page = max(0, min(start_page, total_pages - 1))
            end_page = max(start_page + 1, min(end_page, total_pages))
            
            print(f"[CoarseChunk] 处理 {chapter.chapter_id}: {chapter.title} (页 {start_page+1}-{end_page})")
            
            chapter_text = ""
            chapter_images = []
            
            for page_num in range(start_page, end_page):
                try:
                    page = pdf.pages[page_num]
                    page_text = page.extract_text() or ""
                    chapter_text += page_text + "\n"
                    
                    # 提取图片（如果提供了image_processor）
                    if image_processor and temp_image_dir:
                        try:
                            page_images = image_processor.extract_images_from_page(
                                page, page_num, temp_image_dir
                            )
                            chapter_images.extend(page_images)
                        except Exception as e:
                            print(f"[CoarseChunk] 提取图片失败 page {page_num+1}: {e}")
                except Exception as e:
                    print(f"[CoarseChunk] 处理页面失败 page {page_num+1}: {e}")
            
            # 粗颗粒切分：按固定token数或语义边界切分
            sub_chunks = semantic_split(chapter_text, max_tokens=2000)
            
            for idx, sub_chunk in enumerate(sub_chunks):
                # 构建chunk_id: 章节ID-主题关键词-粗块序号
                safe_title = re.sub(r'[^\w\u4e00-\u9fff]', '_', chapter.title[:6])
                chunk_id = f"{chapter.chapter_id}-{safe_title}-粗块{idx+1}"
                
                chunk = CoarseChunk(
                    chunk_id=chunk_id,
                    content=sub_chunk,
                    metadata={
                        'chapter': chapter.title,
                        'chapter_id': chapter.chapter_id,
                        'page_range': [start_page + 1, end_page],
                        'level': 'coarse',
                        'sub_chunk_index': idx + 1,
                        'total_sub_chunks': len(sub_chunks),
                        'has_images': len(chapter_images) > 0,
                        'image_count': len(chapter_images)
                    }
                )
                chunks.append(chunk)
            
            # 处理图片块
            if image_processor and chapter_images:
                for img_idx, img_info in enumerate(chapter_images):
                    try:
                        # 找到图片附近的文本作为上下文
                        surrounding = chapter_text[:500] if chapter_text else ""
                        image_chunk_data = image_processor.process_image(img_info, surrounding)
                        
                        img_chunk_id = f"{chapter.chapter_id}-{safe_title}-图片{img_idx+1}"
                        img_chunk = CoarseChunk(
                            chunk_id=img_chunk_id,
                            content=image_chunk_data['searchable_text'],
                            metadata={
                                'chapter': chapter.title,
                                'chapter_id': chapter.chapter_id,
                                'page_range': [img_info.get('page', start_page + 1), img_info.get('page', start_page + 1)],
                                'level': 'coarse',
                                'type': 'image',
                                'original_image': image_chunk_data['original_image'],
                                'ocr_text': image_chunk_data['ocr_text']
                            }
                        )
                        chunks.append(img_chunk)
                    except Exception as e:
                        print(f"[CoarseChunk] 处理图片块失败: {e}")
    
    return chunks


class BatchPDFProcessor:
    """批量PDF处理器"""
    
    def __init__(
        self, 
        input_dir: str, 
        output_dir: str,
        ocr_client: Optional[BaiduOCR] = None
    ):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.ocr_client = ocr_client
        self.processed_count = 0
        self.temp_image_dir = os.path.join(output_dir, 'temp_images')
        
        # 创建临时图片目录
        os.makedirs(self.temp_image_dir, exist_ok=True)
    
    def preprocess_pipeline(self, pdf_path: str) -> List[CoarseChunk]:
        """单文档预处理流水线"""
        print(f"\n{'='*60}")
        print(f"[BatchProcessor] 开始处理: {os.path.basename(pdf_path)}")
        print(f"{'='*60}")
        
        # Step 1: 结构提取
        print("[Step 1] 提取PDF结构...")
        extractor = PDFStructureExtractor(pdf_path)
        extractor.extract_outline()
        extractor.build_chapter_index()
        
        # Step 2: 粗颗粒切分
        print("[Step 2] 粗颗粒度切分...")
        image_processor = ImageProcessor(self.ocr_client) if self.ocr_client else None
        
        pdf_temp_dir = os.path.join(self.temp_image_dir, os.path.basename(pdf_path).replace('.pdf', ''))
        os.makedirs(pdf_temp_dir, exist_ok=True)
        
        coarse_chunks = coarse_chunk_by_chapters(
            pdf_path, 
            extractor,
            image_processor=image_processor,
            temp_image_dir=pdf_temp_dir
        )
        
        # Step 3: 添加溯源标签
        print("[Step 3] 添加溯源标签...")
        tagged_chunks = self.add_source_tags(coarse_chunks, pdf_path)
        
        print(f"[BatchProcessor] 处理完成: {len(tagged_chunks)} 个粗颗粒块")
        
        return tagged_chunks
    
    def add_source_tags(self, chunks: List[CoarseChunk], pdf_path: str) -> List[CoarseChunk]:
        """添加来源标签：手册ID + 页码"""
        manual_id = os.path.basename(pdf_path).replace('.pdf', '')
        
        for chunk in chunks:
            page_info = chunk.metadata.get('page_range', ['unknown'])
            chunk.metadata['source'] = {
                'manual_id': manual_id,
                'page_start': page_info[0] if len(page_info) > 0 else 'unknown',
                'page_end': page_info[1] if len(page_info) > 1 else page_info[0] if len(page_info) > 0 else 'unknown',
                'full_path': pdf_path
            }
            # 用户追问"内容来源"时可快速定位
            chunk.metadata['source_citation'] = (
                f"[来源：{manual_id}，第{chunk.metadata['source']['page_start']}-"
                f"{chunk.metadata['source']['page_end']}页]"
            )
        
        return chunks
    
    def batch_process(self, test_mode: bool = False) -> Dict[str, Any]:
        """
        批量处理
        
        Args:
            test_mode: 测试模式，只处理前几个文件
        """
        pdf_files = [
            os.path.join(self.input_dir, f)
            for f in os.listdir(self.input_dir)
            if f.endswith('.pdf')
        ]
        
        if not pdf_files:
            print("[BatchProcessor] 未找到PDF文件")
            return {
                'total_processed': 0,
                'total_chunks': 0,
                'test_mode': test_mode
            }
        
        if test_mode:
            pdf_files = pdf_files[:2]
            print(f"【测试模式】选取前{len(pdf_files)}个PDF进行验证")
        
        all_chunks = []
        results = {
            'processed_files': [],
            'failed_files': []
        }
        
        for pdf_path in pdf_files:
            try:
                chunks = self.preprocess_pipeline(pdf_path)
                all_chunks.extend(chunks)
                self.processed_count += 1
                
                # 保存单个文件的结果
                output_filename = os.path.basename(pdf_path).replace('.pdf', '_coarse.json')
                output_path = os.path.join(self.output_dir, output_filename)
                
                # 转换为字典列表并保存
                chunks_data = [asdict(chunk) for chunk in chunks]
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(chunks_data, f, ensure_ascii=False, indent=2)
                
                print(f"[BatchProcessor] 已保存: {output_path}")
                results['processed_files'].append({
                    'file': pdf_path,
                    'chunks': len(chunks),
                    'output': output_path
                })
                
            except Exception as e:
                print(f"[BatchProcessor] 处理失败 {pdf_path}: {e}")
                import traceback
                traceback.print_exc()
                results['failed_files'].append({
                    'file': pdf_path,
                    'error': str(e)
                })
        
        # 保存汇总结果
        summary = {
            'total_processed': self.processed_count,
            'total_chunks': len(all_chunks),
            'test_mode': test_mode,
            'results': results
        }
        
        summary_path = os.path.join(self.output_dir, 'processing_summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*60}")
        print(f"[BatchProcessor] 批量处理完成")
        print(f"  - 成功处理: {len(results['processed_files'])} 个文件")
        print(f"  - 失败: {len(results['failed_files'])} 个文件")
        print(f"  - 总粗颗粒块: {len(all_chunks)}")
        print(f"  - 汇总文件: {summary_path}")
        print(f"{'='*60}")
        
        return summary


def main():
    """主函数 - 执行粗颗粒度切分"""
    # 配置路径
    input_dir = os.path.join('data', 'raw', 'pdf')
    output_dir = os.path.join('data', 'processed', 'chunks')
    
    # 确保目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 百度OCR配置
    api_key = "b5wOdK0hfr1YYuZWyy5A0nlh"
    secret_key = "ah6i9wlEfD8TfiIMFA40pWawDKoQEZgn"
    
    # 初始化OCR客户端
    ocr_client = None
    try:
        ocr_client = BaiduOCR(api_key, secret_key)
        print("[Main] 百度OCR初始化成功")
    except Exception as e:
        print(f"[Main] 百度OCR初始化失败: {e}")
        print("[Main] 将继续处理，但不进行OCR识别")
    
    # 创建批量处理器
    processor = BatchPDFProcessor(
        input_dir=input_dir,
        output_dir=output_dir,
        ocr_client=ocr_client
    )
    
    # 执行批量处理
    result = processor.batch_process(test_mode=False)
    
    return result


if __name__ == '__main__':
    main()
