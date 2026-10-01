"""Device identity and one trusted source of license state."""
import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import platform
import re
import secrets
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from database import DATA_DIR, SessionLocal
import models
from version import APP_VERSION
from runtime_log import event

OFFLINE_SECONDS, HEARTBEAT_SECONDS = 1296000, 21600
TRIAL_LIMITS = {'fiscal_years':1,'practitioners':3,'projects':3}
FEATURE_CODES = {'project_management','project_assignment','business_number','signatory_review',
    'invoice_registration','payment_registration','user_management','fiscal_year_settings','data_export'}


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def encoded(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def decoded(value):
    return base64.urlsafe_b64decode(value+'='*(-len(value)%4))


def stamp(value):
    parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('授权时间缺少时区')
    return parsed.timestamp()


def iso(value):
    return datetime.fromtimestamp(value,timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')


def normalize_url(value):
    try:
        parsed=urlsplit(value.strip().rstrip('/'))
        if parsed.scheme!='http' or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:raise ValueError()
        address=ipaddress.IPv4Address(parsed.hostname)
        if address.is_unspecified or address.is_multicast:raise ValueError()
        port=parsed.port or 80
        if not 1<=port<=65535:raise ValueError()
        return f'http://{address}:{port}'
    except (ValueError,TypeError,AttributeError):
        raise ValueError('授权地址必须为HTTP IPv4和端口，不允许路径、账号或跳转')


def fingerprint():
    return hashlib.sha256('|'.join((platform.system(),platform.machine(),socket.gethostname(),hex(uuid.getnode()))).encode()).hexdigest()


def version_in_range(version, version_min, version_max):
    def parts(value):
        if not value or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}', value):
            raise ValueError('版本必须为数字点分格式')
        values = tuple(int(number) for number in value.split('.'))
        return values + (0,) * (4 - len(values))
    try:
        current = parts(version)
        return (not version_min or current >= parts(version_min)) and (not version_max or current <= parts(version_max))
    except ValueError:
        return False


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as output:
            json.dump(value,output,ensure_ascii=False,sort_keys=True)
            output.flush();os.fsync(output.fileno())
        temporary.chmod(0o600);temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class LicenseManager:
    def __init__(self,directory=DATA_DIR,public_key=None,development=None):
        self.directory=Path(directory)
        self.identity_path=self.directory/'device-identity.json'
        self.state_path=self.directory/'license-state.json'
        self._identity=None;self._state=None;self._load_error=None
        self._guard=threading.RLock()
        self.network_lock=asyncio.Lock();self.wakeup=asyncio.Event()
        self.wall_base=time.time();self.monotonic_base=time.monotonic();self.server_base=None;self.last_checkpoint=0
        frozen=bool(getattr(sys,'frozen',False))
        self.development=(not frozen and os.getenv('FIRM_MANAGER_DEVELOPMENT')=='1') if development is None else development and not frozen
        self.public_key=public_key
        if public_key is None:
            try:
                value=(Path(sys.executable).resolve().parent/'license-public-key.txt').read_text(encoding='ascii').strip() if frozen else os.getenv('FIRM_MANAGER_LICENSE_PUBLIC_KEY','').strip()
                raw=decoded(value)
                self.public_key=Ed25519PublicKey.from_public_bytes(raw) if len(raw)==32 else None
            except (OSError,ValueError):pass

    def identity(self,initialize=False):
        with self._guard:
            if self._identity is not None:return self._identity
            if self.identity_path.exists():
                try:
                    value=json.loads(self.identity_path.read_text(encoding='utf-8'))
                    private=Ed25519PrivateKey.from_private_bytes(decoded(value['private_key']))
                    raw=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
                    if value['device_key_id']!=hashlib.sha256(raw).hexdigest()[:32] or len(value['instance_id'])!=32:raise ValueError()
                except (OSError,ValueError,KeyError,TypeError):raise ValueError('设备身份损坏，请恢复原身份备份')
            elif initialize and not self.state_path.exists():
                private=Ed25519PrivateKey.generate()
                raw=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
                value={'instance_id':uuid.uuid4().hex,'device_key_id':hashlib.sha256(raw).hexdigest()[:32],
                    'private_key':encoded(private.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()))}
                atomic_json(self.identity_path,value)
            else:raise ValueError('缺少原设备私钥，请恢复身份备份；不得创建替代身份')
            self._identity={**value,'private':private,'public_key':encoded(raw)}
            return self._identity

    def verify(self,document):
        if not self.public_key or not isinstance(document,dict):return False
        try:
            self.public_key.verify(decoded(document['signature']),canonical({k:v for k,v in document.items() if k!='signature'}))
            return True
        except Exception:return False

    def _mac(self,value):
        return hmac.new(decoded(self.identity()['private_key']),canonical(value),hashlib.sha256).hexdigest()

    def load(self):
        with self._guard:
            if self._state is not None:return self._state
            self._state={}
            if not self.state_path.exists():return self._state
            try:
                envelope=json.loads(self.state_path.read_text(encoding='utf-8'));state=envelope['state']
                if not hmac.compare_digest(envelope['mac'],self._mac(state)):raise ValueError()
                if state.get('lease'):self.validate_lease(state['lease'])
                self._state=state
            except (OSError,ValueError,KeyError,TypeError):self._load_error='授权缓存或设备身份损坏，请恢复备份或重新核验'
            return self._state

    def persist(self):
        atomic_json(self.state_path,{'state':self._state,'mac':self._mac(self._state)})

    def validate_grant(self,document):
        if not self.verify(document) or document.get('schema_version')!=2 or document.get('document_type')!='license' or document.get('product_code')!='YMH-FMC':
            raise ValueError('许可证协议或签名无效，必须使用预置发行公钥')
        normalize_url(document.get('server_url'))
        if not isinstance(document.get('license_id'),str):raise ValueError('许可证编号无效')

    def validate_lease(self,lease):
        identity=self.identity()
        if not self.verify(lease) or lease.get('schema_version')!=2 or lease.get('document_type')!='lease' or lease.get('product_code')!='YMH-FMC':raise ValueError('租约签名或协议无效')
        if lease.get('instance_id')!=identity['instance_id'] or lease.get('device_key_id')!=identity['device_key_id']:raise ValueError('租约不属于当前设备')
        if lease.get('status') not in {'active','not_yet_active','expired_readonly','suspended_readonly','revoked_readonly','version_not_allowed','user_limit_exceeded'}:raise ValueError('租约状态无效')
        issued=stamp(lease['issued_at']);deadline=stamp(lease['lease_until']);stamp(lease['starts_at'])
        if lease.get('offline_grace_seconds')!=OFFLINE_SECONDS or deadline>issued+OFFLINE_SECONDS:raise ValueError('离线租约超过15天')
        contract=lease.get('contract_expires_at');grace=lease.get('renewal_grace_days')
        if type(grace) is not int or not 0<=grace<=366:raise ValueError('合同宽限无效')
        if lease.get('license_type')!='perpetual' and (not contract or deadline>stamp(contract)+grace*86400):raise ValueError('租约超出合同期限')
        if lease.get('heartbeat_interval_seconds')!=HEARTBEAT_SECONDS or type(lease.get('max_users')) is not int or lease['max_users']<0:raise ValueError('租约配额或周期无效')
        if not isinstance(lease.get('features'),list) or any(f not in FEATURE_CODES for f in lease['features']):raise ValueError('租约功能无效')
        for field in ('lease_sequence','license_revision'):
            if type(lease.get(field)) is not int or lease[field]<1:raise ValueError('租约修订无效')
        normalize_url(lease['server_url'])

    def accept(self,lease,grant=None,server_url=None,response_age=0):
        with self._guard:
            self.validate_lease(lease);state=self.load();previous=state.get('lease')
            if previous and previous['license_id']==lease['license_id']:
                if lease['license_revision']<previous['license_revision'] or lease['lease_sequence']<previous['lease_sequence']:raise ValueError('旧租约不可覆盖新状态')
                if lease['lease_sequence']==previous['lease_sequence']:
                    if canonical(lease)!=canonical(previous):raise ValueError('同序列租约内容冲突')
                    state.update(last_result='success',last_error=None);self.persist();return
                if stamp(lease['issued_at'])<stamp(previous['issued_at']):raise ValueError('服务端时间回拨，请检查中心时钟')
            if previous and previous['status']=='revoked_readonly' and previous['license_id']==lease['license_id'] and lease['status']=='active':raise ValueError('撤销身份不能自行恢复')
            now=time.time();self.wall_base=now;self.monotonic_base=time.monotonic();self.server_base=stamp(lease['issued_at'])+max(0,response_age)
            self._state={**state,'lease':lease,'grant':grant or state.get('grant'),'server_url':normalize_url(server_url or lease['server_url']),
                'clock_offset':self.server_base-now,'trusted_floor':self.server_base,'wall_checkpoint':now,
                'last_success_at':lease['issued_at'],'last_attempt_at':iso(now),'last_result':'success','last_error':None}
            self.persist();self._load_error=None;self.last_checkpoint=time.monotonic()

    def status(self):
        with self._guard:
            if self.development:return {'required':False,'allowed':True,'mode':'development','reason':'显式源码开发构建','limits':None}
            state=self.load()
            if not self.public_key or self._load_error:return {'required':True,'allowed':False,'mode':'invalid_license','reason':self._load_error or '缺少有效预置公钥','limits':None}
            lease=state.get('lease')
            if not lease:return {'required':True,'allowed':True,'mode':'trial','reason':'试用额度内可用','limits':TRIAL_LIMITS.copy()}
            wall=time.time();elapsed=time.monotonic()-self.monotonic_base
            now=max(wall+state.get('clock_offset',0),state.get('trusted_floor',0),self.server_base+elapsed if self.server_base else 0)
            clock_bad=wall<state.get('wall_checkpoint',wall)-300 or wall-self.wall_base<elapsed-300
            mode=lease['status'];allowed=False
            if clock_bad:mode='clock_untrusted'
            elif mode=='active':
                if not version_in_range(APP_VERSION,lease.get('version_min'),lease.get('version_max')):mode='version_not_allowed'
                elif now<stamp(lease['starts_at']):mode='not_yet_active'
                elif now>=stamp(lease['lease_until']):mode='expired_readonly'
                else:
                    allowed=True
                    if state.get('last_result')=='error' or now>=stamp(lease['issued_at'])+HEARTBEAT_SECONDS:mode='offline_grace'
            if time.monotonic()-self.last_checkpoint>=60 and not clock_bad:
                state['trusted_floor']=now;state['wall_checkpoint']=wall
                try:self.persist()
                except OSError:allowed=False;mode='invalid_license'
                self.last_checkpoint=time.monotonic()
            messages={'active':'授权有效','offline_grace':'有效离线租约内','expired_readonly':'租约或合同已到期，只读',
                'suspended_readonly':'授权暂停，只读','revoked_readonly':'授权或设备已撤销，只读','not_yet_active':'授权尚未生效',
                'clock_untrusted':'本机时间回拨，请校时并核验','invalid_license':'授权缓存保存失败','version_not_allowed':'当前版本不在授权范围','user_limit_exceeded':'专业人员数超过授权上限'}
            return {'required':True,'allowed':allowed,'mode':mode,'reason':messages.get(mode,'授权不可用'),'document':lease,
                'limits':None,'expires_at':lease.get('contract_expires_at'),'lease_until':lease['lease_until']}

    def features(self):
        if self.development or self.status()['mode']=='trial':return FEATURE_CODES.copy()
        return set(self.load().get('lease',{}).get('features',[]))

    def user_count(self):
        with SessionLocal() as db:return db.query(models.User.id).filter_by(is_active=True,is_practitioner=True).count()

    def request(self,operation,grant=None,instance_name=None):
        identity=self.identity();lease=self.load().get('lease') or {}
        values={'schema_version':2,'operation':operation,'license_id':(grant or lease)['license_id'],'product_code':'YMH-FMC',
            'instance_id':identity['instance_id'],'device_key_id':identity['device_key_id'],'software_version':APP_VERSION,
            'enabled_practitioner_count':self.user_count(),'hardware_fingerprint':fingerprint(),
            'request_id':secrets.token_hex(16),'nonce':secrets.token_hex(16),'sent_at':iso(time.time())}
        if operation=='activate':
            values.update(license_document=grant,device_public_key=identity['public_key'])
            if instance_name:values['instance_name']=instance_name
        values['signature']=encoded(identity['private'].sign(canonical(values)))
        return values

    async def communicate(self,operation,grant=None,server_url=None,instance_name=None,transport=None):
        if grant is not None:
            self.validate_grant(grant)
            if server_url and normalize_url(server_url)!=normalize_url(grant['server_url']):
                raise ValueError('激活地址必须与签名许可证一致；地址恢复使用专门入口')
        async with self.network_lock:
            state=self.load();url=normalize_url(server_url or (grant or {}).get('server_url') or state.get('server_url'))
            digest=hashlib.sha256(canonical(grant or {})).hexdigest();pending=state.get('pending_request')
            if pending and time.time() < stamp(pending['values']['sent_at']) - 300:
                pending = None  # 回拨后请求新的签名时间，不能重用旧响应恢复时钟
            if pending and pending['operation']==operation and pending['url']==url and pending['grant_hash']==digest:values=pending['values']
            else:
                values=await asyncio.to_thread(self.request,operation,grant,instance_name)
                state['pending_request']={'operation':operation,'url':url,'grant_hash':digest,'values':values};self.persist()
            try:
                started=time.monotonic()
                async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,transport=transport) as client:
                    response=await client.post(url+f'/api/v1/{operation}',json=values,headers={'X-Request-ID':values['request_id']})
                result=response.json();lease=result.get('lease')
                if not lease:
                    if response.status_code>=400:
                        if response.status_code<500:self._state.pop('pending_request',None)
                        detail=result.get('detail',{})
                        raise ValueError(detail.get('message','授权通信失败') if isinstance(detail,dict) else '授权通信失败')
                    raise ValueError('授权中心未返回签名租约')
                if lease.get('license_id')!=values['license_id'] or result.get('request_id')!=values['request_id']:raise ValueError('租约请求身份不匹配')
                response_age=max(0,time.time()-stamp(values['sent_at']))
                self.accept(lease,grant,server_url=url if server_url else None,response_age=response_age)
                self._state.pop('pending_request',None);self.persist()
                if operation=='activate':self.wakeup.set()
                event('license.communication',request_id=values['request_id'],target_url=url,operation=operation,result=lease['status'],duration_ms=round((time.monotonic()-started)*1000,2))
                return result
            except (httpx.HTTPError,ValueError,OSError,KeyError,TypeError) as error:
                self._state.update(last_attempt_at=iso(time.time()),last_result='error',last_error=type(error).__name__ if isinstance(error,httpx.HTTPError) else str(error));self.persist()
                event('license.communication',request_id=values['request_id'],target_url=url,operation=operation,result='failed',reason_code=type(error).__name__)
                raise ValueError(self._state['last_error']) from error


manager=LicenseManager()
