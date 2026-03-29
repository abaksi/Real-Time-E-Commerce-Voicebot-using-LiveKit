import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Central logging configuration for the voicebot project.
# Creates log files under project_root/logs with rotation.

LOG_DIR = (Path(__file__).parent.parent / "logs").resolve()
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging(name, log_file=None, level=logging.INFO):
    """
    Configure and return a logger that writes to logs/<filename>.

    Args:
        name (str): Logger name.
        log_file (str, optional): Log file name. Defaults to None.
        level (int or str, optional): Logging level (e.g., logging.INFO or 'INFO'). Defaults to logging.INFO.

    Returns:
        logging.Logger: Configured logger instance.

    Notes:
        - Uses INFO level by default.
        - Adds a rotating file handler (5 MB, 5 backups).
        - Also attaches a console handler for immediate diagnostics.
        - Safe to call multiple times for the same logger.
    """
    logger = logging.getLogger(name)
    # Accept log level as string or int
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(level)

    if logger.handlers:
        # Already configured
        return logger

    # Determine log file name
    if log_file is not None:
        log_path = LOG_DIR / log_file
    else:
        log_path = LOG_DIR / f"{name}.log"

    # Clear the log file at startup (refresh log)
    try:
        with open(log_path, "w", encoding="utf-8"):
            pass
    except Exception as e:
        print(f"[LOGGING] Could not clear log file {log_path}: {e}")

    formatter = logging.Formatter(DEFAULT_FORMAT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
