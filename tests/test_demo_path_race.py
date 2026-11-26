import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.config import get_demo_data_dir


class DemoPathTests(unittest.TestCase):
    def test_disappearing_sqlite_journal_is_not_a_link_violation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'MY_AGENT_DEMO_DATA_DIR':directory}):
            journal=Path(directory)/'app.db-wal'
            journal.write_bytes(b'fictional journal')
            original=Path.lstat
            def snapshot(path,*args,**kwargs):
                if path==journal:raise FileNotFoundError('injected concurrent journal unlink')
                return original(path,*args,**kwargs)
            with patch.object(Path,'lstat',snapshot):
                self.assertEqual(get_demo_data_dir(),Path(directory).resolve())

    def test_non_regular_and_hardlinked_database_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'MY_AGENT_DEMO_DATA_DIR':directory}):
            target=Path(directory)/'memory.db';target.mkdir()
            with self.assertRaises(RuntimeError):get_demo_data_dir()
            target.rmdir()
            original=Path(directory)/'fiction.txt';original.write_text('fiction')
            os.link(original,target)
            with self.assertRaises(RuntimeError):get_demo_data_dir()
