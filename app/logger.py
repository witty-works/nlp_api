import logging
import os
import sys

class LoggerConfig:
    """Logger configuration class to simplify logging setup."""
    
    @staticmethod
    def setup(settings):
        logger = logging.getLogger("nlp_api")
        logger.handlers.clear()

        if settings.logging_enabled:
            formatter = logging.Formatter(
                "[%(asctime)s] %(name)s %(levelname)s - %(message)s"
            )

            if settings.instrumentation_key:
                from opencensus.ext.azure.log_exporter import AzureLogHandler

                handler = AzureLogHandler(
                    connection_string="InstrumentationKey={}".format(
                        settings.instrumentation_key
                    )
                )
                handler.setFormatter(formatter)
            elif settings.logging_config_filename == "stdout":
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
