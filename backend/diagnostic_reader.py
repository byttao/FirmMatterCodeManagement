"""Rebuildable metadata index and bounded, subject-bound snapshot cursors.

Only timestamps/byte offsets enter the cache. Business databases and payloads do not.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from fastapi import HTTPException

FIELDS = {"timestamp","event","level","request_id","client_request_id","method","route","status_code","duration_ms",
          "client_ip","actor_id","category","reason_code","exception_type","exception_location",
          "customer_id","customer_code","customer_name","identity_verified","instance_id","app_version",
          "enabled_practitioner_count","result","operation","job_id","row_count","exit_code"}
MAX_SCAN = 12 * 1024 * 1024
MAX_ROWS = 5000
TTL = 900
_states = {}

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def window(since, until):
    until = utc(until) if until else datetime.now(timezone.utc)
    since = utc(since) if since else until - timedelta(days=1)
    if since > until or until - since > timedelta(days=31):
        raise HTTPException(422, "日志时间范围须为先开始后结束，且不能超过31天")
    return since, until

def stamp(record):
    return utc(datetime.fromisoformat(record['timestamp'].replace('Z','+00:00'))).timestamp()

def project(record):
    result = {k:(v[:500] if isinstance(v,str) else v) for k,v in record.items()
              if k in FIELDS and (v is None or isinstance(v,(str,int,float,bool)))}
    if record.get('identity_verified') is not True:
        for k in ('customer_id','customer_code','customer_name','instance_id','client_request_id'):
            result.pop(k,None)
    return result

def matches(record, filters):
    for k,v in filters.items():
        if v is None: continue
        if k in ('customer_id','instance_id') and record.get('identity_verified') is not True:return False
        values=(record.get(k), record.get('client_request_id')) if k=='request_id' and record.get('identity_verified') is True else (record.get(k),)
        if str(v) not in tuple(str(x) for x in values):return False
    return True

def identity(path):
    s=path.stat()
    return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]

def load_cache(directory):
    try:
        value=json.loads((directory/'.diagnostic-index.json').read_text())
        return value['files'] if value.get('version')==1 and isinstance(value.get('files'),dict) else {}
    except (OSError,ValueError,TypeError,KeyError):return {}

def save_cache(state):
    target=state['directory']/'.diagnostic-index.json'
    temporary=target.with_name(target.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        data={'version':1,'files':{f['name']:{'identity':f['identity'],'rows':f['rows'], 'bad':f['bad'], 'partial':f['partial'], 'checksum':hashlib.sha256(json.dumps(f['rows'],separators=(',',':')).encode()).hexdigest()} for f in state['files']}}
        temporary.write_text(json.dumps(data,separators=(',',':')))
        os.replace(temporary,target)
    except OSError:pass # An unwritable cache cannot hide the source files.
    finally:
        try:temporary.unlink(missing_ok=True)
        except OSError:pass

def start(directory, patterns, since, until, filters, subject):
    cache=load_cache(directory);files=[]
    paths=sorted({p for pattern in patterns for p in directory.glob(pattern)},key=lambda p:p.name)
    for p in paths:
        if p.is_symlink() or not p.is_file():continue
        try:ident=identity(p)
        except OSError:raise HTTPException(409,'日志文件正在变化，请重新查询')
        f={'name':p.name,'identity':ident,'offset':0,'rows':[], 'bad':0,'partial':False}
        c=cache.get(p.name,{})
        if c.get('identity')==ident:
            try:
                rows=c['rows']
                if c.get('checksum')!=hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest():raise ValueError()
                if not isinstance(rows,list) or not all(len(r)==3 and isinstance(r[0],(int,float)) and isinstance(r[1],int) and isinstance(r[2],int) and r[1]>=0 and 0<r[2]<=10001 and r[1]+r[2]<=ident[2] for r in rows):raise ValueError()
                f.update(offset=ident[2], rows=rows,bad=int(c.get('bad',0)),partial=bool(c.get('partial',False)))
            except (ValueError,KeyError,TypeError):pass
        files.append(f)
    return {'directory':directory,'files':files,'file_index':0,'refs':None,'position':0,'since':since,'until':until,
            'filters':filters,'subject':subject,'expires':time.monotonic()+TTL,'fingerprint':fingerprint(filters),'bad':0}

def fingerprint(filters):
    return hashlib.sha256(json.dumps(filters,sort_keys=True,default=str).encode()).hexdigest()

def check_snapshot(state):
    for f in state['files']:
        p=state['directory']/f['name']
        try:
            if p.is_symlink():raise OSError()
            current=identity(p);original=f['identity']
            # Appends are beyond the fixed read ceiling; replacement, truncation or same-size modification invalidates it.
            if current[:2]!=original[:2] or current[2]<original[2] or (current[2]==original[2] and current[3]!=original[3]):raise OSError()
        except OSError:raise HTTPException(409,'日志查询快照已失效或文件缺失，请重新查询；未宣称历史已全部检索')

def _scan_records(directory, patterns, since, until, filters, subject, cursor=None, page_size=50):
    directory=Path(directory)
    now=time.monotonic()
    for key in list(_states):
        if _states[key]['expires']<now:del _states[key]
    if cursor:
        state=_states.get(cursor)
        if not state or state['subject']!=str(subject) or state['directory']!=directory or state['fingerprint']!=fingerprint(filters):
            raise HTTPException(409,'日志游标失效、过期或查询条件不一致，请重新查询')
        # Explicit date filters must agree; omitted defaults keep the original fixed window.
        if since is not None and utc(since)!=state['since'] or until is not None and utc(until)!=state['until']:
            raise HTTPException(409,'日志游标时间范围不一致，请重新查询')
        check_snapshot(state)
        del _states[cursor]
    else:
        since,until=window(since,until)
        if len(_states)>=16:raise HTTPException(429,'日志查询快照已满，请稍后重试',headers={'Retry-After':'5'})
        state=start(directory,patterns,since,until,filters,str(subject))
    scanned=0;count=0;items=[]
    while state['file_index']<len(state['files']):
        f=state['files'][state['file_index']]
        if f['offset']>=f['identity'][2]:state['file_index']+=1;continue
        with (directory/f['name']).open('rb') as source:
            source.seek(f['offset'])
            while f['offset']<f['identity'][2] and scanned<MAX_SCAN and count<MAX_ROWS:
                offset=f['offset'];line=source.readline(min(10002,f['identity'][2]-offset))
                f['offset']+=len(line);scanned+=len(line);count+=1
                if not line.endswith(b'\n'):
                    if f['offset']==f['identity'][2]:f['partial']=True
                    else:f['bad']+=1
                    continue
                try:
                    row=json.loads(line);t=stamp(row)
                    f['rows'].append([t,offset,len(line)])
                except (ValueError,KeyError,TypeError,AttributeError):f['bad']+=1
        if scanned>=MAX_SCAN or count>=MAX_ROWS:break
    indexed=state['file_index']>=len(state['files'])
    if indexed and state['refs'] is None:
        save_cache(state)
        state['refs']=sorted([(t,f['name'],o,n) for f in state['files'] for t,o,n in f['rows']
                if state['since'].timestamp()<=t<=state['until'].timestamp()],reverse=True)
    if indexed:
        while state['position']<len(state['refs']) and len(items)<page_size and scanned<MAX_SCAN and count<MAX_ROWS:
            _,name,offset,length=state['refs'][state['position']]
            with (directory/name).open('rb') as source:source.seek(offset);line=source.read(length)
            scanned+=len(line);count+=1;state['position']+=1
            try:
                row=json.loads(line)
                if matches(row,state['filters']):items.append(project(row))
            except (ValueError,KeyError,TypeError):pass
    check_snapshot(state)
    complete=indexed and state['position']>=len(state['refs'])
    partial=any(f['partial'] for f in state['files'])
    next_cursor=None
    if not complete:
        next_cursor=secrets.token_urlsafe(32);_states[next_cursor]=state
    timestamps=[r[0] for f in state['files'] for r in f['rows']]
    def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat() if t is not None else None
    return {'items':items,'next_cursor':next_cursor,'scan_complete':complete and not partial,'scanned_bytes':scanned,
            'truncated':not complete or partial, 'has_more':bool(next_cursor),
            'truncated_reason':('index_discovery' if not indexed else 'scan_or_page_budget') if not complete else ('partial_line' if partial else None),
            'since':state['since'].isoformat(),'until':state['until'].isoformat(),'files_invalidated':False,
            'malformed_lines':sum(f['bad'] for f in state['files']),
            'available_range':{'earliest':iso(min(timestamps) if timestamps else None),'latest':iso(max(timestamps) if timestamps else None),'index_complete':indexed},
            'retention_policy':'容量轮转可能早于30天删除；仅可检索当前保留文件。索引发现期间范围未完整。尾部半行须重新查询。'}

def read_records(directory, patterns, since, until, filters):
    """Single bounded compatibility call for local probes; HTTP callers use scan_records."""
    r=scan_records(directory,patterns,since,until,filters,'local-probe',page_size=MAX_ROWS)
    return r['items'],r['truncated']

def scan_records(*args, **kwargs):
    try:return _scan_records(*args, **kwargs)
    except OSError:raise HTTPException(409,'日志文件变化或不可读，查询未完整，请重新查询并检查日志健康状态')
