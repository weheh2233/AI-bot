##  RecursiveCharacterTextSplitter —— 递归切分

from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""],   # 中文场景建议自定义
)


def split_segments(
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



