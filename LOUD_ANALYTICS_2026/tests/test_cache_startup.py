"""Testes de interface e cache, usando apenas SQLite local e API simulada.

Rodar no Linux: xvfb-run -a python -m unittest tests.test_cache_startup -v
"""
import tempfile
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from database.db_manager import Database


def entry(mid=930100):
    return dict(id=mid, date_utc='2026-09-10T18:00:00+00:00',
                tournament='Fixture de teste',stage='Teste',bracket=None,
                opponent_id=22,opponent='Equipe de teste',team_score=2,
                opponent_score=0,won=1,url=f'https://www.vlr.gg/{mid}',
                status='completed')


def display_available():
    if sys.platform in ('win32', 'darwin'):
        return True
    display=os.environ.get('DISPLAY','')
    if display.startswith(':'):
        number=display[1:].split('.')[0]
        return (Path('/tmp/.X11-unix') / ('X'+number)).exists()
    return bool(display)


@unittest.skipUnless(display_available(), "Tkinter precisa de display; execute com xvfb-run no Linux")
class CacheStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / 'cache.sqlite3')

    def run_app(self, update, *, manual=False, seconds=1.1):
        from interface import app as gui
        with patch.object(gui, 'Database', return_value=self.db), \
             patch.object(gui.DataEngine, 'update', update):
            app=gui.LoudApp()
            if manual:
                app.after(450, lambda: app.startup_sync(manual=True))
            app.after(round(seconds * 1000), app.close)
            app.mainloop()
            return app

    def test_existing_cache_does_not_call_network(self):
        self.db.save_match_list([entry()])
        calls=[]
        def online(*args, **kwargs):
            calls.append(kwargs)
            raise AssertionError('consultou a rede com banco preenchido')
        app = self.run_app(online)
        self.assertTrue(app.ready)
        self.assertTrue(app._has_cached_matches)
        self.assertEqual(calls, [])
        self.assertFalse(app._startup_sync_started)

    def test_first_run_collects_once_and_persists_for_second_run(self):
        calls=[]
        def online(engine, *args, **kwargs):
            calls.append(kwargs)
            engine.db.save_match_list([entry()])
            return dict(changed=True, errors=0, message='ok')
        first=self.run_app(online)
        self.assertTrue(first.ready)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]['auto'])
        self.assertEqual(self.db.scalar('SELECT COUNT(*) FROM matches'), 1)

        def should_not_call(*a, **k):
            raise AssertionError('coleta repetida')
        second=self.run_app(should_not_call)
        self.assertTrue(second._has_cached_matches)
        self.assertFalse(second._startup_sync_started)

    def test_recent_failure_does_not_retry_automatically(self):
        log_id = self.db.log_start()
        self.db.log_end(log_id, 0, 0, 1, 'simulação de falha')
        self.assertFalse(self.db.can_retry_empty_cache())
        calls=[]
        def online(*args, **kwargs):
            calls.append(kwargs)
            return dict(changed=False, errors=0, message='ok')
        app=self.run_app(online)
        self.assertTrue(app.ready)
        self.assertEqual(calls, [])
        self.assertFalse(app._startup_sync_started)
        self.assertIn('falhou recentemente', app.sync_error)

    def test_manual_update_is_available_with_cached_data(self):
        self.db.save_match_list([entry()])
        calls=[]
        def online(engine, *args, **kwargs):
            calls.append(kwargs)
            return dict(changed=False, errors=0, message='ok')
        app=self.run_app(online, manual=True)
        self.assertTrue(app.ready)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['auto'], False)
        self.assertEqual(calls[0]['limit'], 5)
        self.assertFalse(app.updating)


if __name__ == '__main__':
    unittest.main()
