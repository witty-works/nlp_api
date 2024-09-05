import logging
import os
import sys
from app.settings import Settings


class LoggerSetup:
    """Logger setup class to simplify logging setup."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_logger(self):
        logger = logging.getLogger("nlp_api")
        logger.handlers.clear()

        if self.settings.logging_enabled:
            formatter = logging.Formatter(
                "[%(asctime)s] %(name)s %(levelname)s - %(message)s"
            )

            if self.settings.logging_config_filename == "stdout":
                handler = logging.StreamHandler(sys.stdout)
                handler.setFormatter(formatter)
            else:
                filename = os.path.abspath(self.settings.logging_config_filename)
                os.makedirs(os.path.dirname(filename), exist_ok=True)
                handler = logging.FileHandler(filename=filename)
                handler.setFormatter(formatter)
        else:
            handler = logging.NullHandler()

        logger.addHandler(handler)
        logger.setLevel(self.settings.logging_config_level)

        return logger
