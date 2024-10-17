import logging
import os
import sys
from app.settings import Settings


"""Logger setup class to simplify logging setup."""


class Logger:
    @staticmethod
    def factory(settings: Settings) -> logging.Logger:
        logger = logging.getLogger("nlp_api")
        logger.handlers.clear()

        if settings.logging_enabled:
            formatter = logging.Formatter(
                "[%(asctime)s] %(name)s %(levelname)s - %(message)s"
            )

            if settings.logging_config_filename == "stdout":
                handler = logging.StreamHandler(sys.stdout)
                handler.setFormatter(formatter)
            else:
                filename = os.path.abspath(settings.logging_config_filename)
                os.makedirs(os.path.dirname(filename), exist_ok=True)
                handler = logging.FileHandler(filename=filename)
                handler.setFormatter(formatter)
        else:
            handler = logging.NullHandler()

        logger.addHandler(handler)
        logger.setLevel(settings.logging_config_level)

        return logger
