"""Mac vault encryption. The random encryption key lives in the login Keychain."""
from cryptography.fernet import Fernet

SERVICE = "College Portals"
ACCOUNT = "vault-encryption-key-v1"
MAGIC = b"CPMAC1\n"


def mac_crypt(data: bytes, decrypt: bool = False, *, keychain=None) -> bytes:
    if decrypt and not data.startswith(MAGIC):
        raise ValueError("Not a Mac vault. Windows DPAPI files cannot be decrypted on macOS.")
    if keychain is None:
        # Use the native backend explicitly; never fall back to a plaintext backend.
        from keyring.backends.macOS import Keyring
        keychain = Keyring()
    key = keychain.get_password(SERVICE, ACCOUNT)
    if key is None:
        if decrypt:
            raise ValueError("The original vault key is missing from the login Keychain.")
        key = Fernet.generate_key().decode("ascii")
        keychain.set_password(SERVICE, ACCOUNT, key)
        # Require successful storage before writing any encrypted accounts.
        if keychain.get_password(SERVICE, ACCOUNT) != key:
            raise OSError("Could not verify the saved Keychain encryption key.")
    cipher = Fernet(key.encode("ascii"))
    return cipher.decrypt(data[len(MAGIC):]) if decrypt else MAGIC + cipher.encrypt(data)
