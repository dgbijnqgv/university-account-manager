import tempfile
from pathlib import Path
import plistlib
import unittest
from unittest.mock import patch
import zipfile

from cryptography.fernet import InvalidToken
from mac_crypto import mac_crypt
from build_mac import build, PREFIX, APP


class MemoryKeychain:
    def __init__(self):
        self.key = None

    def get_password(self, service, account):
        return self.key

    def set_password(self, service, account, value):
        self.key = value


class MacTests(unittest.TestCase):
    def test_encryption_tampering_and_missing_key(self):
        keychain = MemoryKeychain()
        original = b'private credentials'
        encrypted = mac_crypt(original, keychain=keychain)
        self.assertNotIn(original, encrypted)
        self.assertEqual(mac_crypt(encrypted, True, keychain=keychain), original)
        with self.assertRaises(InvalidToken):
            mac_crypt(encrypted[:-8] + b'XXXXXXXX', True, keychain=keychain)
        with self.assertRaises(ValueError):
            mac_crypt(encrypted, True, keychain=MemoryKeychain())
        with self.assertRaises(ValueError):
            mac_crypt(b'Windows vault', True, keychain=keychain)
        failed = MemoryKeychain()
        with patch.object(failed, 'set_password', side_effect=OSError('denied')):
            with self.assertRaises(OSError):
                mac_crypt(original, keychain=failed)
        self.assertIsNone(failed.key)

    def test_mac_store_round_trip(self):
        from app import Store
        keychain = MemoryKeychain()
        def cipher(data, decrypt=False):
            return mac_crypt(data, decrypt, keychain=keychain)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            with patch('app.IS_MAC', True), patch('mac_crypto.mac_crypt', side_effect=cipher):
                store = Store(Path(folder) / 'accounts.vault')
                account = dict(id='1', college='Example', url='', email='a@example.edu', username='user',
                               applicant_id='00123', password='private', notes='note', status='Applied')
                store.save([account])
                self.assertEqual(store.load(), [account])

    def test_package_metadata_permissions_and_no_private_files(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            output = build(Path(folder) / 'mac.zip')
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(len(archive.namelist()), 9)
                self.assertFalse(any('/data/' in name or name.endswith('.vault') for name in archive.namelist()))
                info = plistlib.loads(archive.read(PREFIX + APP + 'Info.plist'))
                self.assertEqual(info['CFBundleExecutable'], 'CollegePortals')
                for name in ('Setup.command', APP + 'MacOS/CollegePortals'):
                    entry = archive.getinfo(PREFIX + name)
                    self.assertEqual((entry.external_attr >> 16) & 0o777, 0o755)
                    self.assertNotIn(b'\r\n', archive.read(entry))
                for name in ('app.py', 'mac_crypto.py', 'check_mac.py'):
                    compile(archive.read(PREFIX + APP + 'Resources/' + name), name, 'exec')


if __name__ == '__main__':
    unittest.main()
