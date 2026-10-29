"""Adaptador para a API pública DOCUMENTADA da biblioteca vlrdevapi.

Sem scraping caseiro nem endpoints presumidos. Os dados são obtidos em tempo real
na máquina do usuário e a base local é populada apenas após as requisições.
"""
from datetime import date, datetime, timezone
from core.diagnostics import timed
import logging
from config import TEAM_ID, YEAR, SOURCE

LOG = logging.getLogger(__name__)


def safe(value, attribute, default=None):
    return getattr(value, attribute, default) if value is not None else default


def iso(value):
    if value is None:
        return None
    if isinstance(value, (date,datetime)):
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(timezone.utc).isoformat()
        return value.isoformat()
    return str(value)


def season(value):
    """Datas conhecidas devem pertencer à temporada; desconhecidas não são inventadas."""
    if value is None:
        return False
    try:
        return datetime.fromisoformat(iso(value)).year == YEAR
    except (ValueError, TypeError):
        return False


class VLRAdapter:
    def __enter__(self):
        try:
            from vlrdevapi import VLRClient
        except ImportError as exc:
            raise RuntimeError('Biblioteca vlrdevapi ausente. Execute: pip install -r requirements.txt') from exc
        # Timeout por requisição e SEM retries automáticos demorados.
        # Cada tela usa este adaptador dentro de uma thread, nunca no Tk.
        self.client = VLRClient(timeout=7, max_retries=0, requests_per_second=2)
        self.client.__enter__()
        self.team = self.client.team(TEAM_ID)
        return self

    def __exit__(self, *args):
        self.client.__exit__(*args)

    def confirm_team(self):
        info = self.team.info()
        name = safe(info, 'name','')
        if 'loud' not in str(name).casefold():
            raise RuntimeError(f'ID {TEAM_ID} não corresponde à LOUD: {name}')
        return name

    def completed(self, full=True):
        # Busca rápida: somente a primeira página para novidades; varredura
        # completa semanal e no primeiro uso garante histórico integral.
        with timed("API: listar partidas" + (" (todas as páginas)" if full else " (primeira página)")):
            result = self.team.completed_matches(return_all=bool(full))
        entries = list(safe(result, 'matches',[]) or [])
        self.last_completed_has_more = bool(safe(result, 'has_next_page', False))
        self.last_completed_has_old_year = any(
            safe(x,'datetime') is not None and
            getattr(safe(x,'datetime'), 'year', YEAR) < YEAR for x in entries)
        matches = []
        for x in entries:
            if not season(safe(x,'datetime')):
                continue
            op = safe(x,'opponent')
            mid = safe(x,'match_id')
            if not mid:
                continue
            matches.append({
                'id':int(mid),'date_utc':iso(safe(x,'datetime')),
                'tournament':safe(x,'event') or 'Não informado',
                'stage':safe(x,'stage'),'bracket':safe(x,'bracket'),
                'opponent_id':safe(op,'id'),'opponent':safe(op,'name') or 'N/D',
                'team_score':safe(x,'team_score'), 'opponent_score':safe(x,'opponent_score'),
                'won':None if safe(x,'is_win') is None else int(safe(x,'is_win')),
                'url':safe(x,'url') or f'https://www.vlr.gg/{mid}',
                'status':'completed'
            })
        # Dedupe com ID VLR. A biblioteca tem return_all=True para buscar todas as páginas.
        return list({m['id']:m for m in matches}.values())

    def upcoming(self):
        try:
            result = self.team.upcoming_matches()
        except Exception as e:
            LOG.warning('Partidas futuras indisponíveis: %s',e)
            return []
        rows = []
        for x in (safe(result,'matches',[]) or []):
            if not season(safe(x,'datetime')) or not safe(x,'match_id'):
                continue
            op = safe(x,'opponent')
            rows.append(dict(id=int(x.match_id),date_utc=iso(x.datetime),
                tournament=safe(x,'event') or 'Não informado',stage=safe(x,'stage'),
                bracket=None,opponent_id=safe(op,'id'),
                opponent=safe(op,'name') or 'A definir',team_score=None,
                opponent_score=None,won=None,
                url=safe(x,'url') or f'https://www.vlr.gg/{x.match_id}',status='upcoming'))
        return rows

    def roster(self):
        data = self.team.roster()
        players=[]
        for x in (safe(data,'players',[]) or []):
            if safe(x,'id') and safe(x,'ign'):
                players.append(dict(id=int(x.id),nickname=x.ign,
                    real_name=safe(x,'real_name'),country=safe(x,'country')))
        return players

    def transactions(self):
        data = self.team.transactions()
        players,records=[],[]
        for x in (safe(data,'transactions',[]) or []):
            p=safe(x,'player')
            if not safe(p,'id') or not safe(p,'ign'):
                continue
            # Incluímos apenas transações datadas até o fim da temporada, preservando
            # a data real, inclusive entradas anteriores a 2026.
            d=iso(safe(x,'date'))
            if d and d[:10]>'2026-12-31':
                continue
            players.append(dict(id=int(p.id),nickname=p.ign,
                real_name=safe(p,'real_name'),country=safe(p,'country')))
            action=safe(x,'action')
            records.append(dict(player_id=int(p.id),date=d,
                action=safe(action,'value',str(action)),
                position=safe(x,'position') or '',source_url=safe(x,'source_url')))
        return players,records

    def compositions(self):
        """Team Stats oficial da biblioteca: date_start/end e agent_composition=basic."""
        from datetime import date
        stats=self.team.stats(date_start=date(2026,1,1),date_end=date(2026,12,31),
                              agent_composition='basic')
        rows=[]
        for m in (safe(stats,'maps',[]) or []):
            if not safe(m,'map_name'):continue
            for comp in (safe(m,'compositions',[]) or []):
                agents=safe(comp,'agents',[]) or []
                if len(agents)!=5:continue
                rows.append(dict(map_name=m.map_name,agents=' • '.join(sorted(agents)),
                    games=safe(comp,'games_played'),wins=safe(comp,'wins'),
                    losses=safe(comp,'losses'),wr=safe(comp,'win_rate')))
        return rows

    def details(self, match_id, include_advanced=True, on_maps=None, on_vetoes=None):
        series = self.client.series(match_id)
        with timed(f'API: série {match_id} - placares/mapas'):
            info = series.info()
        t1=safe(info,'team1'); t2=safe(info,'team2')
        if safe(t1,'id')==TEAM_ID:
            loud_is_first=True
        elif safe(t2,'id')==TEAM_ID:
            loud_is_first=False
        else:
            raise ValueError(f'Partida {match_id} não pertence à LOUD ({TEAM_ID})')
        maps=[]; stats=[]; warnings=[]
        # Veto real obtido de series.info().veto, jamais inferido.
        loud = t1 if loud_is_first else t2
        opp = t2 if loud_is_first else t1
        loud_names={str(safe(loud,k,'')).casefold() for k in ('name','tag')}
        opp_names={str(safe(opp,k,'')).casefold() for k in ('name','tag')}
        vetoes=[]
        for index,v in enumerate(safe(info,'veto',[]) or [],1):
            name=safe(v,'map_name'); action=safe(v,'veto_type'); team=safe(v,'team')
            if not name or not action:continue
            who=str(team or '').strip().casefold()
            by=1 if who in loud_names else 0 if who in opp_names else None
            vetoes.append(dict(index=index,map_name=name,action=str(action).casefold(),
                               team_name=team,by_loud=by))
        if on_vetoes and vetoes:on_vetoes(vetoes)
        games_to_load=[]
        for index, game in enumerate(safe(info,'games',[]) or [],1):
            if not safe(game,'played',False):
                continue
            score_l=safe(game,'team1_score') if loud_is_first else safe(game,'team2_score')
            score_o=safe(game,'team2_score') if loud_is_first else safe(game,'team1_score')
            if score_l is None or score_o is None:
                continue
            gi=safe(game,'order') or index
            gid=safe(game,'game_id') or gi
            maps.append(dict(match_id=int(match_id),map_index=int(gi),game_id=int(gid),
                map_name=safe(game,'map_name') or 'Não informado',
                loud_rounds=score_l,opponent_rounds=score_o,
                attack_rounds=safe(game,'team1_attack_rounds') if loud_is_first else safe(game,'team2_attack_rounds'),
                defense_rounds=safe(game,'team1_defense_rounds') if loud_is_first else safe(game,'team2_defense_rounds')))
            games_to_load.append((gi,gid))
        # O dashboard recebe o placar dos mapas antes das consultas individuais.
        if on_maps is not None and maps:
            on_maps(maps, safe(info, 'event_id'))
        for gi, gid in games_to_load:
            try:
                with timed(f"API: série {match_id} - jogadores mapa {gi}"):
                    page=series.players(game_id=gid)
                teams=[safe(page,'team1'),safe(page,'team2')]
                ours=next((t for t in teams if safe(t,'team_id')==TEAM_ID),None)
                if ours is None:
                    ours=next((t for t in teams if str(safe(t,'team_name','')).casefold()=='loud'),None)
                if ours is None:
                    warnings.append(f'Mapa {gi}: time não identificado no placar')
                    continue
                p_records=[]
                for p in (safe(ours,'players',[]) or []):
                    if not safe(p,'player_id') or not safe(p,'name'):
                        continue
                    overall=safe(safe(p,'stats'),'overall')
                    agent_list=safe(p,'agents',[]) or []
                    vals={key:safe(overall,field) for key,field in {
                        'kills':'kills','deaths':'deaths','assists':'assists','acs':'acs',
                        'adr':'adr','kast':'kast','hs':'hs_percent','rating':'rating',
                        'fk':'first_kills','fd':'first_deaths'}.items()}
                    p_records.append(dict(match_id=int(match_id),map_index=int(gi),
                        player_id=int(p.player_id),agent=', '.join(agent_list) or None,
                        **vals, two_k=None,three_k=None,four_k=None,five_k=None,
                        clutches=None,plants=None,defuses=None,economy=None,
                        source=SOURCE,player=dict(id=int(p.player_id),nickname=p.name,
                            country=safe(p,'country') or safe(p,'country_code'),real_name=None)))
                # Dados avançados são opcionais, nunca substituem o placar principal.
                if p_records and include_advanced:
                    try:
                        with timed(f"API: série {match_id} - avançados mapa {gi}"):
                            perf=series.performance(game_id=gid)
                        advanced=safe(perf,'adv_stats',[]) or []
                        for st in p_records:
                            p=st['player']
                            ad=next((a for a in advanced if safe(a,'player_id')==p['id']),None)
                            if ad is None:
                                ad=next((a for a in advanced if str(safe(a,'name','')).casefold()==p['nickname'].casefold()),None)
                            if ad is not None:
                                for target,field in [('two_k','two_k'),('three_k','three_k'),
                                    ('four_k','four_k'),('five_k','five_k'),('plants','plants'),
                                    ('defuses','defuses'),('economy','economy')]:
                                    st[target]=safe(ad,field)
                                clutch_vals=[safe(ad,f) for f in ('one_v1','one_v2','one_v3','one_v4','one_v5')]
                                st['clutches']=sum(clutch_vals) if all(v is not None for v in clutch_vals) else None
                    except Exception as exc:
                        warnings.append(f'Mapa {gi}: estatísticas avançadas indisponíveis: {exc}')
                stats.extend(p_records)
            except Exception as exc:
                warnings.append(f'Mapa {gi}: estatísticas individuais indisponíveis: {exc}')
        return maps,stats,safe(info,'event_id'),warnings
