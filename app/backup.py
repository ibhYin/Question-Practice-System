"""智能备份：数据变更驱动的按需备份（替代固定时间的定时任务）。

触发点：应用启动 / 结束面试 / 题目增删改 —— maybe_backup() 检查距上次备份
是否超过 min_interval（默认 24h），到期才真正执行。备份在后台线程完成，零阻塞。

设计依据：所有数据变更都发生在应用运行时 —— "用过应用就有 ≤24h 的恢复点，
长期不用 = 数据没变 = 无需备份"，不依赖电脑几点开机。
"""

import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import settings
from .redis_client import rdb

LAST_TS_KEY = "backup:last_ts"
RUNNING_KEY = "backup:running"
KEEP_COUNT = 10  # 保留最近 10 份

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "data" / "backups"


def maybe_backup(min_interval_sec: int = 86400) -> bool:
    """距上次备份超过 min_interval_sec 则触发一次后台备份。

    返回 True 表示已触发（或正在备份），False 表示间隔内跳过。
    任何调用点都可以随意调用，内部自带防抖与并发保护。
    """
    last = rdb.get(LAST_TS_KEY)
    if last:
        try:
            if time.time() - float(last) < min_interval_sec:
                return False
        except ValueError:
            pass  # 值损坏按"没有备份"处理
    return force_backup()


def force_backup() -> bool:
    """无视间隔立即触发备份（手动场景）。"""
    # SETNX + 过期防并发重入；卡死 5 分钟自动解锁
    if not rdb.set(RUNNING_KEY, "1", nx=True, ex=300):
        return False
    threading.Thread(target=_run_backup, daemon=True).start()
    return True


def _run_backup() -> None:
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = BACKUP_DIR / f"interview_{stamp}.sql.gz"
        dump_cmd = (
            f'docker exec interview-mysql mysqldump -u{settings.mysql_user} '
            f'-p"{settings.mysql_password}" --single-transaction {settings.mysql_database}'
        )
        proc = subprocess.run(
            ["bash", "-lc", f"{dump_cmd} | gzip > '{target}'"],
            capture_output=True, text=True, timeout=300,
        )
        # mysqldump 的密码警告走 stderr 不影响退出码；以退出码 + 文件非空为准
        if proc.returncode != 0 or not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            detail = (proc.stderr or "空文件").strip().splitlines()[-1:] 
            print(f"[backup] 备份失败，跳过（下次触发重试）：{detail}")
            return
        _cleanup_old()
        rdb.set(LAST_TS_KEY, str(time.time()))
        print(f"[backup] 完成：{target.name}（{target.stat().st_size // 1024} KB）")
    except Exception as e:
        print(f"[backup] 异常：{type(e).__name__}: {e}")
    finally:
        rdb.delete(RUNNING_KEY)


def _cleanup_old() -> None:
    files = sorted(BACKUP_DIR.glob("interview_*.sql.gz"))
    for old in files[:-KEEP_COUNT]:
        old.unlink(missing_ok=True)
