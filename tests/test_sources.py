"""核对业务资料的格式与可关联性。"""
import csv
from pathlib import Path
import unittest

DATA = Path(__file__).resolve().parents[1] / 'data'
TABLES = {'shows': ('show', 'channel', 'category', 'day', 'minutes', 'host'), 'segments': ('segment', 'show', 'start', 'end', 'candidates', 'known', 'ref', 'state'), 'policy': ('id', 'channel', 'category', 'start', 'end', 'evidence_kind'), 'credentials': ('doc', 'person', 'kind', 'channel', 'category', 'start', 'end', 'known', 'state', 'replaces'), 'requests': ('request', 'segment', 'doc_hint', 'requested', 'owner', 'state'), 'reports': ('report', 'asof', 'from_day', 'to_day', 'kind')}
RELATION = ('requests', 'segment', 'segments', 'segment')


class SourceContract(unittest.TestCase):
    def read(self, table):
        with (DATA / f'{table}.csv').open(encoding='utf-8', newline='') as file:
            return list(csv.DictReader(file))

    def test_shape(self):
        for name, columns in TABLES.items():
            with self.subTest(table=name):
                rows = self.read(name)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(tuple(row), columns)
                    self.assertNotIn(None, row.values())

    def test_references(self):
        left, left_key, right, right_key = RELATION
        self.assertLessEqual({row[left_key] for row in self.read(left)}, {row[right_key] for row in self.read(right)})

    def test_source_variation(self):
        self.assertEqual({row['segment'] for row in self.read('requests') if row['doc_hint'] == 'd6'}, {'g3', 'g6'})
        self.assertIn('p1|p2', {row['candidates'] for row in self.read('segments')})
