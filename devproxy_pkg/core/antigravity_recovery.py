






import os
import sys
from typing import Tuple, List, Dict, Any


class ASARRecoveryManager:
    





    @staticmethod
    def is_protected_system_path(path: str) -> bool:
        
        norm = os.path.abspath(path).lower()
        if sys.platform == "win32":
            prog_files = os.environ.get("ProgramFiles", "C:\\Program Files").lower()
            prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)").lower()
            system_root = os.environ.get("SystemRoot", "C:\\Windows").lower()
            return norm.startswith(prog_files) or norm.startswith(prog_files_x86) or norm.startswith(system_root)
        elif sys.platform == "darwin":
            return norm.startswith("/applications") or norm.startswith("/system")
        else:
            return norm.startswith("/usr") or norm.startswith("/etc") or norm.startswith("/opt")

    @staticmethod
    def is_writable(path: str) -> bool:
        
        if os.path.exists(path):
            return os.access(path, os.W_OK)
        parent = os.path.dirname(os.path.abspath(path))
        return os.path.exists(parent) and os.access(parent, os.W_OK)

    @classmethod
    def evaluate_injection_strategy(cls, executable_path: str, config_paths: List[str]) -> Dict[str, Any]:
        



        is_sys_install = cls.is_protected_system_path(executable_path)
        unwritable_configs = [c for c in config_paths if not cls.is_writable(c)]

        if is_sys_install or unwritable_configs:
            return {
                "strategy": "env_only_fallback",
                "reason": (
                    f"Installation is located in a protected system directory "
                    f"or configuration files require elevated UAC privileges."
                ),
                "safe_cli_flags": [
                    "--proxy-server={PROXY_URL}",
                    "--enable-features=NetworkService,NetworkServiceInProcess",
                ],
                "requires_uac": False,
            }

        return {
            "strategy": "standard_persistent",
            "reason": "All configuration targets are user-writable without UAC elevation.",
            "safe_cli_flags": [],
            "requires_uac": False,
        }

    @classmethod
    def cleanup_legacy_backups(cls, search_dir: str) -> List[str]:
        
        cleaned = []
        if not os.path.exists(search_dir) or not os.access(search_dir, os.W_OK):
            return cleaned

        try:
            for root, _, files in os.walk(search_dir):
                for f in files:
                    if f.endswith(".devproxy.bak"):
                        full_path = os.path.join(root, f)
                        try:
                            os.remove(full_path)
                            cleaned.append(full_path)
                        except OSError:
                            pass
        except Exception:
            pass

        return cleaned
