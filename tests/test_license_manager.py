import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import test_security as baseline  # configure an isolated database before product imports
from license_manager import LicenseManager, canonical, encoded, iso, OFFLINE_SECONDS, stamp


class LeaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='device-lease-')
        self.signer=Ed25519PrivateKey.generate()
        self.manager=LicenseManager(self.directory.name,self.signer.public_key(),development=False)
        self.identity=self.manager.identity(initialize=True)
        self.issued=int(self.manager.wall_base)

    def tearDown(self):
        self.directory.cleanup()

    def signed(self,values):
        return {**values,'signature':encoded(self.signer.sign(canonical(values)))}

    def lease(self,**changes):
        values={'schema_version':2,'document_type':'lease','product_code':'YMH-FMC','license_id':'YMH-TEST-DEVICE',
            'instance_id':self.identity['instance_id'],'device_key_id':self.identity['device_key_id'],'license_revision':1,
            'lease_sequence':1,'status':'active','starts_at':iso(self.issued-86400),'issued_at':iso(self.issued),
            'lease_until':iso(self.issued+OFFLINE_SECONDS),'contract_expires_at':None,'renewal_grace_days':0,
            'offline_grace_seconds':OFFLINE_SECONDS,'license_type':'perpetual','max_users':10,'features':['business_number'],
            'heartbeat_interval_seconds':21600,'server_url':'http://192.168.10.20:8100','config_revision':1,'key_id':'primary'}
        return self.signed({**values,**changes})

    def grant(self,**changes):
        return self.signed({'schema_version':2,'document_type':'license','product_code':'YMH-FMC',
            'license_id':'YMH-TEST-DEVICE','server_url':'http://192.168.10.20:8100',**changes})

    def at(self,offset):
        return patch.multiple('license_manager.time',time=lambda:self.issued+offset,monotonic=lambda:self.manager.monotonic_base+offset)

    def test_fifteen_day_exact_boundary_and_restart_never_extends(self):
        self.manager.accept(self.lease())
        for offset,allowed in ((OFFLINE_SECONDS-60,True),(OFFLINE_SECONDS,False)):
            with self.at(offset):
                self.assertEqual(self.manager.status()['allowed'],allowed)
                restarted=LicenseManager(self.directory.name,self.signer.public_key(),development=False)
                self.assertEqual(restarted.status()['allowed'],allowed)
                self.assertEqual(restarted.load()['lease']['lease_until'],iso(self.issued+OFFLINE_SECONDS))

    def test_contract_deadline_cannot_be_overridden_and_perpetual_is_bounded(self):
        with self.assertRaises(ValueError):self.manager.accept(self.lease(license_type='subscription',contract_expires_at=iso(self.issued+86400)))
        with self.assertRaises(ValueError):self.manager.accept(self.lease(lease_until=iso(self.issued+OFFLINE_SECONDS+1)))
        self.manager.accept(self.lease(license_type='subscription',contract_expires_at=iso(self.issued+86400),lease_until=iso(self.issued+86400)))
        with self.at(86400):self.assertFalse(self.manager.status()['allowed'])

    def test_pause_sequence_replay_conflict_and_revision_rejection(self):
        initial=self.lease();self.manager.accept(initial)
        paused=self.lease(status='suspended_readonly',lease_sequence=2,license_revision=2)
        self.manager.accept(paused)
        self.assertFalse(self.manager.status()['allowed'])
        for document in (initial,self.lease(lease_sequence=2,license_revision=2),self.lease(lease_sequence=3,license_revision=1)):
            with self.assertRaises(ValueError):self.manager.accept(document)
        restored=LicenseManager(self.directory.name,self.signer.public_key(),development=False)
        with self.assertRaises(ValueError):restored.accept(initial)
        self.assertEqual(restored.status()['mode'],'suspended_readonly')

    def test_copy_lease_and_missing_device_private_key_do_not_create_identity(self):
        self.manager.accept(self.lease())
        with tempfile.TemporaryDirectory() as other:
            cloned=LicenseManager(other,self.signer.public_key(),development=False)
            cloned.identity(initialize=True)
            with self.assertRaises(ValueError):cloned.accept(self.lease())
        self.manager.identity_path.unlink()
        restored=LicenseManager(self.directory.name,self.signer.public_key(),development=False)
        self.assertEqual(restored.status()['mode'],'invalid_license')
        with self.assertRaises(ValueError):restored.identity(initialize=True)
        self.assertFalse(restored.identity_path.exists())

    def test_clock_rollback_is_readonly_and_signed_online_response_recovers(self):
        self.manager.accept(self.lease())
        with patch('license_manager.time.time',return_value=self.issued-3600):
            self.assertEqual(self.manager.status()['mode'],'clock_untrusted')
            self.manager.accept(self.lease(lease_sequence=2))
            self.assertTrue(self.manager.status()['allowed'])

    def test_cache_tampering_is_not_a_new_trial(self):
        self.manager.accept(self.lease())
        saved=json.loads(self.manager.state_path.read_text())
        saved['state']['trusted_floor']=0
        self.manager.state_path.write_text(json.dumps(saved))
        restored=LicenseManager(self.directory.name,self.signer.public_key(),development=False)
        self.assertEqual(restored.status()['mode'],'invalid_license')
        self.assertFalse(restored.status()['allowed'])

    async def test_communication_failures_do_not_permanently_block_valid_lease(self):
        self.manager.accept(self.lease())
        for code in (403,404,429,500):
            transport=httpx.MockTransport(lambda request:httpx.Response(code,json={'detail':'unsigned failure'}))
            with self.assertRaises(ValueError):await self.manager.communicate('heartbeat',transport=transport)
            self.assertTrue(self.manager.status()['allowed'])
            self.assertEqual(self.manager.load()['lease']['status'],'active')

    async def test_invalid_grant_and_unsigned_address_rejected_before_network(self):
        calls=[]
        transport=httpx.MockTransport(lambda request:calls.append(request))
        for grant,url in (({**self.grant(),'server_url':'http://127.0.0.1:9000'},None),(self.grant(),'http://127.0.0.1:9000')):
            with self.assertRaises(ValueError):await self.manager.communicate('activate',grant,server_url=url,transport=transport)
        self.assertEqual(calls,[])

    async def test_trial_to_active_changes_limits_and_features_without_restart(self):
        self.assertEqual(self.manager.status()['mode'],'trial')
        def response(request):
            values=json.loads(request.content)
            return httpx.Response(200,json={'request_id':values['request_id'],'lease':self.lease(max_users=25)})
        await self.manager.communicate('activate',self.grant(),transport=httpx.MockTransport(response))
        self.assertTrue(self.manager.status()['allowed'])
        self.assertIsNone(self.manager.status()['limits'])
        self.assertEqual(self.manager.status()['document']['max_users'],25)
        self.assertEqual(self.manager.features(),{'business_number'})
        self.assertTrue(self.manager.wakeup.is_set())

    async def test_lost_response_reuses_request_and_does_not_restart_old_lease_clock(self):
        requests=[]
        def lost(request):
            requests.append(json.loads(request.content))
            raise httpx.ReadTimeout('lost',request=request)
        with self.assertRaises(ValueError):await self.manager.communicate('activate',self.grant(),transport=httpx.MockTransport(lost))
        restarted=LicenseManager(self.directory.name,self.signer.public_key(),development=False)
        def response(request):
            values=json.loads(request.content);requests.append(values)
            return httpx.Response(200,json={'request_id':values['request_id'],'lease':self.lease()})
        with self.at(7*86400):
            await restarted.communicate('activate',self.grant(),transport=httpx.MockTransport(response))
            self.assertEqual(requests[0],requests[1])
            self.assertGreaterEqual(restarted.load()['trusted_floor'],self.issued+7*86400-1)
        self.assertEqual(restarted.load()['lease']['lease_until'],iso(self.issued+OFFLINE_SECONDS))

    def test_frozen_build_cannot_use_development_environment(self):
        with patch('license_manager.sys.frozen',True,create=True):
            frozen=LicenseManager(self.directory.name,self.signer.public_key(),development=True)
            self.assertFalse(frozen.development)

    def test_version_contract_and_local_gate(self):
        from license_manager import version_in_range
        self.assertTrue(version_in_range('0.5','0.5.0','0.5.0.0'))
        self.assertFalse(version_in_range('0.5evil',None,None))
        self.assertFalse(version_in_range('0.6','0.5','0.5.9'))
        self.manager.accept(self.lease(version_max='0.1'))
        self.assertEqual(self.manager.status()['mode'],'version_not_allowed')

    async def test_rollback_does_not_reuse_old_request_to_reset_trusted_clock(self):
        requests=[]
        def lost(request):
            requests.append(json.loads(request.content));raise httpx.ReadTimeout('lost',request=request)
        with self.assertRaises(ValueError):await self.manager.communicate('activate',self.grant(),transport=httpx.MockTransport(lost))
        with patch('license_manager.time.time',return_value=self.issued-3600):
            with self.assertRaises(ValueError):await self.manager.communicate('activate',self.grant(),transport=httpx.MockTransport(lost))
        self.assertNotEqual(requests[0]['request_id'],requests[1]['request_id'])
