"""按文档结构切分 RAG 文本，并保留 loader 提供的定位信息。"""

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""],   # 中文场景建议自定义
)


def _build_heading_prefix(meta: dict) -> str:
    path = [meta[key] for key in ("h1", "h2", "h3") if meta.get(key)]
    if not path:
        return ""
    return f"章节：{' > '.join(path)}\n\n"

_md_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
    ],
    strip_headers=True,
)


def route_file_type(
    segments: list[tuple[str, dict | None]],
) -> list[tuple[str, dict | None]]:
    """根据 loader 的 metadata 选择结构切分策略。

    PDF 当前只带 page_number，因此也通过该定位字段识别；未知格式使用通用切分。
    """
    if not segments:
        return []

    _, meta = segments[0]
    meta = meta or {}

    file_type = meta.get("format")
    match file_type:
        case "md":
            return split_markdown(segments)
        case "pdf" | "docx" | "pptx" | "txt":
            return split_common_segments(segments)
        case _:
            return split_common_segments(segments)


def split_markdown(
    segments: list[tuple[str, dict | None]],
) -> list[tuple[str, dict | None]]:
    """先按 Markdown 标题分章节，再在每个章节内部按长度递归切分。"""
    chunks: list[tuple[str, dict | None]] = []

    for text, base_meta in segments:
        sections = _md_header_splitter.split_text(text)

        for section in sections:
            heading_meta = section.metadata
            prefix = _build_heading_prefix(heading_meta)
            body = section.page_content

            for piece in splitter.split_text(body):
                if piece.strip():
                    meta = {**(base_meta or {}), **heading_meta}
                    content = f"{prefix}{piece}" if prefix else piece
                    chunks.append((content, meta))

    return chunks


def split_common_segments(
    segments: list[tuple[str, dict | None]],
) -> list[tuple[str, dict | None]]:
    """在每段内切分，子块继承该段定位。输入输出同构（loader 输出即输入形态）。

    段内切而非全文切，是为了让 PDF 的一页切出的所有 chunk 都带同一 page_number，
    页码不会因跨页而错乱。
    """
    chunks: list[tuple[str, dict | None]] = []
    for text, meta in segments:
        for piece in splitter.split_text(text):
            if piece.strip():          # 丢掉纯空白块
                chunks.append((piece, meta))
    return chunks



