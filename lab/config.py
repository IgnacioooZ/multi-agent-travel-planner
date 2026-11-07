import os
from dataclasses import asdict, dataclass
from dotenv import load_dotenv
from lab.common import ROOT


@dataclass
class Settings:
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    temperature: float = 0.0
    max_model_calls: int = 24
    max_tool_calls: int = 60
    # None: use the service's advertised maximum, not its smaller default.
    max_output_tokens: int | None = None
    # None 表示只记录累计用量，不因累计 tokens 停止任务。
    max_total_tokens: int | None = None
    max_context_chars: int | None = None
    timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        return cls(model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))

    def public_dict(self):
        return asdict(self)


def api_key():
    """仅在需要模型时读取本地密钥；MCP 工具本身不需要密钥。"""
    load_dotenv(ROOT / ".env", override=False)
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("请在项目根目录 .env 中填写 DEEPSEEK_API_KEY。MCP 自检可直接运行，无需密钥。")
    return key
