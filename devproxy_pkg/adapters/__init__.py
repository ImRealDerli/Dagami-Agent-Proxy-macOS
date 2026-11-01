



from typing import Dict, List, Optional
from .chatgpt import ChatGPTAdapter
from .chatgpt_web import ChatGPTWebAdapter
from .base import ApplicationAdapter
from .antigravity import AntigravityAdapter
from .antigravity_ide import AntigravityIDEAdapter
from .vscode_family import VSCodeAdapter, CursorAdapter, WindsurfAdapter, VSCodiumAdapter
from .opencode import OpenCodeAdapter
from .codex import CodexCliAdapter, CodexGuiAdapter
from .cli_tools import CliToolAdapter
from .opencode_desktop import OpenCodeDesktopAdapter


ALL_ADAPTERS: List[ApplicationAdapter] = [
    AntigravityAdapter(),
    AntigravityIDEAdapter(),
    VSCodeAdapter(),
    CursorAdapter(),
    WindsurfAdapter(),
    VSCodiumAdapter(),
    OpenCodeAdapter(),
    CodexCliAdapter(),
    CodexGuiAdapter(),
    ChatGPTAdapter(),
    ChatGPTWebAdapter(),
    OpenCodeDesktopAdapter(),
    CliToolAdapter("gemini", "Gemini CLI", "gemini"),
    CliToolAdapter("claude", "Claude Code", "claude"),
    CliToolAdapter("agy", "agy CLI", "agy"),
    CliToolAdapter("git", "Git", "git"),
]


def get_adapter(app_id: str) -> Optional[ApplicationAdapter]:
    app_id = app_id.lower().strip()
    for adapter in list_adapters():
        if adapter.app_id.lower() == app_id:
            return adapter
    return None


def list_adapters() -> List[ApplicationAdapter]:
    from .custom import adapters
    return ALL_ADAPTERS + adapters()
