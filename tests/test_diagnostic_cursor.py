import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
reader = importlib.import_module('diagnostic_reader')

class CursorTests(unittest.TestCase):
    def test_old_date_survives_large_new_logs(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            old={'timestamp':'2026-09-01T00:00:00Z','event':'old','request_id':'historical'}
            (p/'operations.jsonl.15').write_text(json.dumps(old)+'\n')
            line=(json.dumps({'timestamp':'2026-10-01T00:00:00Z','event':'new','padding':'x'*9000})+'\n').encode()
            (p/'operations.jsonl').write_bytes(line*1500)
            since,until=reader.window(datetime(2026,9,1,tzinfo=timezone.utc),datetime(2026,9,2,tzinfo=timezone.utc))
            rows=[]; token=None
            for _ in range(10):
                r=reader.scan_records(p,('operations.jsonl*',),since,until,{'request_id':'historical'},'admin:1',cursor=token)
                rows.extend(r['items']);token=r['next_cursor']
                if not token:break
            self.assertEqual([r['request_id'] for r in rows],['historical'])

    def test_cursor_bound_snapshot_timezone_and_tail(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); path=p/'operations.jsonl'
            path.write_text(''.join(json.dumps({'timestamp':t,'event':'probe','request_id':str(i),'password':'SECRET',
                'customer_id':123,'customer_name':'untrusted','instance_id':'fake'})+'\n' for i,t in enumerate([
                '2026-10-02T08:02:00+08:00','2026-10-02T00:01:00Z','2026-10-02T00:03:00Z']))+'{bad}\n{partial')
            s,u=reader.window(datetime(2026,10,2,tzinfo=timezone.utc),datetime(2026,10,3,tzinfo=timezone.utc))
            r=reader.scan_records(p,('operations.jsonl*',),s,u,{},'admin:1',page_size=1)
            self.assertEqual(r['items'][0]['request_id'],'2')
            self.assertNotIn('customer_id',r['items'][0]); self.assertNotIn('SECRET',str(r))
            token=r['next_cursor']
            from fastapi import HTTPException
            with self.assertRaises(HTTPException): reader.scan_records(p,('operations.jsonl*',),s,u,{},'admin:2',cursor=token)
            with self.assertRaises(HTTPException): reader.scan_records(p,('operations.jsonl*',),s,u,{'level':'ERROR'},'admin:1',cursor=token)
            r=reader.scan_records(p,('operations.jsonl*',),s,u,{},'admin:1',cursor=token,page_size=1)
            self.assertEqual(r['items'][0]['request_id'],'0')
            path.rename(p/'operations.jsonl.1');path.write_text('{}\n')
            with self.assertRaises(HTTPException): reader.scan_records(p,('operations.jsonl*',),s,u,{},'admin:1',cursor=r['next_cursor'])

    def test_rebuild_budget_no_gap_and_cache_tail(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);path=p/'operations.jsonl'
            path.write_text(''.join(json.dumps({'timestamp':'2026-10-02T00:00:00Z','event':'probe','request_id':str(i)})+'\n' for i in range(31)))
            s,u=reader.window(datetime(2026,10,2,tzinfo=timezone.utc),datetime(2026,10,3,tzinfo=timezone.utc))
            original=reader.MAX_SCAN;reader.MAX_SCAN=200
            try:
                token=None; ids=[];count=0
                while True:
                    r=reader.scan_records(p,('operations.jsonl*',),s,u,{},'admin:1',cursor=token,page_size=3)
                    ids.extend(x['request_id'] for x in r['items']);count+=1
                    token=r['next_cursor']
                    if not token:break
                    self.assertLess(count,100)
                self.assertEqual(len(ids),31);self.assertEqual(len(set(ids)),31)
                self.assertTrue(r['scan_complete'])
            finally: reader.MAX_SCAN=original
            with path.open('a') as f:f.write(json.dumps({'timestamp':'2026-10-02T01:00:00Z','event':'tail','request_id':'new'})+'\n')
            r=reader.scan_records(p,('operations.jsonl*',),s,u,{'request_id':'new'},'admin:1')
            self.assertEqual(r['items'][0]['request_id'],'new')
            self.assertTrue((p/'.diagnostic-index.json').is_file())

    def test_cache_corruption_rebuilds_and_health_is_nonrecursive(self):
        from log_health import LogHealth
        h=LogHealth();h.failure('log_write_failed')
        self.assertEqual(h.snapshot()['log_drops'],1)
        events=[]
        class Logger:
            def info(self, value):events.append(json.loads(value))
        h.recover(Logger());h.recover(Logger())
        self.assertEqual(len(events),1);self.assertEqual(events[0]['reason_code'],'log_write_recovered')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'operations.jsonl').write_text(json.dumps({'timestamp':'2026-10-02T00:00:00Z','event':'probe'})+'\n')
            s,u=reader.window(datetime(2026,10,2,tzinfo=timezone.utc),datetime(2026,10,3,tzinfo=timezone.utc))
            reader.scan_records(p,('operations.jsonl*',),s,u,{},'admin:1')
            cache=p/'.diagnostic-index.json';obj=json.loads(cache.read_text());obj['files']['operations.jsonl']['rows']=[];cache.write_text(json.dumps(obj))
            r=reader.scan_records(p,('operations.jsonl*',),s,u,{},'admin:1');self.assertEqual(len(r['items']),1)
