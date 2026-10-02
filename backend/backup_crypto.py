"""Password-encrypted, consistent SQLite backups; restore only into an empty directory."""
import hashlib
from contextlib import closing
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
import time
import zipfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'YMH-BACKUP-1\0'
MAX_SIZE=200*1024*1024


def key(password,salt):
    if not 12<=len(password)<=128:raise ValueError('备份密码需为12至128位')
    return Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password.encode('utf-8'))


def create(directory,database_name,files,password,product,schema,version):
    directory=Path(directory)
    deadline=time.monotonic()+120
    with tempfile.TemporaryDirectory(prefix='backup-private-') as temporary:
        os.chmod(temporary,0o700)
        target=Path(temporary)/database_name
        def progress(*_):
            if time.monotonic()>deadline:raise ValueError('备份超过时间预算，请稍后重试')
        with closing(sqlite3.connect((directory/database_name).resolve().as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(target)) as snapshot:
            source.backup(snapshot,pages=500,progress=progress)
            if snapshot.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('数据库一致性校验失败')
        paths={database_name:target}
        for name,required in files.items():
            path=directory/name
            if path.is_file():paths[name]=path
            elif required:raise ValueError('缺少必需身份或密钥文件，不能创建完整备份')
        if sum(path.stat().st_size for path in paths.values())>MAX_SIZE:
            raise ValueError('备份超过200MiB，请联系维护人员')
        def digest(path):
            value=hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda:source.read(65536),b''):value.update(chunk)
            return value.hexdigest()
        manifest={'product':product,'schema':schema,'version':version,'created_at':time.time(),
                  'files':{name:digest(path) for name,path in paths.items()}}
        archive_path=Path(temporary)/'snapshot.zip'
        with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            for name,path in paths.items():archive.write(path,name)
        if archive_path.stat().st_size>MAX_SIZE:raise ValueError('压缩备份超过200MiB')
        plain=archive_path.read_bytes()
        salt,nonce=secrets.token_bytes(16),secrets.token_bytes(12)
        blob=MAGIC+salt+nonce+AESGCM(key(password,salt)).encrypt(nonce,plain,MAGIC)
        if len(blob)>MAX_SIZE:raise ValueError('加密备份超过200MiB')
        return blob


def unpack(blob,password,product,schema,allowed):
    if len(blob)>MAX_SIZE or not blob.startswith(MAGIC):raise ValueError('备份格式或大小无效')
    offset=len(MAGIC);salt=blob[offset:offset+16];nonce=blob[offset+16:offset+28]
    try:plain=AESGCM(key(password,salt)).decrypt(nonce,blob[offset+28:],MAGIC)
    except Exception:raise ValueError('备份密码错误或文件被篡改') from None
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)) or set(names)-set(allowed)-{'manifest.json'} or sum(i.file_size for i in archive.infolist())>MAX_SIZE:
            raise ValueError('备份包含无效文件或超过解压上限')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest['product']!=product or manifest['schema']!=schema:raise ValueError('备份产品或结构不匹配，请使用对应版本程序')
        contents={name:archive.read(name) for name in names if name!='manifest.json'}
        if set(contents)!=set(manifest['files']):raise ValueError('备份文件清单不一致')
        for name,value in contents.items():
            if hashlib.sha256(value).hexdigest()!=manifest['files'][name]:raise ValueError('备份文件校验失败')
        for name,required in allowed.items():
            if required and name not in contents:raise ValueError('备份缺少身份或密钥')
        return contents


def restore(blob,password,destination,product,schema,database_name,allowed,validate):
    destination=Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):raise ValueError('只能恢复到全新空数据目录；不能覆盖现有数据')
    contents=unpack(blob,password,product,schema,{database_name:True,**allowed})
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent,prefix='restore-private-') as temporary:
        os.chmod(temporary,0o700);stage=Path(temporary)/'data';stage.mkdir(mode=0o700)
        for name,value in contents.items():
            path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value);path.chmod(0o600)
        with closing(sqlite3.connect(stage/database_name)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('备份数据库一致性验证失败')
            if db.execute('SELECT version FROM schema_version').fetchone()[0]!=schema:raise ValueError('数据库结构不匹配')
            validate(stage,db)
            db.execute('UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP')
            db.commit()
        if destination.exists():destination.rmdir()
        stage.replace(destination)
