import ast
import os

from dotenv import load_dotenv

load_dotenv()


def _eval_size_expr(node: ast.AST) -> float:
    """安全求值只含数字常量与乘法的表达式（如 20 * 1024 * 1024），不执行任意代码。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _eval_size_expr(node.left) * _eval_size_expr(node.right)
    raise ValueError("MAX_UPLOAD_BYTES 表达式只支持数字和乘法")


def _parse_size(value: str) -> int:
    """解析上传大小上限，支持 '20971520' / '20MB' / '20 * 1024 * 1024' 三种写法。"""
    s = value.strip()
    upper = s.upper()
    for suffix, mul in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if upper.endswith(suffix):
            return int(float(s[: -len(suffix)].strip()) * mul)
    return int(_eval_size_expr(ast.parse(s, mode="eval").body))


class Settings:
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    # 只在服务器保存，用于加密数据库里的个人 API Key；不要和 JWT 密钥混用。
    model_settings_encryption_key: str = os.getenv("MODEL_SETTINGS_ENCRYPTION_KEY", "")
    embedding_model_api_key:str=os.getenv("DASHSCOPE_API_KEY")
    embedding_model_base_url:str=os.getenv("DASHSCOPE_BASE_URL")
    zhipuai_api_key: str = os.getenv("ZHIPUAI_API_KEY", "")
    database_url :str= os.getenv("DATABASE_URL")
    max_upload_bytes: int = _parse_size(os.getenv("MAX_UPLOAD_BYTES", "5MB"))
settings = Settings()


