# RAG 数据处理技术文档

## 版本：v1.0 | 日期：2026-04-26

***

## 1. 概述

本文档面向百万级技术手册/文档的RAG（检索增强生成）场景，提供从PDF解析、文档切分、图表处理到索引构建的全链路数据处理方案。

***

## 2. 粗颗粒度切分：章节级处理

### 2.1 核心原则

优先处理PDF结构化信息，建立层级结构后再进行粗颗粒切分。

### 2.2 技术实现

**工具链：** PyPDF2 + pdfplumber + 大纲提取

```python
import pdfplumber
from PyPDF2 import PdfReader

class PDFStructureExtractor:
    """PDF结构提取器：梳理手册层级结构"""
    
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.outlines = []  # 文档大纲
        self.chapters = []  # 章节结构
        
    def extract_outline(self):
        """提取PDF大纲/书签结构"""
        reader = PdfReader(self.pdf_path)
        outlines = reader.outline if hasattr(reader, 'outline') else []
        
        def parse_outline(outline_list, level=0):
            """递归解析大纲层级"""
            result = []
            for item in outline_list:
                if isinstance(item, list):
                    result.extend(parse_outline(item, level + 1))
                else:
                    result.append({
                        'title': item.title if hasattr(item, 'title') else str(item),
                        'page': item.page if hasattr(item, 'page') else None,
                        'level': level
                    })
            return result
            
        self.outlines = parse_outline(outlines)
        return self.outlines
    
    def build_chapter_index(self):
        """构建章节索引，为粗颗粒块打标签"""
        chapters = []
        current_chapter = None
        
        for outline in self.outlines:
            if outline['level'] == 0:  # 一级标题 = 章
                current_chapter = {
                    'chapter_id': f"第{len(chapters)+1}章",
                    'title': outline['title'],
                    'start_page': outline['page'],
                    'sections': []
                }
                chapters.append(current_chapter)
            elif outline['level'] == 1 and current_chapter:  # 二级标题 = 节
                section = {
                    'section_id': f"{current_chapter['chapter_id']}-{outline['title'][:10]}",
                    'title': outline['title'],
                    'page': outline['page']
                }
                current_chapter['sections'].append(section)
                
        self.chapters = chapters
        return chapters
```

### 2.3 粗颗粒块标签规范

| 标签字段     | 格式示例           | 说明       |
| :------- | :------------- | :------- |
| 章节ID     | `第3章`          | 一级章节标识   |
| 主题关键词    | `产品参数`         | 章节核心主题   |
| 粗块序号     | `粗块1`          | 同章节内切分序号 |
| **完整标签** | `第3章-产品参数-粗块1` | 唯一标识符    |

### 2.4 切分策略

```python
def coarse_chunk_by_chapters(pdf_path, structure_extractor):
    """按章节进行粗颗粒切分"""
    chunks = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for i, chapter in enumerate(structure_extractor.chapters):
            start_page = chapter['start_page']
            # 下一章起始页作为本章结束（最后一章到文档末尾）
            end_page = structure_extractor.chapters[i+1]['start_page'] if i+1 < len(structure_extractor.chapters) else len(pdf.pages)
            
            chapter_text = ""
            for page_num in range(start_page, end_page):
                page = pdf.pages[page_num]
                chapter_text += page.extract_text() + "\n"
            
            # 粗颗粒切分：按固定token数或语义边界切分
            sub_chunks = semantic_split(chapter_text, max_tokens=2000)
            
            for idx, sub_chunk in enumerate(sub_chunks):
                chunk_id = f"{chapter['chapter_id']}-{chapter['title'][:6]}-粗块{idx+1}"
                chunks.append({
                    'chunk_id': chunk_id,
                    'content': sub_chunk,
                    'metadata': {
                        'chapter': chapter['title'],
                        'page_range': [start_page, end_page],
                        'level': 'coarse'
                    }
                })
    return chunks
```

***

## 3. 细颗粒度切分：语义单元保护

### 3.1 文本类型分类标准

| 类型         | 特征         | 切分策略           |
| :--------- | :--------- | :------------- |
| **正文段落**   | 连续叙述性文本    | 按语义边界切分，保持段落完整 |
| **表格说明**   | 表格标题+表头+数据 | 整体保留，不跨表切分     |
| **公式注释**   | 数学公式+解释文本  | 公式与紧邻说明文本绑定    |
| **图表关联文本** | 图注、表注、数据来源 | 与对应图表整体切分      |

### 3.2 核心原则：保证同一语义单元不拆分

