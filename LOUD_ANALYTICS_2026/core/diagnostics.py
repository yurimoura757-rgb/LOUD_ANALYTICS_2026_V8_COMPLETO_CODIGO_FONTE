"""Logs visíveis no terminal e no arquivo, com duração de cada operação."""
import logging
import sys
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from config import LOG_PATH


def setup_logging():
    root = logging.getLogger()
    # Configuração idempotente: não instala handlers duplicados a cada thread.
    if getattr(root, '_loud_logging_ready', False):
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(threadName)s | %(message)s',
        datefmt='%H:%M:%S')
    # Em executáveis --windowed, sys.stdout pode ser None.
    if sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        root.addHandler(stream)
    try:
        file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000,
                                           backupCount=2, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning('Não foi possível criar arquivo de log: %s', exc)
    root._loud_logging_ready = True


@contextmanager
def timed(stage):
    log = logging.getLogger('loud.etapas')
    start = time.monotonic()
    log.info('INÍCIO: %s', stage)
    try:
        yield
    except Exception:
        log.exception('ERRO: %s (%.2fs)', stage, time.monotonic() - start)
        raise
    else:
        log.info('FIM: %s (%.2fs)', stage, time.monotonic() - start)
