import logging
import logging.handlers
from pathlib import Path


class LoggerConfig:
    def __init__(self, log_dir="logs", log_file="app.log", max_bytes=10 * 1024 * 1024, backup_count=5):
        self.script_dir = Path(__file__).resolve().parent
        self.log_dir = self.script_dir / log_dir
        self.log_file = self.log_dir / log_file
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.logger = None

    def setup_logger(self):
        self.log_dir.mkdir(exist_ok=True)
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)

        # 避免重复添加 handler
        if not logger.handlers:
            # 创建 FileHandler，按大小滚动保留最多5个备份
            file_handler = logging.handlers.RotatingFileHandler(
                self.log_file, maxBytes=self.max_bytes, backupCount=self.backup_count, encoding="utf-8"
            )
            file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(file_formatter)

            # 创建 StreamHandler 输出到控制台
            console_handler = logging.StreamHandler()
            console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            console_handler.setFormatter(console_formatter)

            # 添加 handlers
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        self.logger = logger
        return logger
