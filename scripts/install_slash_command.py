from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    source = plugin_root / "commands" / "questline.md"
    if not source.exists():
        raise FileNotFoundError(source)

    codex_home = Path.home() / ".codex"
    target_dir = codex_home / "commands"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "questline.md"

    shutil.copyfile(source, target)
    print(f"Installed /questline command shim: {target}")


if __name__ == "__main__":
    main()
