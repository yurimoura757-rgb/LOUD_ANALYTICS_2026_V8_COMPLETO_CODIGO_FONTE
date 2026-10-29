"""Análises reprodutíveis por DataFrame, sem estatísticas simuladas."""
import numpy as np
import pandas as pd
from config import START, END

MATCH_COLS=['id','date_utc','tournament','stage','bracket','opponent','team_score',
            'opponent_score','won','url','status','details_complete']
MAP_COLS=['match_id','map_index','map_name','loud_rounds','opponent_rounds',
          'attack_rounds','defense_rounds','tournament','opponent','date_utc']
PLAYER_COLS=['match_id','map_index','player_id','nickname','real_name','country',
             'agent','kills','deaths','assists','acs','adr','kast','hs','rating',
             'fk','fd','two_k','three_k','four_k','five_k','clutches','plants',
             'defuses','economy','map_name','loud_rounds','opponent_rounds',
             'tournament','opponent','date_utc','won','rounds','map_won']
COUNT_COLS=['kills','deaths','assists','fk','fd','two_k','three_k','four_k',
            'five_k','clutches','plants','defuses','economy']
RATE_COLS=['acs','adr','kast','hs','rating']


def divide(n,d):
    """Métricas indefinidas são NaN, nunca zero inventado."""
    return float(n)/float(d) if d is not None and pd.notna(d) and d != 0 else np.nan


def weighted_mean(frame,column,weights='rounds'):
    if frame.empty or column not in frame:
        return np.nan
    x=pd.to_numeric(frame[column],errors='coerce')
    w=pd.to_numeric(frame[weights],errors='coerce')
    mask=x.notna() & w.notna() & (w>0)
    return float(np.average(x[mask],weights=w[mask])) if mask.any() else np.nan


def filtered(df, tournament='', opponent='', map_name='', agent='', start='', end=''):
    if df.empty:
        return df.copy()
    out=df.copy()
    for col,val in [('tournament',tournament),('opponent',opponent),('map_name',map_name),('agent',agent)]:
        if val and val!='Todos' and col in out:
            out=out[out[col].fillna('').astype(str).str.casefold()==val.casefold()]
    if 'date_utc' in out:
        if start:
            out=out[out['date_utc'].fillna('').str[:10]>=start]
        if end:
            out=out[out['date_utc'].fillna('').str[:10]<=end]
    return out.copy()