```python
class SemanticChunker:
    """语义切分器：保持语义单元完整性"""
    
    def __init__(self):
        self.text_types = ['paragraph', 'table', 'formula', 'figure_text']
        
    def identify_text_type(self, text_block, page_layout):
        """识别文本块类型"""
        # 基于布局特征判断
        if self.is_table(text_block, page_layout):
            return 'table'
        elif self.is_formula(text_block):
            return 'formula'
        elif self.is_figure_caption(text_block):
            return 'figure_text'
        else:
            return 'paragraph'
    
    def chunk_with_semantic_protection(self, text_blocks, max_tokens=512):
        """
        语义保护切分：
        - 穿插小图标/符号的正文段落 → 归为同一块
        - 独立表格/大图 → 单独切分
        """
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for block in text_blocks:
            block_type = block['type']
            block_tokens = estimate_tokens(block['text'])
            
            # 策略1：独立表格/大图 → 强制单独成块
            if block_type in ['table', 'large_figure']:
                if current_chunk:  # 先保存当前累积块
                    chunks.append(self._create_chunk(current_chunk))
                    current_chunk = []
                    current_tokens = 0
                
                # 表格块：尝试关联前后1-2段上下文
                table_chunk = self._build_table_chunk(block, text_blocks)
                chunks.append(table_chunk)
                continue
            
            # 策略2：正文段落中穿插小元素 → 合并到同一块
            if block_type == 'paragraph' or block_type == 'inline_symbol':
                if current_tokens + block_tokens <= max_tokens * 1.2:  # 允许20%溢出
                    current_chunk.append(block)
                    current_tokens += block_tokens
                else:
                    chunks.append(self._create_chunk(current_chunk))
                    current_chunk = [block]
                    current_tokens = block_tokens
        
        if current_chunk:
            chunks.append(self._create_chunk(current_chunk))
            
        return chunks
    
    def _build_table_chunk(self, table_block, all_blocks, context_range=2):
        """构建表格块：关联前后上下文"""
        table_idx = all_blocks.index(table_block)
        
        # 向前取context_range段
        prev_context = []
        for i in range(max(0, table_idx - context_range), table_idx):
            if all_blocks[i]['type'] == 'paragraph':
                prev_context.append(all_blocks[i])
        
        # 向后取context_range段
        next_context = []
        for i in range(table_idx + 1, min(len(all_blocks), table_idx + 1 + context_range)):
            if all_blocks[i]['type'] == 'paragraph':
                next_context.append(all_blocks[i])
        
        return {
            'type': 'table_chunk',
            'table': table_block,
            'prev_context': prev_context,  # 数据来源、说明
            'next_context': next_context,  # 结论说明
            'metadata': {
                'has_context': len(prev_context) > 0 or len(next_context) > 0
            }
        }
```

***

## 4. 图表处理：关键难点方案

### 4.1 "标题+图片+上下文"整体切割

```
┌─────────────────────────────────────┐
│  [图表标题] 图3-2 产品性能对比曲线    │  ← 标题
├─────────────────────────────────────┤
│                                     │
│      [  图片/图表区域  ]            │  ← 图片
│                                     │
├─────────────────────────────────────┤
│  数据来源：实验室测试，2024年Q1      │  ← 上下文
│  结论：A型号在高温环境下性能更稳定    │
└─────────────────────────────────────┘
           ↓
    整体切分为一个语义块
```

### 4.2 图片文本化处理

```python
from PIL import Image
import base64

class ImageProcessor:
    """图片处理器：生成文本描述，实现可检索"""
    
    def __init__(self, vision_model=None):
        # 可使用多模态模型（如GPT-4V、Qwen-VL）或OCR工具
        self.vision_model = vision_model or default_vision_client()
        
    def process_image(self, image_path, surrounding_text=""):
        """
        处理图片，生成文本描述加入chunk
        """
        # 1. OCR提取图片内文字
        ocr_text = self.extract_ocr(image_path)
        
        # 2. 生成图片描述（多模态模型）
        image_description = self.generate_description(
            image_path, 
            context=surrounding_text
        )
        
        # 3. 构建可检索的文本块
        searchable_text = f"""
        [图表区域]
        图片描述：{image_description}
        图片内文字：{ocr_text}
        关联上下文：{surrounding_text}
        """
        
        return {
            'type': 'image_chunk',
            'original_image': image_path,
            'searchable_text': searchable_text,
            'metadata': {
                'has_image': True,
                'image_description_length': len(image_description)
            }
        }
    
    def extract_ocr(self, image_path):
        """OCR提取图片内文字"""
        # 使用paddleocr / tesseract / 云端OCR API
        # 返回识别到的文字内容
        pass
    
    def generate_description(self, image_path, context=""):
        """使用多模态模型生成图片描述"""
        with open(image_path, "rb") as img:
            base64_image = base64.b64encode(img.read()).decode()
        
        prompt = f"""
        请详细描述这张技术图表的内容。如果包含数据，请提取关键数值。
        上下文信息：{context}
        """
        
        response = self.vision_model.chat.completions.create(
            model="gpt-4-vision-preview",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }]
        )
        return response.choices[0].message.content
```

