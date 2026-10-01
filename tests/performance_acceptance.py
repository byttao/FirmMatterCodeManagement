"""Explicit opt-in local load evidence; never touches an existing installation."""
import argparse
import concurrent.futures
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import statistics
import subprocess
import sys
import time
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=1800)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import test_security as qa
    qa.SecurityTests.setUpClass()
    from database import SessionLocal,DATA_DIR
    import models
    root=Path(__file__).resolve().parents[1]
    base='http://127.0.0.1:18200'
    env={**os.environ,'FIRM_MANAGER_ALLOWED_HOSTS':'127.0.0.1','FIRM_MANAGER_ALLOWED_PORTS':'18200',
         'FIRM_MANAGER_STATIC_DIR':str(root/'frontend/dist')}
    command=[sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','18200','--no-proxy-headers','--no-access-log']
    output=(DATA_DIR/'performance-server.log').open('w')
    server=None
    evidence={'environment':'macOS开发机；不代表Windows2019或2Mbps','duration_requested':args.seconds,'phases':[]}
    try:
        with SessionLocal() as db:
            password=db.get(models.User,1).hashed_password
            for index in range(100):
                user=models.User(username=f'load-{index}',real_name=f'负载人员{index}',fiscal_year=2026,hashed_password=password,
                    is_practitioner=True,role_records=[models.UserRoleRecord(role_code='practitioner')])
                db.add(user)
            db.commit()
        server=subprocess.Popen(command,cwd=root/'backend',env=env,stdout=output,stderr=output)
        admin=httpx.Client(base_url=base,trust_env=False,timeout=40)
        for _ in range(100):
            try:
                if admin.get('/api/setup/status').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        response=admin.post('/api/auth/login',json={'username':'admin','password':'Test-password-2026'})
        response.raise_for_status();admin.headers['X-CSRF-Token']=admin.cookies['firm_csrf']
        def timed(path):
            started=time.perf_counter();response=admin.get(path);return response.status_code,(time.perf_counter()-started)*1000
        with SessionLocal() as db:
            for first,last in ((1,10001),(10001,50001)):
                rows=[dict(project_id=f'PRJ-2026-{100000+i}',firm='测试所',report_type='审计',report_year=2026,
                    customer_name=f'代表客户{i}',customer_id=qa.SecurityTests.customer_id,leader_id=qa.SecurityTests.leader_id,
                    fiscal_year=2026,contract_amount_cents=12345,created_at=datetime(2026,9,1)) for i in range(first,last)]
                db.bulk_insert_mappings(models.Project,rows);db.commit()
                samples={}
                for path in ('/api/projects?fiscal_year=2026&page_size=20','/api/dashboard?fiscal_year=2026','/api/customers?search=测试'):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:results=list(pool.map(lambda _:timed(path),range(60)))
                    timings=sorted(value for _,value in results)
                    samples[path]={'p50_ms':round(statistics.median(timings),2),'p95_ms':round(timings[int(len(timings)*.95)-1],2),'statuses':sorted(set(code for code,_ in results))}
                evidence['phases'].append({'project_count':last-1,'queries':samples})
        for count in (20,50):
            drafts=[]
            for _ in range(count):
                r=admin.post('/api/projects',json={'fiscal_year':2026,'firm':'测试所','report_type':'审计','report_year':2026,'customer_id':qa.SecurityTests.customer_id,'customer_name':'测试客户','leader_id':qa.SecurityTests.leader_id})
                r.raise_for_status();drafts.append(r.json())
            def issue(project):
                started=time.perf_counter();key=secrets.token_hex(16)
                r=admin.post('/api/projects/'+str(project['id'])+'/generate-report-no',json={'expected_revision':project['revision']},headers={'Idempotency-Key':key})
                return r.status_code,(time.perf_counter()-started)*1000,r.json().get('report_no')
            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:results=list(pool.map(issue,drafts))
            timings=sorted(t for _,t,_ in results);numbers=[n for code,_,n in results if code==200]
            evidence['phases'].append({'burst':count,'success':len(numbers),'unique':len(set(numbers)),
                'p95_ms':round(timings[int(count*.95)-1],2),'statuses':sorted(set(c for c,_,_ in results))})
        started=time.monotonic();samples=[];failures={};exports=0;peak_rss_kib=0
        while time.monotonic()-started<args.seconds:
            iteration=time.monotonic()
            for path in ('/api/projects?fiscal_year=2026&page_size=20','/api/dashboard?fiscal_year=2026'):
                code,ms=timed(path);samples.append(ms)
                if code!=200:failures[str(code)]=failures.get(str(code),0)+1
            if int(time.monotonic()-started)%60==0:
                r=admin.post('/api/export-jobs',json={'export_type':'projects','filters':{'fiscal_year':2026,'search':'代表客户'},'columns':['project_id','customer_name']},headers={'Idempotency-Key':secrets.token_hex(16)})
                if r.status_code==202:exports+=1
                elif r.status_code!=429:failures['export-'+str(r.status_code)]=failures.get('export-'+str(r.status_code),0)+1
            r=admin.post('/api/projects',json={'fiscal_year':2026,'firm':'测试所','report_type':'审计','report_year':2026,'customer_id':qa.SecurityTests.customer_id,'customer_name':'测试客户','leader_id':qa.SecurityTests.leader_id})
            if r.status_code==200:
                code,ms,_=issue(r.json());samples.append(ms)
                if code!=200:failures['number-'+str(code)]=failures.get('number-'+str(code),0)+1
            else:failures['create-'+str(r.status_code)]=failures.get('create-'+str(r.status_code),0)+1
            try:peak_rss_kib=max(peak_rss_kib,int(subprocess.check_output(['ps','-o','rss=','-p',str(server.pid)],text=True).strip()))
            except Exception:pass
            elapsed=time.monotonic()-started
            evidence['mixed']={'seconds':round(elapsed,1),'samples':len(samples),'p95_ms':round(sorted(samples)[int(len(samples)*.95)-1],2),
                'failures':failures,'export_jobs':exports,'server_peak_rss_kib':peak_rss_kib,
                'wal_bytes':(DATA_DIR/'db.sqlite-wal').stat().st_size if (DATA_DIR/'db.sqlite-wal').exists() else 0}
            args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
            time.sleep(max(0,1-(time.monotonic()-iteration)))
        with SessionLocal() as db:
            evidence['integrity']={'history_count':db.query(models.ReportNumberHistory).count(),
                'issued_projects':db.query(models.Project).filter(models.Project.report_no!=None).count(),
                'export_statuses':[(status,count) for status,count in db.query(models.ExportJob.status,__import__('sqlalchemy').func.count()).group_by(models.ExportJob.status)]}
        args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps(evidence,ensure_ascii=False))
        admin.close()
    finally:
        if server:server.terminate();server.wait(timeout=20)
        output.close();qa.SecurityTests.tearDownClass()


if __name__=='__main__':main()
