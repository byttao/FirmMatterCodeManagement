"""Application-facing facade over the single LicenseManager."""
from fastapi import HTTPException
from license_manager import manager, TRIAL_LIMITS


def license_required():
    return not manager.development


def trial_mode():
    return manager.status()['mode']=='trial'


def status():
    return manager.status()


def license_features():
    return manager.features()


def read_document():
    return manager.load().get('lease')


def configured_server_url():
    value=manager.load().get('server_url')
    if not value:raise ValueError('尚未配置受信任授权连接地址')
    return value


def heartbeat_state():
    state=manager.load()
    return {'last_attempt_at':state.get('last_attempt_at'),'last_success_at':state.get('last_success_at'),
        'last_result':state.get('last_result'),'last_error':state.get('last_error')}


def require_license_feature(feature):
    if feature not in manager.features():
        raise HTTPException(403,{'code':'feature_not_licensed','message':'当前授权未包含此功能模块'})


async def activate(document,server_url=None,instance_name=None):
    return await manager.communicate('activate',document,server_url,instance_name)


async def heartbeat():
    return await manager.communicate('heartbeat')