### 4.3 上下文范围控制

| 图表类型 | 建议上下文范围            | 原因     |
| :--- | :----------------- | :----- |
| 数据表格 | 前1段（来源）+ 后1段（结论）   | 避免冗余   |
| 流程图  | 前1段（背景）+ 后1段（说明）   | 保持精简   |
| 性能曲线 | 前2段（测试条件）+ 后1段（分析） | 条件信息重要 |
| 架构图  | 前1段（概述）+ 后2段（组件说明） | 组件细节多  |

***

## 5. 批量处理与落地验证

### 5.1 批量处理流水线

```python
import os
from concurrent.futures import ProcessPoolExecutor

class BatchPDFProcessor:
    """批量PDF处理器"""
    
    def __init__(self, input_dir, output_dir):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.processed_count = 0
        
    def preprocess_pipeline(self, pdf_path):
        """单文档预处理流水线"""
        # Step 1: 解析与清洗
        raw_text = self.parse_and_clean(pdf_path)
        
        # Step 2: 结构提取
        extractor = PDFStructureExtractor(pdf_path)
        extractor.extract_outline()
        extractor.build_chapter_index()
        
        # Step 3: 粗颗粒切分
        coarse_chunks = coarse_chunk_by_chapters(pdf_path, extractor)
        
        # Step 4: 细颗粒切分（语义保护）
        semantic_chunker = SemanticChunker()
        final_chunks = []
        for chunk in coarse_chunks:
            sub_chunks = semantic_chunker.chunk_with_semantic_protection(
                chunk['content']
            )
            final_chunks.extend(sub_chunks)
        
        # Step 5: 图表处理
        image_processor = ImageProcessor()
        for chunk in final_chunks:
            if chunk['type'] == 'image_chunk':
                chunk = image_processor.process_image(chunk['image_path'])
        
        # Step 6: 添加溯源标签
        tagged_chunks = self.add_source_tags(final_chunks, pdf_path)
        
        return tagged_chunks
    
    def parse_and_clean(self, pdf_path):
        """解析并清洗：去除空白页、重复内容"""
        cleaned_pages = []
        
        with pdfplumber.open(pdf_path) as pdf:
            prev_text = ""
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                
                # 过滤空白页
                if not text or len(text.strip()) < 10:
                    continue
                    
                # 过滤重复页（页眉页脚重复）
                if self.is_duplicate(text, prev_text):
                    continue
                    
                cleaned_pages.append({
                    'page_num': i + 1,
                    'text': text
                })
                prev_text = text[:200]  # 只比较前200字符
                
        return cleaned_pages
    
    def add_source_tags(self, chunks, pdf_path):
        """添加来源标签：手册ID + 页码"""
        manual_id = os.path.basename(pdf_path).replace('.pdf', '')
        
        for chunk in chunks:
            chunk['metadata']['source'] = {
                'manual_id': manual_id,
                'page': chunk['metadata'].get('page_range', ['unknown'])[0],
                'full_path': pdf_path
            }
            # 用户追问"内容来源"时可快速定位
            chunk['source_citation'] = f"[来源：{manual_id}，第{chunk['metadata']['source']['page']}页]"
            
        return chunks
    
    def batch_process(self, max_workers=4, test_mode=False):
        """
        批量处理
        test_mode=True: 先用100本手册做小范围测试
        """
        pdf_files = [
            os.path.join(self.input_dir, f) 
            for f in os.listdir(self.input_dir) 
            if f.endswith('.pdf')
        ]
        
        if test_mode:
            pdf_files = pdf_files[:100]
            print(f"【测试模式】选取前100本手册进行验证")
        
        all_chunks = []
        
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.preprocess_pipeline, pdf): pdf 
                for pdf in pdf_files
            }
            
            for future in futures:
                pdf_path = futures[future]
                try:
                    chunks = future.result()
                    all_chunks.extend(chunks)
                    self.processed_count += 1
                except Exception as e:
                    print(f"处理失败 {pdf_path}: {e}")
                    
        # 保存处理结果
        self.save_to_vector_store(all_chunks)
        
        return {
            'total_processed': self.processed_count,
            'total_chunks': len(all_chunks),
            'test_mode': test_mode
        }
```

