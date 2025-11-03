import logging
import os
import sys
from app.settings import Settings


class Logger:
    """Factory for the application logger.

    Configures a logger to write to stdout or to a file depending on settings,
    with a consistent format and level. No handlers are added when logging is
    disabled.
    """

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
