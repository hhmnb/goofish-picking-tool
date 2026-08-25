# logger.py
import logging
from logging.handlers import RotatingFileHandler
from config import LOG_FILE

def setup_logger():
    logger = logging.getLogger("goofish")
    if logger.handlers:  # 防止重复添加
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # 文件处理器
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1*1024*1024, backupCount=0, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_logger()