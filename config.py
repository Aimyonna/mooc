"""
统一配置模块
-----------
职责：
  1. 加载 .env 环境变量（数据库连接、文件路径等）
  2. 提供工业级双通道日志工厂：
     - 控制台 handler → 仅输出 ERROR
     - 文件 handler   → 输出 INFO 及以上，按大小轮转（10MB × 5）
使用：
  from config import get_logger, DB_HOST, ...
"""
import glob
import logging
import os
import re
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ============================================================
# 项目根目录
# ============================================================
BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# 1. 加载 .env 文件
# ============================================================
try:
    from dotenv import load_dotenv

    _env_path = BASE_DIR / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        # .env 缺失时静默回退到系统环境变量，不阻断运行
        pass
except ImportError:
    # python-dotenv 未安装时静默回退
    pass

# ============================================================
# 2. 数据库配置
# ============================================================
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "mooc")
DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")

# ============================================================
# 3. 文件路径配置
# ============================================================
COOKIE_FILE = os.getenv("COOKIE_FILE", "cookies.json")
COURSES_FILE = os.getenv("COURSES_FILE", "courses.txt")

# ============================================================
# 4. 浏览器配置
# ============================================================
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")


def chrome_service():
    """构造 ChromeDriver Service。

    优先用本地缓存的 chromedriver（离线），避免 webdriver_manager 每次联网
    查最新版本号——国内到 googleapis 的连接常被 reset，会导致脚本直接起不来。
    找不到缓存才退回 webdriver_manager（联网下载）。
    """
    from selenium.webdriver.chrome.service import Service

    home = str(Path.home())
    cands = []
    cands += glob.glob(
        f"{home}/.wdm/drivers/chromedriver/win64/*/chromedriver-win*/chromedriver.exe"
    )
    cands += glob.glob(
        f"{home}/.cache/selenium/chromedriver/win64/*/chromedriver.exe"
    )
    if cands:
        def _verkey(p: str):
            m = re.findall(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", p)
            return tuple(int(x) for x in m[0]) if m else (0, 0, 0, 0)

        cands.sort(key=_verkey)
        return Service(cands[-1])

    from webdriver_manager.chrome import ChromeDriverManager
    return Service(ChromeDriverManager().install())

# ============================================================
# 5. 日志配置
# ============================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / os.getenv("LOG_DIR", "logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s"
LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ============================================================
# 6. 日志工厂函数
# ============================================================
def get_logger(name: str) -> logging.Logger:
    """创建双通道 logger

    Parameters
    ----------
    name : str
        logger 名称，建议用 __name__ 或模块简短名

    Returns
    -------
    logging.Logger
        - 控制台: ERROR 级别（仅严重问题才会出现在终端）
        - 文件:   INFO 级别（完整操作记录写入 logs/crawler.log）
        - 按 10MB 轮转，保留最近 5 个备份
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)       # 放行所有级别，由各 handler 自行过滤
    logger.propagate = False             # 不向根 logger 传播，避免重复

    # 避免重复注册（热重载 / 多次 import 场景）
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FMT)

    # --- 控制台：仅 ERROR ---
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.ERROR)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # --- 文件：INFO 以上，轮转 ---
    file_handler = RotatingFileHandler(
        filename=str(LOG_DIR / "crawler.log"),
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
