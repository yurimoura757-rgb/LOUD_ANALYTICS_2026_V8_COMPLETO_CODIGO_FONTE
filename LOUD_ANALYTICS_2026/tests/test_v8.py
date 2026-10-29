"""Dados criados APENAS em testes unitários, nunca no software distribuído."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd
from api.champions import parse_leaderboard, event_url
from core.agent_roles import role_of
from core.extra_analytics import compositions, veto_summary, local_records
from core.world_analytics import teams_summary, pistol_summary, side_rankings, agent_top
from database.db_manager import Database
from tests.test_sections import m, match_maps, row

SAMPLE_HTML='''<html><table class="wf-table mod-stats"><thead><tr>
<th>Player</th><th>Agents</th><th>Maps</th><th>Rnd</th><th>R</th>
<th>ACS</th><th>K:D</th><th>KAST</th><th>ADR</th><th>K</th><th>D</th>
<th>A</th><th>CL</th><th>FK</th><th>FD</th></tr></thead><tbody><tr>
<td><span class="text-of">yay</span><span class="stats-player-team">OPTC</span></td>
<td>Chamber</td><td>23</td><td>492</td><td>1.30</td><td>254</td><td>1.50</td><td>73%</td>
<td>159.8</td><td>460</td><td>306</td><td>42</td><td>9/59</td><td>96</td><td>40</td>
</tr></tbody></table></html>'''

class V8Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'db.sqlite3')
        self.db.save_match_list([m(1001)])
    def test_existing_schema_migrates(self):
        db2=Database(self.db.path)
        self.assertEqual(db2.scalar("SELECT COUNT(*) FROM matches"),1)
        self.assertEqual(db2.scalar("SELECT COUNT(*) FROM map_vetoes"),0)
        self.assertEqual(db2.scalar("SELECT COUNT(*) FROM champions_players"),0)
    def test_champions_parse_and_cache(self):
        rows=parse_leaderboard(SAMPLE_HTML)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['player'],'yay')
        self.assertEqual(rows[0]['team'],'OPTC')
        self.assertEqual(rows[0]['clutches'],9)
        self.assertEqual(rows[0]['clutch_attempts'],59)
        self.assertEqual(rows[0]['kast'],73)
        self.assertIn('1015',event_url(2022,'Chamber'))
        self.db.save_champions(1015,2022,'Chamber',rows,event_url(2022,'Chamber'))
        self.assertTrue(self.db.champions_cached(1015,'Chamber'))
        self.assertEqual(self.db.get_champions(1015,'Chamber').iloc[0].kills,460)
        with self.assertRaises(ValueError): self.db.save_champions(1015,2022,'Chamber',[],event_url(2022))
        self.assertEqual(len(self.db.get_champions(1015,'Chamber')),1)
    def test_veto_ids_no_guess(self):
        self.db.save_vetoes(1001,[dict(index=1,map_name='Bind',action='ban',team_name='LOUD',by_loud=1),
            dict(index=2,map_name='Haven',action='ban',team_name='OPTC',by_loud=0)])
        summary=veto_summary(self.db.veto_frame())
        self.assertEqual(summary['Bans LOUD'].sum(),1)
        self.assertEqual(summary['Bans adversário'].sum(),1)
    def test_roles(self):
        self.assertEqual(role_of('Chamber'),'Sentinela')
        self.assertEqual(role_of('Jett'),'Duelista')
        self.assertEqual(role_of('KAY/O'),'Iniciador')
        self.assertEqual(role_of('Jett, Chamber'),'Não classificado')
    def test_compositions_reject_incomplete_lineup(self):
        records=[row(1001,i,a,10,200) for i,a in enumerate(['Chamber','Sova','Omen','Jett','Killjoy'],1)]
        self.db.save_details(1001,match_maps(1001),records)
        from core.analytics import Analytics
        ana=Analytics(self.db)
        comps=compositions(ana.players(),ana.maps())
        self.assertEqual(comps.iloc[0]['Jogos'],1)
        self.assertIn('Chamber',comps.iloc[0]['Composição'])
        self.assertFalse(local_records(ana.player_summary(ana.players())).empty)
    def test_advanced_retry_once(self):
        from core.analytics import Analytics
        self.db.save_details(1001,match_maps(1001),[row(1001,1,'Chamber',20,260)])
        self.assertEqual(self.db.pending_advanced_ids(),[1001])
        self.db.mark_advanced_attempt(1001)
        self.assertEqual(self.db.pending_advanced_ids(),[])
    def test_world_progressive_cache(self):
        t=[dict(event_id=1015,match_id=7,game_id=11,team_id=1,team_name='LOUD',
                map_name='Bind',rounds_won=13,rounds_lost=10,attack_won=7,
                attack_lost=5,defense_won=6,defense_lost=5)]
        a=[dict(event_id=1015,match_id=7,game_id=11,player_id=7,
            player='Teste',team_id=1,team_name='LOUD',side='Ataque',rounds=12,
            kills=17,deaths=10,assists=6,fk=3,fd=1,acs=230,adr=145)]
        r=[dict(event_id=1015,match_id=7,game_id=11,round_number=x,
            winner_team_id=1,team1_id=1,team2_id=2) for x in (1,2,13,14)]
        agent=[dict(event_id=1015,match_id=7,game_id=11,player_id=7,
                    agent='Chamber',team_name='LOUD',map_name='Bind')]
        self.db.save_world_series(1015,7,t,a,r,agent)
        self.assertTrue(self.db.world_series_cached(1015,7))
        tf,pf,rf,af=self.db.world_frames(1015)
        self.assertEqual(teams_summary(tf).iloc[0]['Rounds ganhos'],13)
        self.assertEqual(pistol_summary(tf,rf).iloc[0]['Conversão %'],100)
        self.assertEqual(side_rankings(pf,'Ataque').iloc[0]['First Kills'],3)
        self.assertEqual(agent_top(af).iloc[0]['Agente'],'Chamber')

if __name__=='__main__':unittest.main()


class V8IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'integration.sqlite3')
        self.db.save_match_list([m(1001)])

    def test_persist_multikills_and_clutches_after_reopening(self):
        records=[row(1001,i,a,10,200) for i,a in enumerate(
            ['Chamber','Sova','Omen','Jett','Killjoy'],1)]
        for r in records:
            r.update(two_k=2,three_k=1,four_k=0,five_k=1,clutches=3)
        self.db.save_details(1001,match_maps(1001),records)
        from core.analytics import Analytics
        reopened=Database(self.db.path)
        summary=Analytics(reopened).player_summary(Analytics(reopened).players())
        r=summary.iloc[0]
        self.assertEqual(r['2K'],2)
        self.assertEqual(r['3K'],1)
        self.assertEqual(r['4K'],0)
        self.assertEqual(r['Aces'],1)
        self.assertEqual(r['Clutches'],3)

    def test_verified_age_records_limited_to_cited_editions(self):
        from core.age_records import verified_champions_ages
        ages=verified_champions_ages()
        self.assertEqual(sorted(ages.Ano.unique()),[2021,2022,2023])
        self.assertEqual(len(ages),6)
        self.assertTrue(ages.Fonte.str.startswith('https://liquipedia.net/valorant/').all())

    def test_world_collector_only_fetches_unsaved_series(self):
        from types import SimpleNamespace as NS
        from api.world_deep import fetch_world_series
        status=NS
        a=status(id=1,name='LOUD');b=status(id=2,name='OpTic')
        game=status(played=True,game_id=22,order=1,map_name='Bind',
          team1_attack_rounds=7,team1_defense_rounds=6,team2_attack_rounds=4,
          team2_defense_rounds=6,team1_score=13,team2_score=10)
        series=Mock()
        series.info.return_value=status(team1=a,team2=b,games=[game])
        gameplayer=status(player_id=123,name='Lukxo',agents=['Chamber'],
          stats=status(attack=status(kills=14,deaths=5,assists=4,first_kills=4,first_deaths=0,acs=270,adr=175),
                       defend=status(kills=9,deaths=5,assists=1,first_kills=2,first_deaths=2,acs=230,adr=140)))
        series.players.return_value=status(team1=status(team_name='LOUD',players=[gameplayer]),
                                           team2=status(team_name='OpTic',players=[]))
        series.rounds.return_value=status(rounds=[status(round_number=1,winner_team_id=1),
                                                        status(round_number=2,winner_team_id=1)])
        ev=Mock();ev.matches.return_value=status(matches=[status(match_id=77)])
        client=Mock();client.series.return_value=series;client.event.return_value=ev
        class ClientContext:
            def __enter__(self):return client
            def __exit__(self,*args):return False
        with patch('api.world_deep.LOG'):
            first=fetch_world_series(self.db,2022,client_factory=lambda **kw:ClientContext())
            self.assertEqual(first['saved'],1)
            second=fetch_world_series(self.db,2022,client_factory=lambda **kw:ClientContext())
            self.assertEqual(second['skipped'],1)
        teams,players,rounds,agents=self.db.world_frames(1015)
        self.assertEqual(len(teams),2)
        self.assertEqual(len(players),2)
        self.assertEqual(len(rounds),2)
        self.assertEqual(len(agents),1)
        self.assertEqual(int(players[players.side=='Ataque'].iloc[0].fk),4)
