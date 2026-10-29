"""Coleta avançada POR DEMANDA de cada Champions.

Usa exclusivamente métodos documentados da VLRdevAPI. Nenhuma coleta ocorre
na inicialização da GUI. Cada série é persistida imediatamente no cache.
"""
import logging
from api.champions import EVENTS
from api.client import safe

LOG=logging.getLogger(__name__)


def _count(value):
    try:return int(value) if value is not None else None
    except (TypeError,ValueError):return None


def fetch_world_series(db,year,on_progress=None,client_factory=None):
    if client_factory is None:
        from vlrdevapi import VLRClient
        client_factory=VLRClient
    event_id=EVENTS[year]
    result={'found':0,'saved':0,'errors':0,'skipped':0}
    with client_factory(timeout=7,max_retries=0,requests_per_second=2) as client:
        page=client.event(event_id).matches(state='completed')
        matches=list(safe(page,'matches',[]) or [])
        ids=list(dict.fromkeys(int(safe(m,'match_id')) for m in matches if safe(m,'match_id')))
        result['found']=len(ids)
        for ix,mid in enumerate(ids,1):
            if db.world_series_cached(event_id,mid):
                result['skipped']+=1;continue
            if on_progress:on_progress(f'Champions {year}: série {ix}/{len(ids)} (ID {mid})')
            try:
                series=client.series(mid)
                info=series.info()
                t1=safe(info,'team1');t2=safe(info,'team2')
                a=safe(t1,'id');b=safe(t2,'id')
                if not a or not b:raise ValueError('IDs de equipes ausentes')
                teamrows=[];side_rows=[];roundrows=[];agentrows=[]
                for idx,game in enumerate(safe(info,'games',[]) or [],1):
                    if not safe(game,'played'):continue
                    gid=safe(game,'game_id') or safe(game,'order') or idx
                    name=safe(game,'map_name') or 'N/D'
                    # Campos teamX_attack_rounds são vitórias de rounds naquele lado.
                    # Derrotas ataque time1 = vitórias defesa time2 e vice-versa.
                    aw1=safe(game,'team1_attack_rounds');dw1=safe(game,'team1_defense_rounds')
                    aw2=safe(game,'team2_attack_rounds');dw2=safe(game,'team2_defense_rounds')
                    for tid,t,atk,def_,atk_opp,def_opp,score,score_opp in (
                        (a,t1,aw1,dw1,aw2,dw2,safe(game,'team1_score'),safe(game,'team2_score')),
                        (b,t2,aw2,dw2,aw1,dw1,safe(game,'team2_score'),safe(game,'team1_score'))):
                        teamrows.append(dict(event_id=event_id,match_id=mid,game_id=gid,
                            team_id=int(tid),team_name=safe(t,'name') or str(tid),map_name=name,
                            rounds_won=score,rounds_lost=score_opp,attack_won=atk,
                            attack_lost=def_opp,defense_won=def_,defense_lost=atk_opp))
                    # Falhas de uma aba do mapa não eliminam os placares já disponíveis.
                    try:
                        p=series.players(game_id=gid)
                        for team,tid in ((safe(p,'team1'),a),(safe(p,'team2'),b)):
                            if team is None:continue
                            for player in (safe(team,'players',[]) or []):
                                pid=safe(player,'player_id')
                                if not pid:continue
                                agents=safe(player,'agents',[]) or []
                                if len(agents)==1 and agents[0]:
                                    agentrows.append(dict(event_id=event_id,match_id=mid,
                                        game_id=gid,player_id=int(pid),agent=agents[0],
                                        team_name=safe(team,'team_name') or '',map_name=name))
                                stats=safe(player,'stats')
                                for side,field,played in (
                                    ('Ataque','attack',next((r['attack_won']+r['attack_lost'] for r in teamrows
                                          if r['team_id']==tid and r['game_id']==gid and
                                            r['attack_won'] is not None and r['attack_lost'] is not None),None)),
                                    ('Defesa','defend',next((r['defense_won']+r['defense_lost'] for r in teamrows
                                          if r['team_id']==tid and r['game_id']==gid and
                                            r['defense_won'] is not None and r['defense_lost'] is not None),None))):
                                    st=safe(stats,field)
                                    if st is None:continue
                                    side_rows.append(dict(event_id=event_id,match_id=mid,game_id=gid,
                                        player_id=int(pid),player=safe(player,'name') or str(pid),
                                        team_id=int(tid),team_name=safe(team,'team_name') or '',
                                        side=side,rounds=played,kills=safe(st,'kills'),deaths=safe(st,'deaths'),
                                        assists=safe(st,'assists'),fk=safe(st,'first_kills'),
                                        fd=safe(st,'first_deaths'),acs=safe(st,'acs'),adr=safe(st,'adr')))
                    except Exception as exc:
                        LOG.warning('Sem dados individuais Champions %s/%s: %s',mid,gid,exc)
                    try:
                        rounds=series.rounds(game_id=gid)
                        for r in (safe(rounds,'rounds',[]) or []):
                            rn=safe(r,'round_number')
                            if rn is None:continue
                            winner=safe(r,'winner_team_id')
                            if winner is None:
                                winnername=str(safe(r,'winner_team_name') or '').casefold()
                                winner=a if winnername==str(safe(t1,'name','')).casefold() else (
                                    b if winnername==str(safe(t2,'name','')).casefold() else None)
                            roundrows.append(dict(event_id=event_id,match_id=mid,game_id=gid,
                                                  round_number=int(rn),winner_team_id=winner,
                                                  team1_id=a,team2_id=b))
                    except Exception as exc:
                        LOG.warning('Sem rounds Champions %s/%s: %s',mid,gid,exc)
                if not teamrows:raise ValueError('Série sem mapas concluídos')
                db.save_world_series(event_id,mid,teamrows,side_rows,roundrows,agentrows)
                result['saved']+=1
            except Exception as exc:
                LOG.exception('Série Champions %s não foi salva: %s',mid,exc)
                result['errors']+=1
    return result
