import logging

def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    return logger
