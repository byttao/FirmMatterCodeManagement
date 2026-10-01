"""Run against the isolated packaged EXE/service, never a production instance."""
import secrets
import sys
import time
import httpx

base=sys.argv[1]
password='Smoke-'+secrets.token_hex(16)
with httpx.Client(base_url=base,trust_env=False,timeout=30) as client:
    response=client.post('/api/setup',json={'admin_username':'smoke-admin','admin_password':password,
        'admin_real_name':'隔离自检','fiscal_year':2026,'firms':[{'name':'自检所','report_types':[{'report_type':'审计','template':'自检〔{yyyy}〕{nnnn}'}]}]})
    response.raise_for_status()
    client.post('/api/auth/login',json={'username':'smoke-admin','password':password}).raise_for_status()
    client.headers['X-CSRF-Token']=client.cookies['firm_csrf']
    response=client.post('/api/export-jobs',json={'export_type':'projects','filters':{'fiscal_year':2026},'columns':['project_id']},headers={'Idempotency-Key':secrets.token_hex(16)})
    response.raise_for_status();job=response.json()['id']
    for _ in range(60):
        status=client.get('/api/export-jobs/'+job).json()
        if status['status'] not in ('queued','running'):break
        time.sleep(1)
    if status['status']!='succeeded':raise RuntimeError('冻结导出worker未完成任务：'+str(status))
    file=client.get('/api/export-jobs/'+job+'/download');file.raise_for_status()
    if not file.content.startswith(b'PK'):raise RuntimeError('导出文件无效')
    backup=client.post('/api/system/backup',json={'password':password});backup.raise_for_status()
    if not backup.content.startswith(b'YMH-BACKUP-1'):raise RuntimeError('加密备份无效')
print('发布EXE初始化、登录、独立worker导出、认证下载和加密备份通过')
