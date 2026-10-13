from datetime import datetime, timezone, timedelta
from langchain_core.tools import tool

@tool
def get_current_time()->str:
    """返回当前北京时间,当用户问现在目前的时间时调用

    输入：无。
    返回：格式为 "YYYY-MM-DD HH:MM:SS" 的北京时间字符串
    """
    beijing = timezone(timedelta(hours=8))
    return datetime.now(beijing).strftime("%Y-%m-%d %H:%M:%S")





