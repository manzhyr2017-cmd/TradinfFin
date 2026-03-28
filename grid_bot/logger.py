import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name="GridBot", log_file="grid_bot.log", level=logging.INFO):
    """Establishes a rotating file logger for the grid bot."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent adding handlers multiple times in interactive/restarting environments
    if not logger.handlers:
        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File Handler (Rotating at 5MB, keep 3 backup files)
        file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

logger = setup_logger()