### 5.2 落地验证与粒度微调

```python
class ChunkEvaluator:
    """切分效果评估器"""
    
    def __init__(self, test_queries):
        self.test_queries = test_queries  # 常见问题集
        
    def evaluate(self, chunks, retriever):
        """
        评估指标：
        1. 匹配精度：查询能否命中正确chunk
        2. 上下文完整性：答案生成是否连贯
        3. 溯源准确性：来源定位是否正确
        """
        results = []
        
        for query in self.test_queries:
            # 执行检索
            retrieved_chunks = retriever.retrieve(query, top_k=5)
            
            # 评估
            result = {
                'query': query,
                'retrieved': [c['chunk_id'] for c in retrieved_chunks],
                'precision': self.check_precision(query, retrieved_chunks),
                'context_complete': self.check_context_completeness(retrieved_chunks),
                'source_traceable': self.check_source_traceability(retrieved_chunks)
            }
            results.append(result)
            
        # 汇总
        avg_precision = sum(r['precision'] for r in results) / len(results)
        
        return {
            'average_precision': avg_precision,
            'detailed_results': results,
            'recommendation': self.generate_tuning_advice(results, chunks)
        }
    
    def generate_tuning_advice(self, results, chunks):
        """根据评估结果生成调优建议"""
        advice = []
        
        # 常见问题1：表格片段漏上下文
        table_issues = [r for r in results if '表格' in r['query'] and not r['context_complete']]
        if len(table_issues) > 5:
            advice.append("【调优】表格上下文范围不足，建议扩大前后关联段落范围（当前2段→4段）")
        
        # 常见问题2：语义单元被拆分
        semantic_issues = [r for r in results if not r['context_complete']]
        if len(semantic_issues) > 10:
            advice.append("【调优】存在语义断裂，建议放宽细颗粒切分的token限制（当前512→768）")
            
        # 常见问题3：来源定位不准
        source_issues = [r for r in results if not r['source_traceable']]
        if len(source_issues) > 3:
            advice.append("【调优】页码标签精度不足，建议增加段落级定位标记")
            
        return advice
```

***

## 6. 分层索引与树形结构（进阶）

### 6.1 双层索引架构

```
                    ┌─────────────────┐
                    │   查询入口        │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │ 粗索引   │    │ 粗索引   │    │ 粗索引   │
        │(章节级)  │    │(章节级)  │    │(章节级)  │
        │第1章产品 │    │第3章参数│    │第5章故障│
        │概述     │    │规格     │    │排除     │
        └────┬────┘    └────┬────┘    └────┬────┘
             │              │              │
        ┌────┴────┐    ┌────┴────┐    ┌────┴────┐
        │ 细索引   │    │ 细索引   │    │ 细索引   │
        │(段落级)  │    │(段落级)  │    │(段落级)  │
        │  ├ 概述  │    │  ├ 参数A │    │  ├ 故障1 │
        │  ├ 特点  │    │  ├ 参数B │    │  ├ 故障2 │
        │  └ 应用  │    │  └ 参数C │    │  └ 故障3 │
        └─────────┘    └─────────┘    └─────────┘
```

### 6.2 树形索引实现（Llama Index风格）

