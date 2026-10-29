"""Fixtures artificiais APENAS em testes. Nunca distribuídas como dados do aplicativo."""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from api.client import VLRAdapter
from core.analytics import Analytics
from core.data_engine import DataEngine
from database.db_manager import Database
from tests.test_cache_startup import display_available


def m(mid, date='2026-06-08T10:00:00+00:00', team_score=2,opponent_score=0):
    return dict(id=mid, date_utc=date,tournament='Torneio de teste',
                stage='Fase de teste',bracket='',opponent_id=10,opponent='Oponente fictício de teste',
                team_score=team_score,opponent_score=opponent_score,won=int(team_score>opponent_score),
                url=f'https://www.vlr.gg/{mid}',status='completed')


def row(mid,player,agent,kills,score):
    return dict(match_id=mid, map_index=1,player_id=player,agent=agent,
       kills=kills,deaths=9,assists=3,acs=score,adr=120.0,kast=77.0,hs=24.0,
       rating=1.12,fk=2,fd=1,two_k=None,three_k=None,four_k=None,five_k=None,
       clutches=None,plants=None,defuses=None,economy=None,source='fixture teste',
       player=dict(id=player,nickname=f'TestPlayer{player}',real_name=None,country=None))


def match_maps(mid):
    return [dict(match_id=mid,map_index=1,game_id=mid*10,map_name='Bind',
                 loud_rounds=13,opponent_rounds=6,attack_rounds=7,defense_rounds=6)]


class ExistingCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'test.sqlite3')
        self.db.save_match_list([m(1001),m(1002),m(1003)])

    def test_empty_stats_are_not_invented(self):
        snap=Analytics(self.db)
        self.assertEqual(len(snap.matches()),3)
        self.assertTrue(snap.maps().empty)
        self.assertTrue(snap.players().empty)

    def test_details_only_preserves_list_and_fills_stats(self):
        calls=[]
        class API:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def completed(self,*a,**kw):raise AssertionError('Listagem não deveria ser consultada')
            def roster(self):raise AssertionError('Elenco não deveria ser consultado')
            def details(self,mid,include_advanced=True,on_maps=None,on_vetoes=None):
                calls.append(mid)
                mm=match_maps(mid)
                on_maps(mm,None)
                return mm,[row(mid,1,'Jett',20,235.0),row(mid,2,'Sova',11,175.0)],None,[]
        with patch('core.data_engine.VLRAdapter',API):
            out=DataEngine(self.db).update(details_only=True)
        self.assertEqual(out['processed'],3)
        self.assertEqual(out['errors'],0)
        self.assertEqual(len(calls),3)
        ana=Analytics(self.db)
        matches, maps, players=ana.matches(),ana.maps(),ana.players()
        self.assertEqual(len(matches),3)
        self.assertEqual(len(maps),3)
        self.assertEqual(len(players),6)
        self.assertEqual(int(matches.details_complete.sum()),3)
        self.assertEqual(len(ana.player_summary(players)),2)
        self.assertEqual(len(ana.agents_summary(players)),2)
        self.assertEqual(len(ana.maps_summary(maps)),1)
        self.assertEqual(int(ana.maps_summary(maps)['WR %'].iloc[0]),100)
        self.assertEqual(len(ana.tournament_summary(matches)),1)
        self.assertEqual(len(ana.evolution(players)),2)
        # repetir com cache completo não consulta detalhes novamente
        with patch('core.data_engine.VLRAdapter',API):
            again=DataEngine(self.db).update(details_only=True)
        self.assertEqual(again['processed'],0)
        self.assertEqual(len(calls),3)

    def test_no_known_rounds_does_not_count_as_loss(self):
        self.db.save_details(1001,[dict(match_maps(1001)[0],loud_rounds=None,opponent_rounds=None)],[],None)
        out=Analytics(self.db).maps_summary(Analytics(self.db).maps())
        self.assertEqual(out.iloc[0]['Derrotas'],0)
        import pandas as pd
        self.assertTrue(pd.isna(out.iloc[0]['WR %']))

    def test_map_results_available_before_players_request(self):
        api=VLRAdapter()
        # Fixture no formato dos modelos documentados da biblioteca.
        t1=NS(id=6961,name='LOUD')
        t2=NS(id=400,name='Adversário')
        info=NS(team1=t1,team2=t2,event_id=10,games=[
            NS(played=True,order=1,game_id=76543,map_name='Bind',team1_score=13,
               team2_score=8,team1_attack_rounds=8,team1_defense_rounds=5,
               team2_attack_rounds=4,team2_defense_rounds=4)])
        p=NS(player_id=3,name='P3',country='BR',agents=['Jett'],
             stats=NS(overall=NS(kills=20,deaths=11,assists=5,acs=270,
               adr=160,kast=78,hs_percent=30,rating=1.2,
               first_kills=2,first_deaths=1)))
        events=[]
        class Series:
            def info(self):return info
            def players(self,game_id):
                events.append('players')
                return NS(team1=NS(team_id=6961,team_name='LOUD',players=[p]),
                          team2=NS(team_id=400,team_name='Adversário',players=[]))
        api.client=NS(series=lambda match_id:Series())
        def maps_first(rows,event_id):
            events.append('maps')
            self.assertEqual(rows[0]['loud_rounds'],13)
            self.assertEqual(event_id,10)
        maps,stats,tid,warnings=api.details(1001,include_advanced=False,on_maps=maps_first)
        self.assertEqual(events,['maps','players'])
        self.assertEqual(maps[0]['map_name'],'Bind')
        self.assertEqual(len(stats),1)
        self.assertEqual(stats[0]['agent'],'Jett')
        self.assertEqual(stats[0]['acs'],270)
        self.assertFalse(warnings)


