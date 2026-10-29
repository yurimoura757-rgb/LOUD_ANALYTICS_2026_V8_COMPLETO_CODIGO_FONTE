"""Coleta incremental e limitada, sem bloquear a interface.

Abertura automática: 1 página de partidas + no máximo 1 série de detalhes.
Coleta completa via terminal: `python app.py --update`.
"""
from datetime import datetime, timezone
import logging
import time
from api.client import VLRAdapter
from core.diagnostics import timed, setup_logging
from database.db_manager import Database

LOG = logging.getLogger(__name__)
AUTO_MAX_DETAILS = 1
AUTO_BUDGET_SECONDS = 13.0
RETRY_HOURS = 24


class DataEngine:
    def __init__(self, db=None):
        self.db = db if db is not None else Database()

    def update(self, callback=None, force=False, auto=False, on_data=None, limit=None, details_only=False):
        """Consulta limitada na GUI, detalhamento completo opcional no CLI.

        `on_data` recebe apenas fases, jamais manipula widgets Tk diretamente.
        O orçamento se aplica ANTES de iniciar uma série: não cancela operações
        já em andamento, que são protegidas por timeout em cada HTTP request.
        """
        setup_logging()
        start = time.monotonic()
        found = processed = errors = 0
        changed = False
        players = set()
        message = 'Concluído.'
        log_id = self.db.log_start()

        def emit(msg, n=0, total=0):
            LOG.info('%s', msg)
            if callback:
                callback(msg, n, total, len(players), errors)

        def notify(phase):
            if on_data:
                try:
                    on_data(phase)
                except Exception:
                    LOG.exception('Notificação para a interface falhou')

        try:
            with VLRAdapter() as api:
                if details_only:
                    # Sem consulta à listagem e sem recadastrar resultados que já existem.
                    entries = []
                    found = self.db.scalar("SELECT COUNT(*) FROM matches WHERE status='completed'", default=0)
                    emit(f'CACHE: {found} partidas locais; enriquecendo somente detalhes pendentes.')
                    if not found:
                        raise ValueError('Nenhuma partida no cache. Use Atualizar dados primeiro.')
                else:
                    with timed('Buscar lista de partidas da LOUD (2026)'):
                        entries = api.completed(full=not auto)
                    found = len(entries)
                    emit(f'LISTA: {found} partidas encontradas na fonte.')
                    if entries:
                        with timed('Gravar partidas no cache SQLite'):
                            saved = self.db.save_match_list(entries)
                        if saved:
                            changed = True
                            notify('matches')
                    if not auto:
                        self.db.set_sync('last_full_history', datetime.now(timezone.utc).isoformat())
                # Priorizar partidas novas, sem reprocessar as concluídas.
                ids = self.db.pending_match_ids(retry_hours=RETRY_HOURS if auto else 0)
                if details_only and not auto:
                    advanced = self.db.pending_advanced_ids()
                    ids = list(dict.fromkeys(ids + advanced))
                if force:
                    ids = ([m['id'] for m in entries] if not details_only else
                           [int(r['id']) for r in self.db.frame(
                               "SELECT id FROM matches WHERE status='completed' ORDER BY date_utc DESC").to_dict('records')])
                if auto:
                    ids = ids[:AUTO_MAX_DETAILS]
                elif limit is not None:
                    ids = ids[:max(0, int(limit))]
                emit(f'DETALHES: {len(ids)} série(s) nesta execução.')
                for pos, match_id in enumerate(ids, start=1):
                    if auto and time.monotonic() - start >= AUTO_BUDGET_SECONDS:
                        emit('Tempo de atualização rápida atingido; restantes serão processados em outra execução.')
                        break
                    try:
                        # Marca a tentativa ANTES da chamada para evitar
                        # recomeçar o mesmo item caso a conexão falhe.
                        self.db.mark_detail_attempt(match_id)
                        if not auto:
                            self.db.mark_advanced_attempt(match_id)
                        with timed(f'Partida {pos}/{len(ids)} - ID {match_id}'):
                            def persist_maps(map_rows, event_id):
                                # Salva placares ANTES da coleta pesada dos jogadores.
                                # Se houver falha depois, o gráfico já pode abrir.
                                self.db.save_details(match_id, map_rows, [], event_id)
                                notify('maps')
                            maps, stats, tournament_id, warnings = api.details(
                                match_id, include_advanced=not auto,
                                on_vetoes=lambda vetoes:self.db.save_vetoes(match_id,vetoes),
                                on_maps=persist_maps)
                            if not maps:
                                raise ValueError('A fonte não retornou mapas para esta série')
                            complete = self.db.save_details(
                                match_id, maps, stats, tournament_id)
                        processed += 1
                        changed = True
                        players.update(s['player_id'] for s in stats)
                        notify('details')
                        emit(f'SALVO: {match_id} ({len(maps)} mapa(s), {len(stats)} registro(s) de jogador; completo={complete})')
                        for warning in warnings:
                            LOG.warning('API: %s | %s', match_id, warning)
                    except Exception as exc:
                        errors += 1
                        LOG.exception('Falha na partida %s: %s', match_id, exc)
                if not auto and not details_only:
                    for desc, task in (
                        ('Elenco', lambda: self.db.save_players(api.roster(), roster_status='Atual na fonte')),
                        ('Transferências', lambda: self._transactions(api)),
                        ('Partidas futuras', lambda: self._upcoming(api)),
                        ('Composições da LOUD', lambda: self.db.save_team_compositions(api.compositions())),
                    ):
                        try:
                            with timed('Metadados: ' + desc):
                                task()
                        except Exception as exc:
                            LOG.warning('%s indisponível: %s', desc, exc)
                self.db.set_sync('last_online_check', datetime.now(timezone.utc).isoformat())
                if not found and not self.db.has_history():
                    errors += 1
                    message = 'A API não retornou partidas da LOUD em 2026.'
                else:
                    message = f'Partidas no cache: {found}; séries detalhadas nesta execução: {processed}; falhas: {errors}.'
        except Exception as exc:
            errors += 1
            message = f'{type(exc).__name__}: {exc}'
            LOG.exception('FALHA DE CONEXÃO/COLETA: %s', message)
        finally:
            try:
                self.db.log_end(log_id, found, processed, errors, message)
            except Exception:
                LOG.exception('Falha ao finalizar log de coleta no banco')
            emit(f'ATUALIZAÇÃO ENCERRADA em {time.monotonic()-start:.1f}s: {message}')
        return dict(found=found, processed=processed, players=len(players),
                    errors=errors, changed=changed, message=message,
                    skipped=False, full=not auto and not details_only, details_only=details_only)

    def _transactions(self, api):
        players, tx = api.transactions()
        self.db.save_players(players)
        self.db.save_transactions(tx)

    def _upcoming(self, api):
        upcoming = api.upcoming()
        if upcoming:
            self.db.save_match_list(upcoming)
