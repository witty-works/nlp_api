import logging
import os
import sys

# Logging set up
def set_up_logger(settings):
    logging.basicConfig(level=settings.logging_config_level)
    logging.getLogger().handlers.clear()
    formatter = logging.Formatter("[%(asctime)s] %(name)s %(levelname)s - %(message)s")

    if settings.logging_enabled:
        if settings.instrumentation_key:
            from opencensus.ext.azure.log_exporter import AzureLogHandler

            ah = AzureLogHandler(
                connection_string="InstrumentationKey={}".format(
                    settings.instrumentation_key
                )
            )
            ah.setFormatter(formatter)
            logging.getLogger().addHandler(ah)
        elif settings.logging_config_filename == "stdout":
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(formatter)
            logging.getLogger().addHandler(sh)
        else:
            filename = os.path.abspath(settings.logging_config_filename)
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            fh = logging.FileHandler(filename=filename)
            fh.setFormatter(formatter)
            logging.getLogger().addHandler(fh)
    else:
        logging.getLogger().addHandler(logging.NullHandler())

    return logging