@unittest.skipUnless(display_available(),'Testes Tk precisam de X display (xvfb-run)')
class UiSectionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'gui.sqlite3')
        self.db.save_match_list([m(1001),m(1002)])

    def open_and_navigate(self,with_details):
        if with_details:
            for mid in (1001,1002):
                self.db.save_details(mid,match_maps(mid),
                    [row(mid,1,'Jett',20,235),row(mid,2,'Sova',11,175)])
        from interface import app as ui
        app=None
        with patch.object(ui,'Database',return_value=self.db), \
             patch.object(ui.DataEngine,'update',side_effect=AssertionError('Sem rede')):
            try:
                app=ui.LoudApp()
                def change_tabs():
                    self.assertTrue(app.ready)
                    self.assertEqual(bool(app.coverage_panel.winfo_manager()),not with_details)
                    for section in ui.SECTIONS:
                        app.go(section)
                        app.update_idletasks()
                        self.assertGreater(len(app.main.winfo_children()),0,section)
                errors=[]
                def wait_until_ready():
                    if app.ready:
                        try:
                            change_tabs()
                        except Exception as exc:
                            errors.append(exc)
                        finally:
                            app.after(150,app.close)
                    else:
                        app.after(150,wait_until_ready)
                app.after(200,wait_until_ready)
                app.after(8000,app.close)
                app.mainloop()
                if errors:
                    raise errors[0]
            finally:
                if app is not None and not app._closing:
                    app.close()

    def test_partial_database_every_section_renders(self):
        self.open_and_navigate(False)

    def test_completed_database_every_section_renders(self):
        self.open_and_navigate(True)

    def test_complete_button_fills_cache_without_new_match_listing(self):
        from interface import app as ui
        calls=[]
        def fake_update(engine, *args, **kwargs):
            calls.append(kwargs)
            for mid in (1001,1002):
                self.db.save_details(mid,match_maps(mid),
                    [row(mid,1,'Jett',20,235),row(mid,2,'Sova',11,175)])
            return dict(changed=True,errors=0,message='coleta de teste')
        with patch.object(ui,'Database',return_value=self.db), \
             patch.object(ui.DataEngine,'update',fake_update):
            app=ui.LoudApp()
            def action():
                if not app.ready:
                    app.after(100,action)
                    return
                app.startup_sync(manual=True,details_only=True)
            app.after(100,action)
            app.after(1800,app.close)
            app.mainloop()
        self.assertEqual(len(calls),1)
        self.assertTrue(calls[0]['details_only'])
        self.assertIsNone(calls[0]['limit'])
        self.assertEqual(self.db.scalar('SELECT COUNT(*) FROM player_map_stats'),4)

if __name__=='__main__':unittest.main()
