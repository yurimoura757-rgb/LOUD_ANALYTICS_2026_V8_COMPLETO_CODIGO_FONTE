"""Testes offline com respostas simuladas (não distribuídas no aplicativo)."""
import io
import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from core.data_engine import DataEngine
from database.db_manager import Database
from core.diagnostics import setup_logging, timed


def match(mid):
    return dict(id=mid,date_utc='2026-09-10T18:00:00+00:00',
        tournament='Teste offline',stage='Testes',bracket=None,
        opponent_id=101,opponent='Exemplo fictício (somente teste)',
        team_score=2,opponent_score=0,won=1,
        url='https://www.vlr.gg/'+str(mid),status='completed')


class MockAPI:
    calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def completed(self,full=False):
        self.calls.append(('completed',full))
        return [match(101),match(102),match(103)]
    def details(self,mid,include_advanced=False,on_maps=None,on_vetoes=None):
        self.calls.append(('details',mid,include_advanced))
        maps=[dict(match_id=mid,map_index=1,game_id=1,map_name='Test Map',
                   loud_rounds=13,opponent_rounds=5,attack_rounds=None,defense_rounds=None)]
        if on_maps is not None:
            on_maps(maps,None)
        return maps,[],None,[]
    def roster(self):return []
    def transactions(self):return [],[]
    def upcoming(self):return []


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=Database(Path(self.temp.name)/'test.sqlite3')
        MockAPI.calls=[]

    @mock.patch('core.data_engine.VLRAdapter', MockAPI)
    def test_auto_only_one_detail_and_one_listing(self):
        a=DataEngine(self.db).update(auto=True)
        self.assertEqual(a['found'],3)
        self.assertEqual(a['processed'],1)
        self.assertEqual(sum(k[0]=='completed' for k in MockAPI.calls),1)
        self.assertEqual(sum(k[0]=='details' for k in MockAPI.calls),1)
        self.assertEqual(self.db.scalar('SELECT COUNT(*) FROM matches'),3)
        self.assertEqual(self.db.scalar('SELECT COUNT(*) FROM match_maps'),1)
        self.assertEqual(a['errors'],0)

    @mock.patch('core.data_engine.VLRAdapter', MockAPI)
    def test_auto_does_not_immediately_retry_same_detail(self):
        e=DataEngine(self.db)
        e.update(auto=True)
        e.update(auto=True)
        detail_calls=[x[1] for x in MockAPI.calls if x[0]=='details']
        self.assertEqual(len(detail_calls),2)
        self.assertNotEqual(*detail_calls)

    @mock.patch('core.data_engine.VLRAdapter', MockAPI)
    def test_fast_cache_with_empty_player_data(self):
        DataEngine(self.db).update(auto=True)
        from core.analytics import Analytics
        a=Analytics(self.db)
        self.assertEqual(len(a.matches()),3)
        self.assertEqual(len(a.maps()),1)
        self.assertTrue(a.players().empty)

    def test_exception_is_returned_not_lost(self):
        class BrokenAPI:
            def __enter__(self):raise TimeoutError('timeout na fonte')
            def __exit__(self,*args):return False
        with mock.patch('core.data_engine.VLRAdapter', BrokenAPI):
            response=DataEngine(self.db).update(auto=True)
        self.assertEqual(response['errors'],1)
        self.assertIn('TimeoutError', response['message'])
        self.assertEqual(self.db.scalar('SELECT status FROM update_logs ORDER BY id DESC LIMIT 1'), 'partial')

    def test_empty_cache_does_not_invent_data(self):
        self.assertEqual(self.db.scalar('SELECT COUNT(*) FROM matches'),0)

    def test_logging_has_stage_and_duration(self):
        output=io.StringIO()
        h=logging.StreamHandler(output)
        log=logging.getLogger('loud.etapas')
        log.setLevel(logging.INFO);log.addHandler(h)
        try:
            with timed('etapa isolada'):
                pass
            self.assertIn('INÍCIO: etapa isolada',output.getvalue())
            self.assertIn('FIM: etapa isolada',output.getvalue())
        finally:
            log.removeHandler(h)


if __name__ == '__main__':
    unittest.main()
