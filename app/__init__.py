import warnings

# LangGraph 的 Runtime.context 字段用泛型 TypeVar 却标了 default=None，
# pydantic 序列化 checkpoint 时会误报 PydanticSerializationUnexpectedValue，
# 属框架缺陷，功能无影响，这里精确屏蔽。
warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
)
