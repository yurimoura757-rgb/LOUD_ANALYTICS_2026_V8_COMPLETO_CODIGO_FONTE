"""Rankings por edição dos Champions, calculados apenas a partir da coleta profunda."""
import numpy as np
import pandas as pd


def teams_summary(df):
    cols=['Time','Mapas','Rounds ganhos','Rounds perdidos','Ataque ganhos','Ataque perdidos',
          'Defesa ganhos','Defesa perdidos']
    if df.empty:return pd.DataFrame(columns=cols)
    rec=[]
    for name,g in df.groupby('team_name'):
        row={'Time':name,'Mapas':len(g)}
        for dst,src in zip(cols[2:],['rounds_won','rounds_lost','attack_won','attack_lost',
                                    'defense_won','defense_lost']):
            v=g[src]
            row[dst]=int(v.sum()) if v.notna().all() else np.nan
        rec.append(row)
    return pd.DataFrame(rec,columns=cols).sort_values('Rounds ganhos',ascending=False)


def pistol_summary(teams,rounds):
    cols=['Time','Rounds pistol vencidos','Pistols disputados','Pistol WR %',
          '2º round vencido','2º round disputado','2º round WR %',
          'Conversões pistol → 2º round','Pistols vencidos com 2º round conhecido','Conversão %']
    if teams.empty or rounds.empty:return pd.DataFrame(columns=cols)
    lookup={(int(r.event_id),int(r.match_id),int(r.game_id),int(r.round_number)):r.winner_team_id
            for _,r in rounds.iterrows() if pd.notna(r.round_number)}
    rec=[]
    for (tid,name),g in teams.groupby(['team_id','team_name']):
        out={'Time':name,'Rounds pistol vencidos':0,'Pistols disputados':0,
             '2º round vencido':0,'2º round disputado':0,
             'Conversões pistol → 2º round':0,'Pistols vencidos com 2º round conhecido':0}
        for _,r in g.iterrows():
            for pistol,next_round in [(1,2),(13,14)]:
                k=(int(r.event_id),int(r.match_id),int(r.game_id))
                w=lookup.get(k+(pistol,)); wn=lookup.get(k+(next_round,))
                if w is not None and pd.notna(w):
                    out['Pistols disputados']+=1
                    if int(w)==int(tid):
                        out['Rounds pistol vencidos']+=1
                        if wn is not None and pd.notna(wn):
                            out['Pistols vencidos com 2º round conhecido']+=1
                            out['Conversões pistol → 2º round']+=int(int(wn)==int(tid))
                if wn is not None and pd.notna(wn):
                    out['2º round disputado']+=1
                    out['2º round vencido']+=int(int(wn)==int(tid))
        for pct,num,den in [('Pistol WR %','Rounds pistol vencidos','Pistols disputados'),
                             ('2º round WR %','2º round vencido','2º round disputado'),
                             ('Conversão %','Conversões pistol → 2º round','Pistols vencidos com 2º round conhecido')]:
            out[pct]=round(100*out[num]/out[den],2) if out[den] else np.nan
        rec.append(out)
    return pd.DataFrame(rec,columns=cols).sort_values('Pistols disputados',ascending=False)


def side_rankings(df,side,ranking="ACS"):
    cols=['Posição','Jogador','Equipe','Mapas','Rounds','Kills','Deaths','Assists','K/D','ACS','ADR','First Kills','First Deaths']
    if df.empty:return pd.DataFrame(columns=cols)
    d=df[df.side==side]
    records=[]
    for (pid,name,team),g in d.groupby(['player_id','player','team_name']):
        def total(field):
            return g[field].sum() if g[field].notna().all() else np.nan
        k=total('kills');deaths=total('deaths')
        weights=pd.to_numeric(g.rounds,errors='coerce')
        def weighted(col):
            x=pd.to_numeric(g[col],errors='coerce')
            ok=x.notna()&weights.notna()&(weights>0)
            return np.average(x[ok],weights=weights[ok]) if ok.any() else np.nan
        records.append({'Jogador':name,'Equipe':team,'Mapas':len(g),
             'Rounds':total('rounds'),'Kills':k,'Deaths':deaths,'Assists':total('assists'),
             'K/D':k/deaths if pd.notna(k) and pd.notna(deaths) and deaths else np.nan,
             'ACS':weighted('acs'),'ADR':weighted('adr'),
             'First Kills':total('fk'),'First Deaths':total('fd')})
    out=pd.DataFrame(records)
    key = 'First Kills' if ranking == 'First Kills' else 'ACS'
    out=out.sort_values(key,ascending=False).reset_index(drop=True)
    out.insert(0,'Posição',range(1,len(out)+1))
    return out.reindex(columns=cols)


def agent_top(df):
    cols=['Posição','Agente','Picks (mapas)','Jogadores distintos','Times distintos']
    if df.empty:return pd.DataFrame(columns=cols)
    rows=[]
    for agent,g in df.groupby('agent'):
        rows.append({'Agente':agent,'Picks (mapas)':len(g),
                     'Jogadores distintos':g.player_id.nunique(),
                     'Times distintos':g.team_name.nunique()})
    out=pd.DataFrame(rows).sort_values('Picks (mapas)',ascending=False).head(5).reset_index(drop=True)
    out.insert(0,'Posição',range(1,len(out)+1))
    return out.reindex(columns=cols)
