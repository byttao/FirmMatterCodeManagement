import getpass
import io
import json
import os
import threading
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from limited_response import LimitedStreamingResponse
from pydantic import Field
from auth import get_current_user
from database import DATA_DIR, get_db
from permissions import require
from schemas import InputModel
from schema_init import SCHEMA_VERSION
from version import APP_VERSION
from audit import write_lock, event
from backup_crypto import create, restore
import models

FILES={'billing.key':True,'device-identity.json':True,'license-state.json':False,'server.json':False,'manager-settings.json':False}
router=APIRouter(prefix='/api/system/backup')
slot=threading.BoundedSemaphore(1)


class BackupRequest(InputModel):
    password: str = Field(...,min_length=12,max_length=128)


@router.post('')
def backup(data:BackupRequest,request:Request,user=Depends(get_current_user),db=Depends(get_db)):
    require(user,'system.backup')
    from http_security import throttle
    throttle.consume('backup',user.id,2,60)
    db.rollback()
    from license_manager import manager
    if not slot.acquire(blocking=False):raise HTTPException(429,'正在生成备份，请稍后重试')
    try:
        with manager._guard:
            manager.load()
            if manager._state:manager.persist()
            blob=create(DATA_DIR,'db.sqlite',FILES,data.password,'YMH-FMC',SCHEMA_VERSION,APP_VERSION)
        event(db,user,'backup.created',user,request=request);db.commit()
    except (ValueError,OSError):
        slot.release();raise HTTPException(503,'备份失败，请检查磁盘、身份及密钥并提供请求编号')
    except BaseException:
        slot.release();raise
    return LimitedStreamingResponse(io.BytesIO(blob),slot=slot,media_type='application/octet-stream',
        headers={'Content-Disposition':'attachment; filename="firm-encrypted-backup.ymhb"','Cache-Control':'no-store'})


@router.get('/reconciliation')
def reconciliation(user=Depends(get_current_user),db=Depends(get_db)):
    require(user,'system.backup')
    hold=db.get(models.AppSetting,'restore_hold')
    return {'required':bool(hold and json.loads(hold.value).get('required')),
        'rules':[{'id':r.id,'name':r.rule_name,'template':r.template,'current_sequence':r.current_sequence}
                 for r in db.query(models.ReportNumberRule).order_by(models.ReportNumberRule.id)]}


class ReconcileRule(InputModel):
    id: int=Field(...,ge=1)
    actual_last_sequence: int=Field(...,ge=0,le=1000000000)


class Reconcile(InputModel):
    rules: list[ReconcileRule]=Field(...,max_items=1000)
    reason: str=Field(...,min_length=1,max_length=500)
    confirmed_external_records: bool


@router.post('/reconcile')
def reconcile(data:Reconcile,request:Request,user=Depends(get_current_user),db=Depends(get_db)):
    require(user,'system.backup');write_lock(db)
    hold=db.get(models.AppSetting,'restore_hold')
    if not hold or not json.loads(hold.value).get('required'):raise HTTPException(409,'当前无需恢复核号')
    rules=db.query(models.ReportNumberRule).all();values={r.id:r.actual_last_sequence for r in data.rules}
    if not data.confirmed_external_records or len(values)!=len(data.rules) or set(values)!={r.id for r in rules} or not data.reason.strip():
        raise HTTPException(422,'请核对外部已交付编号，并完整填写所有规则和原因')
    for rule in rules:
        if values[rule.id]<rule.current_sequence:raise HTTPException(409,'已交付最大序号不能小于备份序号')
        rule.current_sequence=values[rule.id]
    hold.value=json.dumps({'required':False})
    event(db,user,'backup.reconciled',user,reason=data.reason,diff={'sequences':values},request=request)
    db.commit();return {'message':'核号已记录，允许恢复业务写入'}


def validate_restored(stage,db):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from license_manager import decoded,encoded
    import hashlib
    identity=json.loads((stage/'device-identity.json').read_text())
    private=Ed25519PrivateKey.from_private_bytes(decoded(identity['private_key']))
    if len((stage/'billing.key').read_bytes())!=32 or hashlib.sha256(private.public_key().public_bytes_raw()).hexdigest()[:32]!=identity['device_key_id']:
        raise ValueError('备份密钥或设备身份无效')
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key=(stage/'billing.key').read_bytes();key_id=hashlib.sha256(key).hexdigest()[:16]
    for table,entity,id_field in (('customer_billing_versions','billing-version','id'),('invoice_billing_snapshots','invoice-snapshot-entry','financial_entry_id')):
        for row in db.execute(f'SELECT {id_field},sensitive_ciphertext,key_id FROM {table}'):
            if row[2]!=key_id:raise ValueError('资料加密密钥不匹配')
            blob=base64.b64decode(row[1],validate=True)
            json.loads(AESGCM(key).decrypt(blob[:12],blob[12:],f'{entity}:{row[0]}:sensitive:{key_id}'.encode()))
    db.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('restore_hold','{\"required\":true}')")
    db.execute("UPDATE export_jobs SET status='failed',error_code='restored_without_artifact' WHERE status IN ('running','succeeded')")


def restore_cli(archive,destination):
    password=getpass.getpass('请输入备份密码（不回显）：')
    restore(Path(archive).read_bytes(),password,destination,'YMH-FMC',SCHEMA_VERSION,'db.sqlite',FILES,validate_restored)
    print('恢复完成。启动对应版本后须由管理员核对已交付最大编号，再解除只读保护。')