```python
from llama_index.core import TreeIndex, VectorStoreIndex
from llama_index.core.schema import TextNode

class HierarchicalIndexBuilder:
    """分层索引构建器"""
    
    def __init__(self):
        self.coarse_index = None  # 章节级索引
        self.fine_indices = {}   # 各章节内的细粒度索引
        
    def build_tree_index(self, chunks):
        """
        构建树形索引：
        - 第一层：章节摘要节点（粗颗粒）
        - 第二层：段落/表格节点（细颗粒）
        """
        # 按章节分组
        chapter_groups = {}
        for chunk in chunks:
            ch_id = chunk['chunk_id'].split('-')[0]  # 提取"第X章"
            if ch_id not in chapter_groups:
                chapter_groups[ch_id] = []
            chapter_groups[ch_id].append(chunk)
        
        # 构建树结构
        root_nodes = []
        
        for ch_id, ch_chunks in chapter_groups.items():
            # 生成章节摘要节点（粗颗粒）
            chapter_summary = self.summarize_chapter(ch_chunks)
            chapter_node = TextNode(
                text=chapter_summary,
                metadata={
                    'level': 'coarse',
                    'chapter_id': ch_id,
                    'child_ids': [c['chunk_id'] for c in ch_chunks]
                }
            )
            root_nodes.append(chapter_node)
            
            # 章节内构建细颗粒索引
            fine_nodes = [
                TextNode(
                    text=c['content'],
                    metadata={
                        'level': 'fine',
                        'parent_id': ch_id,
                        **c['metadata']
                    }
                ) 
                for c in ch_chunks
            ]
            self.fine_indices[ch_id] = VectorStoreIndex(fine_nodes)
        
        # 顶层粗颗粒索引
        self.coarse_index = VectorStoreIndex(root_nodes)
        
        return {
            'coarse_index': self.coarse_index,
            'fine_indices': self.fine_indices,
            'total_chapters': len(chapter_groups)
        }
    
    def hierarchical_retrieve(self, query, top_k_coarse=3, top_k_fine=5):
        """
        分层检索：
        1. 先在粗索引锁定目标章节
        2. 再在对应章节的细索引精确定位
        """
        # Step 1: 粗检索，定位章节
        coarse_results = self.coarse_index.as_retriever(
            similarity_top_k=top_k_coarse
        ).retrieve(query)
        
        # Step 2: 在命中的章节内进行细检索
        fine_results = []
        for coarse_node in coarse_results:
            ch_id = coarse_node.node.metadata['chapter_id']
            if ch_id in self.fine_indices:
                chapter_results = self.fine_indices[ch_id].as_retriever(
                    similarity_top_k=top_k_fine
                ).retrieve(query)
                fine_results.extend(chapter_results)
        
        # 合并排序
        return sorted(fine_results, key=lambda x: x.score, reverse=True)
    
    def summarize_chapter(self, chunks):
        """生成章节摘要（用于粗颗粒节点）"""
        # 可使用LLM生成摘要，或提取关键句
        combined_text = " ".join([c['content'][:200] for c in chunks[:5]])
        return f"【章节概述】{combined_text}..."
```

***

## 7. 完整处理流程图

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  PDF输入     │────▶│  结构提取    │────▶│  大纲解析    │
│  (百万级手册) │     │ PyPDF2/pdfplumber│  │ 章节层级梳理  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          ▼                    ▼                    ▼
                    ┌─────────┐          ┌─────────┐          ┌─────────┐
                    │粗颗粒切分 │          │细颗粒切分 │          │图表处理  │
                    │章节级    │          │语义保护  │          │OCR+描述 │
                    │标签：章ID│          │类型分类  │          │上下文关联│
                    └────┬────┘          └────┬────┘          └────┬────┘
                         │                    │                    │
                         └────────────────────┼────────────────────┘
                                              ▼
                                        ┌─────────┐
                                        │ 溯源标签  │
                                        │手册ID+页码│
                                        └────┬────┘
                                             ▼
                                        ┌─────────┐
                                        │ 索引构建  │
                                        │双层/树形 │
                                        └────┬────┘
                                             ▼
                              ┌──────────────┴──────────────┐
                              ▼                              ▼
                        ┌─────────┐                    ┌─────────┐
                        │落地验证   │                    │批量处理  │
                        │100本测试  │                    │全量处理  │
                        │粒度微调   │                    │监控告警  │
                        └─────────┘                    └─────────┘
```

***

## 8. 关键配置参数

| 参数项        | 建议值              | 调优依据     |
| :--------- | :--------------- | :------- |
| 粗颗粒最大token | 2000             | 章节内容长度   |
| 细颗粒最大token | 512-768          | 语义单元平均长度 |
| 表格上下文范围    | 前后各1-2段          | 评估结果反馈   |
| 图片描述模型     | GPT-4V / Qwen-VL | 成本与精度平衡  |
| 批量测试样本     | 100本             | 覆盖常见问题类型 |
| 并发 workers | 4-8              | 服务器资源配置  |
| 向量维度       | 1024/1536        | 嵌入模型选择   |

***

## 9. 总结

本方案通过\*\*"先结构化、后切分、再索引"\*\*的三阶段处理，解决百万级手册RAG的核心痛点：

1. **粗颗粒章节切分** → 避免跨章节误切，快速定位范围
2. **细颗粒语义保护** → 保持语义单元完整，生成答案连贯
3. **图表整体处理** → OCR+描述+上下文，实现可检索
4. **批量验证调优** → 100本小范围测试，粒度动态调整
5. **分层树形索引** → 粗索引锁定章节，细索引精确定位

如需进一步探讨分层切割与树形索引的落地细节，或针对特定业务场景调整策略，欢迎交流。

***

**标签：** `#RAG` `#Agent` `#LLM` `#大模型` `#文档处理` `#PDF解析`
