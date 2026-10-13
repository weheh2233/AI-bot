from app.tools.basic import get_current_time
from app.tools.memory_tools import get_user_memories, save_user_memory
from app.tools.rag_tools import search_knowledge_base
from app.tools.web_tools import fetch_webpage, web_search

tools = [
    get_current_time,
    save_user_memory,
    get_user_memories,
    web_search,
    fetch_webpage,
    search_knowledge_base
]