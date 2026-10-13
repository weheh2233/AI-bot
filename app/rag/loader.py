import io
import pymupdf as fitz
from docx import Document
from pptx import Presentation
# 不受支持的后缀名
class UnsupportedFormatError(Exception):
    pass


def extract_segments(filename: str, data: bytes) -> list[tuple[str, dict | None]]:
    """按扩展名把上传文件转成 (文本, 定位) 段列表。

    定位是"能给就给"：PDF 按页拆，每页带 {"page_number": n}；
    其余格式整段返回，定位为 None。
    返回多段而非一整段，是为了让切分在段内进行，PDF 的 chunk 不跨页，
    页码天然正确。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("txt", "md"):
        return [(data.decode("utf-8", errors="ignore"), None)]

    if ext == "pdf":
        with fitz.open(stream=data, filetype="pdf") as doc:
            return [
                (page.get_text(), {"page_number": i + 1})
                for i, page in enumerate(doc)
            ]

    if ext == "docx":
          # 局部 import：没装时只在这条分支报错

        doc = Document(io.BytesIO(data))
        return [("\n".join(p.text for p in doc.paragraphs), None)]

    if ext == "pptx":


        prs = Presentation(io.BytesIO(data))
        parts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    parts.append(shape.text_frame.text)
        return [("\n".join(parts), None)]

    raise UnsupportedFormatError(ext)
