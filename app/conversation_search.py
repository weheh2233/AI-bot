import re
import unicodedata

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import ConversationSearchTerm


_TITLE_SEGMENT = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+", re.IGNORECASE)


def title_terms(value: str) -> list[str]:
    """Tokenize Latin words and overlapping CJK bigrams for title lookup."""
    terms: set[str] = set()
    normalized = unicodedata.normalize("NFKC", value).casefold()
    for match in _TITLE_SEGMENT.finditer(normalized):
        segment = match.group(0)
        if "\u3400" <= segment[0] <= "\u9fff":
            if len(segment) == 1:
                terms.add(segment)
            else:
                terms.update(segment[index : index + 2] for index in range(len(segment) - 1))
        else:
            terms.add(segment[:64])
    return sorted(terms)


def sync_title_terms(db: Session, conversation) -> bool:
    terms = set(title_terms(conversation.title))
    existing = set(
        db.execute(
            select(ConversationSearchTerm.term).where(
                ConversationSearchTerm.thread_id == conversation.thread_id
            )
        ).scalars()
    )
    if existing == terms:
        return False
    db.execute(
        delete(ConversationSearchTerm).where(
            ConversationSearchTerm.thread_id == conversation.thread_id
        )
    )
    rows = [
        {
            "thread_id": conversation.thread_id,
            "owner_id": conversation.owner_id,
            "term": term,
        }
        for term in terms
    ]
    if rows:
        # 并发下两个请求可能同时同步同一会话（例如同时在发消息和改标题）：
        # 前一个请求提交后，后一个请求的 DELETE 可能看不到这些行，再插入就会撞
        # uq_conversation_search_term。用 ON CONFLICT DO NOTHING 让同步幂等。
        db.execute(
            pg_insert(ConversationSearchTerm)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_conversation_search_term")
        )
    return True
