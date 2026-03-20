# scripts/user_stats.py — Статистика активности пользователей по логам продакшена
#
# Использование:
#   python scripts/fetch_logs.py -s 12h        # скачать логи
#   python scripts/user_stats.py               # анализ последнего лог-файла
#   python scripts/user_stats.py logs/file.log  # анализ конкретного файла

import re
import sys
from collections import Counter
from pathlib import Path

COMMANDS = ["/start", "/settings", "/chats", "/connect", "/poke", "/status", "/disconnect"]


def analyze_log(log_path: str) -> None:
    """Анализирует лог-файл и выводит статистику по пользователям."""
    lines = Path(log_path).read_text(encoding="utf-8").splitlines()

    users: dict[str, dict] = {}
    for line in lines:
        for uid in re.findall(r"user (\d+)", line):
            if uid not in users:
                users[uid] = {"lines": 0, "cmds": [], "components": []}
            users[uid]["lines"] += 1
            for cmd in COMMANDS:
                if cmd in line:
                    users[uid]["cmds"].append(cmd)
            m = re.search(r"\[(\w[\w-]*)\]", line)
            if m:
                users[uid]["components"].append(m.group(1))

    print(f"Уникальных пользователей: {len(users)}\n")
    for uid, data in sorted(users.items(), key=lambda x: -x[1]["lines"]):
        cmds = Counter(data["cmds"])
        comps = Counter(data["components"])
        cmd_str = ", ".join(f"{c}×{n}" for c, n in cmds.most_common()) if cmds else "—"
        comp_str = ", ".join(f"{c}={n}" for c, n in comps.most_common(5))
        print(f"  user {uid}: {data['lines']} строк")
        print(f"    Команды: {cmd_str}")
        print(f"    Компоненты: {comp_str}")
        print()


def _find_latest_log() -> str | None:
    """Находит последний лог-файл в папке logs/."""
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    if not logs_dir.exists():
        return None
    logs = sorted(logs_dir.glob("production_*.log"), key=lambda p: p.stat().st_mtime)
    return str(logs[-1]) if logs else None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = _find_latest_log()
        if not path:
            print("❌ Лог-файл не найден. Сначала выполните: python scripts/fetch_logs.py -s 12h")
            sys.exit(1)
        print(f"📄 Файл: {path}\n")

    analyze_log(path)
