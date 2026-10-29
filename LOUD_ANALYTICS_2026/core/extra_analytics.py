"""Análises adicionais, calculadas apenas com registros comprovados."""
import pandas as pd
import numpy as np
from core.agent_roles import role_of
from core.analytics import weighted_mean


def compositions(players, maps):
    """Composições por mapa; exige cinco jogadores *distintos*, com um agente cada."""
    cols=['Mapa','Composição','Jogos','Vitórias','WR %','Partidas (IDs)']
    if players.empty or maps.empty:
        return pd.DataFrame(columns=cols)
    rows=[]
    for (match_id,map_index),g in players.groupby(['match_id','map_index']):
        g=g.drop_duplicates(subset=['player_id'])
        if len(g)!=5 or g.agent.isna().any() or any(',' in str(x) for x in g.agent):
            continue
        agents=sorted(str(a).strip() for a in g.agent)
        if len(set(agents))!=5:
            continue
        m=maps[(maps.match_id==match_id)&(maps.map_index==map_index)]
        if len(m)!=1:
            continue
        maprow=m.iloc[0]
        won=np.nan
        if pd.notna(maprow.loud_rounds) and pd.notna(maprow.opponent_rounds):
            won=int(maprow.loud_rounds>maprow.opponent_rounds)
        rows.append({'Mapa':maprow.map_name,'Composição':' • '.join(agents),'id':int(match_id),'won':won})
    if not rows:
        return pd.DataFrame(columns=cols)
    d=pd.DataFrame(rows)
    result=[]
    for (map_name,comp),g in d.groupby(['Mapa','Composição']):
        valid=g.won.dropna()
        result.append({'Mapa':map_name,'Composição':comp,'Jogos':len(g),
                       'Vitórias':int(valid.sum()) if len(valid)==len(g) else np.nan,
                       'WR %':round(valid.mean()*100,1) if len(valid)==len(g) else np.nan,
                       'Partidas (IDs)':', '.join(str(n) for n in sorted(g.id.unique()))})
    return pd.DataFrame(result,columns=cols).sort_values(['Jogos','Mapa'],ascending=[False,True])


def veto_summary(veto_df):
    cols=['Mapa','Bans LOUD','Bans adversário','Picks LOUD','Picks adversário']
    if veto_df.empty:return pd.DataFrame(columns=cols)
    result=[]
    for name,g in veto_df.groupby('map_name'):
        action=g.action.fillna('').str.lower()
        yours=g.by_loud.eq(1)
        theirs=g.by_loud.eq(0)
        result.append({'Mapa':name,'Bans LOUD':int((action.isin(['ban','banned']) & yours).sum()),
                       'Bans adversário':int((action.isin(['ban','banned']) & theirs).sum()),
                       'Picks LOUD':int((action.isin(['pick','picked']) & yours).sum()),
                       'Picks adversário':int((action.isin(['pick','picked']) & theirs).sum())})
    return pd.DataFrame(result,columns=cols).sort_values('Bans LOUD',ascending=False)


def local_records(summary):
    cols=['Recorde no recorte disponível','Jogador','Valor','Abrangência']
    if summary.empty:return pd.DataFrame(columns=cols)
    rows=[]
    for name,key in [('Maior número de kills','Kills'),('Mais assistências','Assists'),
                     ('Mais 2K','2K'),('Mais 3K','3K'),('Mais 4K','4K'),
                     ('Mais aces','Aces'),('Mais clutches','Clutches'),
                     ('Maior ACS médio','ACS'),('Mais first kills','FK')]:
        d=summary.dropna(subset=[key])
        if d.empty:continue
        leader=d.sort_values(key,ascending=False).iloc[0]
        rows.append({'Recorde no recorte disponível':name,'Jogador':leader['Jogador'],
                     'Valor':leader[key],'Abrangência':f"{int(leader['Mapas'])} mapas salvos"})
    return pd.DataFrame(rows,columns=cols)
