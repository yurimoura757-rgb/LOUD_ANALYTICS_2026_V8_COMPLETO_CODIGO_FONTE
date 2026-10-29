"""Início da GUI, atualização e diagnóstico (com etapas exibidas no terminal)."""
import argparse
import importlib.util
import logging
import os
from pathlib import Path

from config import DB_PATH, LOG_PATH
from core.diagnostics import setup_logging, timed
from core.data_engine import DataEngine
from database.db_manager import Database

LOG = logging.getLogger(__name__)


def diagnostic():
    with timed('Diagnóstico de dependências e banco'):
        db = Database()
        print('LOUD Analytics | Diagnóstico', flush=True)
        print('Banco:', DB_PATH, flush=True)
        print('Banco existe:', Path(DB_PATH).exists(), flush=True)
        print('Biblioteca vlrdevapi instalada:', importlib.util.find_spec('vlrdevapi') is not None, flush=True)
        for name in ('matches', 'match_maps', 'player_map_stats', 'players'):
            print(name + ':', db.scalar('SELECT COUNT(*) FROM ' + name, default=0), flush=True)
        print('Séries detalhadas:', db.scalar('SELECT COUNT(*) FROM matches WHERE details_complete=1',default=0),flush=True)
        print('Séries aguardando detalhes:', db.scalar("SELECT COUNT(*) FROM matches WHERE status='completed' AND details_complete=0",default=0),flush=True)
        print('Última tentativa:', db.last_attempt() or 'nunca', flush=True)
        with db.connect() as con:
            row = con.execute('SELECT message FROM update_logs ORDER BY id DESC LIMIT 1').fetchone()
        print('Último resultado:', row[0] if row else 'nenhum', flush=True)
        print('Log detalhado:', LOG_PATH, flush=True)


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description='LOUD Analytics 2026 | VLR.gg')
    parser.add_argument('--update', action='store_true', help='coletar dados via terminal')
    parser.add_argument('--force', action='store_true', help='reprocessar partidas já existentes')
    parser.add_argument('--completar', action='store_true', help='coletar detalhes pendentes SEM baixar novamente a lista de partidas')
    parser.add_argument('--limite', type=int, default=None, help='limitar séries detalhadas no terminal (ex.: 5)')
    parser.add_argument('--diagnostico', action='store_true', help='inspecionar arquivos, banco e dependências')
    args = parser.parse_args()
    LOG.info('LOUD Analytics iniciado | PID=%s | pasta=%s', os.getpid(), DB_PATH.parent)
    try:
        if args.diagnostico:
            diagnostic()
            return 0
        if args.update or args.completar:
            LOG.info('Atualização no terminal | completar=%s | limite=%s | forçar=%s', args.completar, args.limite, args.force)
            with timed('Coleta no terminal'):
                result = DataEngine().update(force=args.force, limit=args.limite, details_only=args.completar)
            print('\nRESUMO FINAL:', result, flush=True)
            return 0 if not result['errors'] else 1
        from interface.app import LoudApp
        with timed('Criar janela Tkinter'):
            app = LoudApp()
        LOG.info('Janela pronta. Carregamento SQLite e API seguem em threads.')
        app.mainloop()
        return 0
    except KeyboardInterrupt:
        LOG.warning('Operação interrompida pelo usuário (Ctrl+C).')
        return 130
    except Exception:
        LOG.exception('ERRO FATAL: o aplicativo não pôde iniciar')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