class Analytics:
    def __init__(self,db):
        self.db=db
        self._snapshot={}

    def invalidate(self):
        """Atualização do banco invalida as consultas, mantendo filtros rápidos."""
        self._snapshot.clear()

    def _cached(self, name, loader):
        if name not in self._snapshot:
            self._snapshot[name]=loader()
        return self._snapshot[name]

    def matches(self):
        return self._cached('matches', self._load_matches)

    def _load_matches(self):
        df=self.db.frame('''SELECT id,date_utc,tournament,stage,bracket,opponent,
              team_score,opponent_score,won,url,status,details_complete
              FROM matches WHERE substr(date_utc,1,4)='2026' ORDER BY date_utc DESC''')
        return df.reindex(columns=MATCH_COLS)

    def maps(self):
        return self._cached('maps', self._load_maps)

    def _load_maps(self):
        df=self.db.frame('''SELECT mm.match_id, mm.map_index, mm.map_name, mm.loud_rounds,
              mm.opponent_rounds, mm.attack_rounds,mm.defense_rounds,
              m.tournament,m.opponent,m.date_utc
              FROM match_maps mm JOIN matches m ON m.id=mm.match_id
              WHERE m.status='completed' AND substr(m.date_utc,1,4)='2026'
              ORDER BY m.date_utc,mm.map_index''')
        return df.reindex(columns=MAP_COLS)

    def players(self):
        return self._cached('players', self._load_players)

    def _load_players(self):
        df=self.db.frame('''SELECT s.match_id,s.map_index,s.player_id,p.nickname,p.real_name,
              p.country,s.agent,s.kills,s.deaths,s.assists,s.acs,s.adr,s.kast,s.hs,
              s.rating,s.fk,s.fd,s.two_k,s.three_k,s.four_k,s.five_k,
              s.clutches,s.plants,s.defuses,s.economy,mm.map_name,
              mm.loud_rounds,mm.opponent_rounds,m.tournament,m.opponent,m.date_utc,m.won
              FROM player_map_stats s JOIN players p ON p.id=s.player_id
              JOIN match_maps mm ON mm.match_id=s.match_id AND mm.map_index=s.map_index
              JOIN matches m ON m.id=s.match_id
              WHERE m.status='completed' AND substr(m.date_utc,1,4)='2026'
              ORDER BY m.date_utc,s.map_index''')
        if df.empty:
            return pd.DataFrame(columns=PLAYER_COLS)
        for col in COUNT_COLS+RATE_COLS+['loud_rounds','opponent_rounds']:
            df[col]=pd.to_numeric(df[col],errors='coerce')
        df['rounds']=df['loud_rounds']+df['opponent_rounds']
        df['map_won']=(df['loud_rounds']>df['opponent_rounds']).astype(int)
        return df.reindex(columns=PLAYER_COLS)

    def overview(self,df=None,maps=None):
        if df is None:
            df=self.matches()
        df=df[df['status']=='completed'] if not df.empty else df
        total=len(df)
        wins=int((df['won']==1).sum()) if total else 0
        losses=int((df['won']==0).sum()) if total else 0
        if maps is None:
            maps=self.maps()
        if not df.empty:
            maps=maps[maps.match_id.isin(df.id)]
        return {'partidas':total,'vitórias':wins,'derrotas':losses,
            'win_rate':divide(wins*100,wins+losses),'mapas':len(maps),
            'mapas_vencidos':int((maps.loud_rounds>maps.opponent_rounds).sum()) if len(maps) else 0,
            'round_diff':int((maps.loud_rounds-maps.opponent_rounds).sum()) if len(maps) else 0}

    @staticmethod
    def player_summary(df):
        """1 linha por jogador. Contagens omitidas se houver pelo menos um valor nulo."""
        columns=['Jogador','ID','Partidas','Mapas','Rounds','Vitórias mapas','WR mapas %',
                 'Kills','Deaths','Assists','K/D','KDA','ACS','ADR','KAST %','HS %',
                 'Rating VLR','FK','FD','FK diff','2K','3K','4K','Aces','Clutches',
                 'Agente mais usado','Desvio ACS']
        if df.empty:
            return pd.DataFrame(columns=columns)
        records=[]
        for pid,g in df.groupby('player_id',sort=False):
            def count(col):
                return int(g[col].sum()) if g[col].notna().all() else np.nan
            k,d,a=count('kills'),count('deaths'),count('assists')
            fk,fd=count('fk'),count('fd')
            agents=g.agent.dropna()
            common=agents.value_counts().index[0] if not agents.empty else 'N/D'
            records.append({'Jogador':g.nickname.iloc[-1],'ID':int(pid),
                'Partidas':int(g.match_id.nunique()),'Mapas':len(g),
                'Rounds':int(g.rounds.sum()) if g.rounds.notna().all() else np.nan,
                'Vitórias mapas':int(g.map_won.sum()),'WR mapas %':round(100*g.map_won.mean(),2),
                'Kills':k,'Deaths':d,'Assists':a,'K/D':divide(k,d),
                'KDA':divide(k+a,d) if pd.notna(k) and pd.notna(a) else np.nan,
                'ACS':weighted_mean(g,'acs'),'ADR':weighted_mean(g,'adr'),
                'KAST %':weighted_mean(g,'kast'),
                'HS %':g.hs.mean() if g.hs.notna().all() else np.nan,
                'Rating VLR':weighted_mean(g,'rating'),
                'FK':fk,'FD':fd,'FK diff':fk-fd if pd.notna(fk) and pd.notna(fd) else np.nan,
                '2K':count('two_k'),'3K':count('three_k'),'4K':count('four_k'),
                'Aces':count('five_k'),'Clutches':count('clutches'),
                'Agente mais usado':common,
                'Desvio ACS':g.acs.std(ddof=1) if g.acs.notna().all() and len(g)>1 else np.nan})
        return pd.DataFrame(records,columns=columns).sort_values('Mapas',ascending=False)

    @staticmethod
    def maps_summary(df):
        columns=['Mapa','Jogos','Vitórias','Derrotas','WR %','Saldo rounds',
                 'Rounds vencidos','Rounds perdidos']
        if df.empty:
            return pd.DataFrame(columns=columns)
        records=[]
        for name,g in df.groupby('map_name'):
            # Uma pontuação desconhecida NÃO é uma derrota.
            known=g.dropna(subset=['loud_rounds','opponent_rounds'])
            if known.empty:
                records.append({'Mapa':name,'Jogos':len(g),'Vitórias':0,
                    'Derrotas':0,'WR %':np.nan,'Saldo rounds':np.nan,
                    'Rounds vencidos':np.nan,'Rounds perdidos':np.nan})
                continue
            w=int((known.loud_rounds>known.opponent_rounds).sum())
            records.append({'Mapa':name,'Jogos':len(g),'Vitórias':w,
                'Derrotas':len(known)-w,'WR %':divide(100*w,len(known)),
                'Saldo rounds':int((known.loud_rounds-known.opponent_rounds).sum()),
                'Rounds vencidos':int(known.loud_rounds.sum()),
                'Rounds perdidos':int(known.opponent_rounds.sum())})
        return pd.DataFrame(records,columns=columns).sort_values('Jogos',ascending=False)

    @staticmethod
    def tournament_summary(df):
        columns=['Campeonato','Partidas','Vitórias','Derrotas','WR %']
        if df.empty:
            return pd.DataFrame(columns=columns)
        rows=[]
        for name,g in df[df.status=='completed'].groupby('tournament'):
            wins=int((g.won==1).sum())
            rows.append({'Campeonato':name,'Partidas':len(g),'Vitórias':wins,
                         'Derrotas':int((g.won==0).sum()),'WR %':divide(100*wins,len(g))})
        return pd.DataFrame(rows,columns=columns).sort_values('Partidas',ascending=False)

    @staticmethod
    def agents_summary(df):
        columns=['Agente','Jogador','Mapas','Vitórias','WR %','K/D','ACS','ADR','KAST %']
        if df.empty:
            return pd.DataFrame(columns=columns)
        records=[]
        for (agent,player),g in df.dropna(subset=['agent']).groupby(['agent','nickname']):
            k=g.kills.sum(min_count=len(g)); d=g.deaths.sum(min_count=len(g))
            records.append({'Agente':agent,'Jogador':player,'Mapas':len(g),
                'Vitórias':int(g.map_won.sum()),'WR %':g.map_won.mean()*100,
                'K/D':divide(k,d),'ACS':weighted_mean(g,'acs'),
                'ADR':weighted_mean(g,'adr'),'KAST %':weighted_mean(g,'kast')})
        return pd.DataFrame(records,columns=columns).sort_values('Mapas',ascending=False)

    @staticmethod
    def evolution(df):
        if df.empty:
            return pd.DataFrame(columns=['data','Jogador','ACS','K/D'])
        d=df.copy()
        d['data']=d.date_utc.str[:10]
        records=[]
        for (day,pid),g in d.groupby(['data','player_id']):
            k=g.kills.sum(min_count=len(g)); deaths=g.deaths.sum(min_count=len(g))
            records.append({'data':day,'Jogador':g.nickname.iloc[0],
                    'ACS':weighted_mean(g,'acs'),'K/D':divide(k,deaths)})
        return pd.DataFrame(records).sort_values('data')

    @staticmethod
    def streaks(df):
        if df.empty:
            return (0,0)
        df=df[(df.status=='completed') & df.won.isin([0,1])].sort_values('date_utc')
        best_w=best_l=current_w=current_l=0
        for x in df.won:
            if x==1:
                current_w+=1;current_l=0
            else:
                current_l+=1;current_w=0
            best_w=max(best_w,current_w);best_l=max(best_l,current_l)
        return best_w,best_l
