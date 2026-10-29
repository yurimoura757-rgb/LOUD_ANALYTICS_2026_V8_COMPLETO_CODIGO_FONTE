"""Camada SQLite: registros idempotentes, SQL parametrizado e conexões curtas."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from config import DB_PATH, SOURCE, TEAM_ID

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tournaments(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS matches(
 id INTEGER PRIMARY KEY, date_utc TEXT, tournament_id INTEGER REFERENCES tournaments(id),
 tournament TEXT, stage TEXT, bracket TEXT, opponent_id INTEGER,
 opponent TEXT, team_score INTEGER, opponent_score INTEGER,
 won INTEGER CHECK(won IN (0,1) OR won IS NULL), url TEXT, status TEXT NOT NULL DEFAULT 'completed',
 details_complete INTEGER NOT NULL DEFAULT 0, updated_utc TEXT NOT NULL,
 details_attempted_utc TEXT, advanced_attempted_utc TEXT,
 source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS match_maps(
 match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
 map_index INTEGER NOT NULL, game_id INTEGER, map_name TEXT NOT NULL,
 loud_rounds INTEGER, opponent_rounds INTEGER, attack_rounds INTEGER, defense_rounds INTEGER,
 PRIMARY KEY(match_id,map_index));
CREATE TABLE IF NOT EXISTS players(
 id INTEGER PRIMARY KEY, nickname TEXT NOT NULL,
 real_name TEXT, country TEXT, roster_status TEXT, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS roster_transactions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL REFERENCES players(id),
 transaction_date TEXT, action TEXT NOT NULL, position TEXT, source_url TEXT,
 UNIQUE(player_id,transaction_date,action,position));
CREATE TABLE IF NOT EXISTS player_map_stats(
 match_id INTEGER NOT NULL, map_index INTEGER NOT NULL,
 player_id INTEGER NOT NULL REFERENCES players(id),
 agent TEXT, kills INTEGER, deaths INTEGER, assists INTEGER,
 acs REAL, adr REAL, kast REAL, hs REAL, rating REAL,
 fk INTEGER, fd INTEGER, two_k INTEGER, three_k INTEGER,
 four_k INTEGER, five_k INTEGER, clutches INTEGER, plants INTEGER,
 defuses INTEGER, economy INTEGER,
 source TEXT NOT NULL,
 PRIMARY KEY(match_id,map_index,player_id),
 FOREIGN KEY(match_id,map_index) REFERENCES match_maps(match_id,map_index) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS world_series_done(
 event_id INTEGER NOT NULL,match_id INTEGER NOT NULL,
 completed_utc TEXT NOT NULL, PRIMARY KEY(event_id,match_id));
CREATE TABLE IF NOT EXISTS world_team_maps(
 event_id INTEGER,match_id INTEGER,game_id INTEGER,team_id INTEGER,team_name TEXT,
 map_name TEXT,rounds_won INTEGER,rounds_lost INTEGER,
 attack_won INTEGER,attack_lost INTEGER,defense_won INTEGER,defense_lost INTEGER,
 PRIMARY KEY(event_id,match_id,game_id,team_id));
CREATE TABLE IF NOT EXISTS world_side_players(
 event_id INTEGER,match_id INTEGER,game_id INTEGER,player_id INTEGER,player TEXT,
 team_id INTEGER,team_name TEXT,side TEXT,rounds INTEGER,kills INTEGER,deaths INTEGER,
 assists INTEGER,fk INTEGER,fd INTEGER,acs REAL,adr REAL,
 PRIMARY KEY(event_id,match_id,game_id,player_id,side));
CREATE TABLE IF NOT EXISTS world_rounds(
 event_id INTEGER,match_id INTEGER,game_id INTEGER,round_number INTEGER,
 winner_team_id INTEGER,team1_id INTEGER,team2_id INTEGER,
 PRIMARY KEY(event_id,match_id,game_id,round_number));
CREATE TABLE IF NOT EXISTS world_agent_picks(
 event_id INTEGER,match_id INTEGER,game_id INTEGER,player_id INTEGER,
 agent TEXT,team_name TEXT,map_name TEXT,
 PRIMARY KEY(event_id,match_id,game_id,player_id));
CREATE TABLE IF NOT EXISTS team_compositions(
 map_name TEXT NOT NULL, agents TEXT NOT NULL, games INTEGER,
 wins INTEGER, losses INTEGER, wr REAL, fetched_utc TEXT NOT NULL,
 PRIMARY KEY(map_name,agents));
CREATE TABLE IF NOT EXISTS map_vetoes(
 match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
 veto_index INTEGER NOT NULL, map_name TEXT NOT NULL,
 action TEXT NOT NULL, team_name TEXT,
 by_loud INTEGER CHECK(by_loud IN (0,1) OR by_loud IS NULL),
 PRIMARY KEY(match_id,veto_index));
CREATE TABLE IF NOT EXISTS champions_players(
 event_id INTEGER NOT NULL, year INTEGER NOT NULL, player TEXT NOT NULL,
 team TEXT NOT NULL DEFAULT '', agent TEXT NOT NULL DEFAULT 'Todos',
 maps INTEGER, rounds INTEGER, rating REAL, acs REAL, kd REAL, kast REAL, hs REAL,
 adr REAL, kills INTEGER, deaths INTEGER, assists INTEGER, fk INTEGER,
 fd INTEGER, clutches INTEGER, clutch_attempts INTEGER,
 source_url TEXT NOT NULL, fetched_utc TEXT NOT NULL,
 PRIMARY KEY(event_id,player,team,agent));
CREATE TABLE IF NOT EXISTS champions_snapshots(
 event_id INTEGER NOT NULL, agent TEXT NOT NULL DEFAULT 'Todos',
 fetched_utc TEXT NOT NULL, PRIMARY KEY(event_id,agent));
CREATE TABLE IF NOT EXISTS sync_state(
 key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS update_logs(
 id INTEGER PRIMARY KEY AUTOINCREMENT, started_utc TEXT NOT NULL,
 ended_utc TEXT, found INTEGER DEFAULT 0, processed INTEGER DEFAULT 0,
 errors INTEGER DEFAULT 0, status TEXT, message TEXT);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date_utc);
CREATE INDEX IF NOT EXISTS idx_pms_player ON player_map_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_pms_agent ON player_map_stats(agent);
'''

class Database:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        self.initialize()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=5000')
        con.execute('PRAGMA synchronous=NORMAL')
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self):
        with self.connect() as con:
            # WAL permite consultar os dados locais durante uma atualização em background.
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('PRAGMA synchronous=NORMAL')
            con.executescript(SCHEMA)
            fields = {r[1] for r in con.execute('PRAGMA table_info(matches)')}
            if 'details_attempted_utc' not in fields:
                con.execute('ALTER TABLE matches ADD COLUMN details_attempted_utc TEXT')
            champ_fields={r[1] for r in con.execute('PRAGMA table_info(champions_players)')}
            if 'hs' not in champ_fields:
                con.execute('ALTER TABLE champions_players ADD COLUMN hs REAL')
            if 'advanced_attempted_utc' not in fields:
                con.execute('ALTER TABLE matches ADD COLUMN advanced_attempted_utc TEXT')
            con.execute('INSERT OR IGNORE INTO teams(id,name) VALUES(?,?)', (TEAM_ID,'LOUD'))

    def frame(self, sql, params=()):
        import pandas as pd
        with self.connect() as con:
            rows = [dict(r) for r in con.execute(sql, params)]
        return pd.DataFrame.from_records(rows)

    def scalar(self, sql, params=(), default=None):
        with self.connect() as con:
            row = con.execute(sql, params).fetchone()
            return row[0] if row else default

    def known_match_ids(self):
        with self.connect() as con:
            return {int(r[0]) for r in con.execute("SELECT id FROM matches WHERE details_complete=1")}

    def pending_match_ids(self, retry_hours=24):
        """Incompletas ainda elegíveis; não insiste em erros a cada abertura."""
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(hours=retry_hours)).isoformat()
        with self.connect() as con:
            return [int(r[0]) for r in con.execute('''SELECT id FROM matches
                WHERE status='completed' AND details_complete=0
                  AND date_utc>='2026-01-01' AND date_utc<'2027-01-01'
                  AND (details_attempted_utc IS NULL OR details_attempted_utc < ?)
                ORDER BY date_utc DESC''', (since,))]

    def mark_detail_attempt(self, match_id):
        with self.connect() as con:
            con.execute('UPDATE matches SET details_attempted_utc=? WHERE id=?',
                (datetime.now(timezone.utc).isoformat(), match_id))

    def save_match_list(self, matches):
        """Garante unicidade sem regravar registros iguais."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            before=con.total_changes
            for m in matches:
                if not m.get('id'):
                    continue
                con.execute('''INSERT INTO matches(id,date_utc,tournament,stage,bracket,
                        opponent_id,opponent,team_score,opponent_score,won,url,status,updated_utc,source)
                    VALUES(:id,:date_utc,:tournament,:stage,:bracket,:opponent_id,:opponent,
                           :team_score,:opponent_score,:won,:url,:status,:updated_utc,:source)
                    ON CONFLICT(id) DO UPDATE SET date_utc=excluded.date_utc,
                    tournament=excluded.tournament,stage=excluded.stage,bracket=excluded.bracket,
                    opponent_id=excluded.opponent_id,opponent=excluded.opponent,
                    team_score=excluded.team_score,opponent_score=excluded.opponent_score,
                    won=excluded.won,url=excluded.url,status=excluded.status,
                    updated_utc=excluded.updated_utc
                    WHERE matches.date_utc IS NOT excluded.date_utc
                      OR matches.tournament IS NOT excluded.tournament
                      OR matches.stage IS NOT excluded.stage
                      OR matches.bracket IS NOT excluded.bracket
                      OR matches.opponent_id IS NOT excluded.opponent_id
                      OR matches.opponent IS NOT excluded.opponent
                      OR matches.team_score IS NOT excluded.team_score
                      OR matches.opponent_score IS NOT excluded.opponent_score
                      OR matches.won IS NOT excluded.won
                      OR matches.url IS NOT excluded.url
                      OR matches.status IS NOT excluded.status''', dict(m, updated_utc=now, source=SOURCE))
            return con.total_changes-before

    def save_players(self, players, roster_status=None):
        with self.connect() as con:
            for p in players:
                if not p.get('id') or not p.get('nickname'):
                    continue
                con.execute('''INSERT INTO players(id,nickname,real_name,country,roster_status,source)
                    VALUES(:id,:nickname,:real_name,:country,:roster_status,:source)
                    ON CONFLICT(id) DO UPDATE SET nickname=excluded.nickname,
                     real_name=COALESCE(excluded.real_name,players.real_name),
                     country=COALESCE(excluded.country,players.country),
                     roster_status=COALESCE(excluded.roster_status,players.roster_status)''',
                    dict(p, roster_status=roster_status, source=SOURCE))

    def save_transactions(self, records):
        with self.connect() as con:
            for x in records:
                con.execute('''INSERT OR IGNORE INTO roster_transactions
                    (player_id,transaction_date,action,position,source_url)
                    VALUES(?,?,?,?,?)''', (x['player_id'],x['date'],x['action'],
                                           x['position'],x['source_url']))

    def save_details(self, match_id, maps, stats, tournament_id=None):
        """Confirma a série somente se existem dados de jogadores para mapas jogados."""
        if not maps:
            return False
        # Preservar placares dos mapas mesmo sem estatísticas individuais.
        # Sem estatísticas, continua elegível para enriquecimento futuro.
        available={s['map_index'] for s in stats}
        complete=bool(stats) and all(m['map_index'] in available for m in maps)
        with self.connect() as con:
            for m in maps:
                con.execute('''INSERT INTO match_maps(match_id,map_index,game_id,map_name,
                    loud_rounds,opponent_rounds,attack_rounds,defense_rounds)
                    VALUES(:match_id,:map_index,:game_id,:map_name,:loud_rounds,
                    :opponent_rounds,:attack_rounds,:defense_rounds)
                    ON CONFLICT(match_id,map_index) DO UPDATE SET
                    game_id=excluded.game_id,map_name=excluded.map_name,
                    loud_rounds=excluded.loud_rounds,opponent_rounds=excluded.opponent_rounds,
                    attack_rounds=excluded.attack_rounds,defense_rounds=excluded.defense_rounds''',m)
            for s in stats:
                p = s['player']
                con.execute('''INSERT INTO players(id,nickname,real_name,country,source)
                    VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    nickname=excluded.nickname,country=COALESCE(excluded.country,players.country)''',
                    (p['id'],p['nickname'],p.get('real_name'),p.get('country'),SOURCE))
                vals = {k:v for k,v in s.items() if k!='player'}
                columns = ','.join(vals)
                marks = ','.join('?' for _ in vals)
                update = ','.join(
                    f'{k}=COALESCE(excluded.{k},player_map_stats.{k})'
                    if k in ('two_k','three_k','four_k','five_k','clutches','plants','defuses','economy')
                    else f'{k}=excluded.{k}'
                    for k in vals if k not in ('match_id','map_index','player_id'))
                con.execute(f'''INSERT INTO player_map_stats({columns}) VALUES({marks})
                                ON CONFLICT(match_id,map_index,player_id) DO UPDATE SET {update}''',tuple(vals.values()))
            if tournament_id:
                con.execute('''INSERT INTO tournaments(id,name)
                  SELECT ?, tournament FROM matches WHERE id=?
                  ON CONFLICT(id) DO NOTHING''',(tournament_id,match_id))
                con.execute('UPDATE matches SET tournament_id=? WHERE id=?',(tournament_id,match_id))
            con.execute('UPDATE matches SET details_complete=? WHERE id=?',(int(complete),match_id))
        return complete

    def get_sync(self, key):
        """Metadados persistidos de atualização, nunca estatísticas simuladas."""
        return self.scalar('SELECT value FROM sync_state WHERE key=?', (key,))

    def set_sync(self, key, value):
        with self.connect() as con:
            con.execute('''INSERT INTO sync_state(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                    (key, str(value)))

    def last_attempt(self):
        return self.scalar('SELECT started_utc FROM update_logs ORDER BY id DESC LIMIT 1')

    def has_history(self):
        return bool(self.scalar("SELECT EXISTS(SELECT 1 FROM matches WHERE status='completed')", default=0))

    def can_retry_empty_cache(self, cooldown_minutes=30):
        """Evita tentar a rede a cada abertura após uma coleta malsucedida.

        Aplica-se somente à primeira coleta automática sem partidas no cache.
        Uma atualização manual ignora esta proteção.
        """
        from datetime import timedelta
        with self.connect() as con:
            row = con.execute('SELECT started_utc,status FROM update_logs '
                              'ORDER BY id DESC LIMIT 1').fetchone()
        if not row or row['status'] == 'completed':
            return True
        try:
            last = datetime.fromisoformat(row['started_utc'])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - last >= timedelta(minutes=cooldown_minutes)
        except (TypeError, ValueError):
            return True


    def log_start(self):
        with self.connect() as con:
            c=con.execute('INSERT INTO update_logs(started_utc,status) VALUES(?,?)',
                          (datetime.now(timezone.utc).isoformat(),'running'))
            return c.lastrowid

    def log_end(self, log_id, found, processed, errors, message):
        with self.connect() as con:
            con.execute('''UPDATE update_logs SET ended_utc=?,found=?,processed=?,errors=?,
                status=?,message=? WHERE id=?''',
                (datetime.now(timezone.utc).isoformat(),found,processed,errors,
                 'completed' if errors==0 else 'partial',message,log_id))

    def save_vetoes(self, match_id, vetoes):
        # Sem apagar vetos anteriores quando uma resposta vem vazia.
        if not vetoes:return
        with self.connect() as con:
            for v in vetoes:
                con.execute('''INSERT INTO map_vetoes
                  (match_id,veto_index,map_name,action,team_name,by_loud)
                  VALUES (?,?,?,?,?,?) ON CONFLICT(match_id,veto_index) DO UPDATE SET
                  map_name=excluded.map_name,action=excluded.action,
                  team_name=excluded.team_name,by_loud=excluded.by_loud''',
                  (int(match_id), v['index'], v['map_name'], v['action'],
                   v.get('team_name'),v.get('by_loud')))

    def save_champions(self, event_id, year, agent, rows, source_url):
        # Snapshot por campeonato/agente; vazios nunca viram cache válido.
        if not rows:raise ValueError('A fonte não forneceu jogadores, nada foi sobrescrito.')
        now=datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            con.execute('DELETE FROM champions_players WHERE event_id=? AND agent=?',(event_id,agent))
            for p in rows:
                val=dict(p,event_id=event_id,year=year,agent=agent,
                         source_url=source_url,fetched_utc=now)
                fields=list(val)
                con.execute(f'INSERT INTO champions_players ({",".join(fields)}) '
                            f'VALUES ({",".join("?" for _ in fields)})',list(val.values()))
            con.execute('''INSERT INTO champions_snapshots(event_id,agent,fetched_utc)
                           VALUES(?,?,?) ON CONFLICT(event_id,agent) DO UPDATE SET
                           fetched_utc=excluded.fetched_utc''',(event_id,agent,now))

    def get_champions(self, event_id, agent='Todos'):
        return self.frame('''SELECT player,team,agent,maps,rounds,rating,acs,kd,kast,hs,adr,
                    kills,deaths,assists,fk,fd,clutches,clutch_attempts,source_url
                    FROM champions_players WHERE event_id=? AND agent=?
                    ORDER BY rounds DESC''',(event_id,agent))

    def champions_cached(self,event_id,agent='Todos'):
        return bool(self.scalar('SELECT EXISTS(SELECT 1 FROM champions_snapshots WHERE event_id=? AND agent=?)',
                                (event_id,agent),default=0))

    def veto_frame(self):
        return self.frame('''SELECT v.*,m.date_utc,m.opponent,m.tournament
              FROM map_vetoes v JOIN matches m ON m.id=v.match_id
              WHERE substr(m.date_utc,1,4)='2026' ORDER BY m.date_utc DESC,v.veto_index''')

    def save_team_compositions(self, rows):
        if not rows:return
        stamp=datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            for r in rows:
                con.execute('''INSERT INTO team_compositions(map_name,agents,games,wins,losses,wr,fetched_utc)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(map_name,agents) DO UPDATE SET
                games=excluded.games,wins=excluded.wins,losses=excluded.losses,
                wr=excluded.wr,fetched_utc=excluded.fetched_utc''',
                (r['map_name'],r['agents'],r['games'],r['wins'],r['losses'],r['wr'],stamp))

    def team_compositions(self):
        return self.frame('''SELECT map_name AS Mapa,agents AS Composição,games AS Jogos,
                          wins AS Vitórias,losses AS Derrotas,wr AS "WR %"
                          FROM team_compositions ORDER BY games DESC,map_name''')

    def pending_advanced_ids(self):
        # Necessário para bases de versões antigas que foram coletadas sem 2K/3K/4K/aces.
        return [int(r['id']) for r in self.frame('''SELECT DISTINCT m.id
           FROM matches m JOIN player_map_stats s ON s.match_id=m.id
           WHERE m.status='completed' AND substr(m.date_utc,1,4)='2026'
           AND s.two_k IS NULL AND m.advanced_attempted_utc IS NULL ORDER BY m.date_utc DESC''').to_dict('records')]

    def world_series_cached(self,event_id,match_id):
        return bool(self.scalar('SELECT EXISTS(SELECT 1 FROM world_series_done WHERE event_id=? AND match_id=?)',
                                (event_id,match_id),default=0))

    def save_world_series(self,event,mid,teams,side,rounds,agents):
        now=datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            for table,rows in [('world_team_maps',teams),('world_side_players',side),
                               ('world_rounds',rounds),('world_agent_picks',agents)]:
                for row in rows:
                    keys=list(row)
                    con.execute('INSERT OR REPLACE INTO '+table+' ('+','.join(keys)+') VALUES ('+
                                ','.join('?' for k in keys)+')',list(row.values()))
            con.execute('INSERT OR REPLACE INTO world_series_done VALUES(?,?,?)',(event,mid,now))

    def world_frames(self,event):
        return tuple(self.frame('SELECT * FROM '+table+' WHERE event_id=?',(event,))
                     for table in ('world_team_maps','world_side_players','world_rounds','world_agent_picks'))

    def mark_advanced_attempt(self,match_id):
        with self.connect() as con:
            con.execute('UPDATE matches SET advanced_attempted_utc=? WHERE id=?',
                        (datetime.now(timezone.utc).isoformat(),match_id))
