from pathlib import Path

import pytest

from services import backup_service as bs


def test_encrypted_backup_round_trip_and_no_plaintext(tmp_path):
    source = tmp_path / "source.sql"
    encrypted = tmp_path / "backup.cftbak"
    restored = tmp_path / "restored.sql"
    content = ("-- MySQL dump\n" + "private row\n" * 200 + "-- Dump completed\n").encode()
    source.write_bytes(content)

    bs._encrypt_file(source, encrypted, "correct horse battery")
    assert bs._is_encrypted(encrypted)
    assert b"private row" not in encrypted.read_bytes()
    bs._decrypt_file(encrypted, restored, "correct horse battery")
    assert restored.read_bytes() == content


def test_wrong_passphrase_and_tampering_are_rejected(tmp_path):
    source = tmp_path / "source.sql"
    encrypted = tmp_path / "backup.cftbak"
    output = tmp_path / "output.sql"
    source.write_bytes(b"secret database content" * 100)
    bs._encrypt_file(source, encrypted, "correct horse battery")

    with pytest.raises(bs.BackupError, match="incorrect|changed|damaged"):
        bs._decrypt_file(encrypted, output, "wrong passphrase here")
    assert not output.exists()

    data = bytearray(encrypted.read_bytes())
    data[len(data) // 2] ^= 1
    encrypted.write_bytes(data)
    with pytest.raises(bs.BackupError, match="incorrect|changed|damaged"):
        bs._decrypt_file(encrypted, output, "correct horse battery")
    assert not output.exists()


def test_short_passphrase_is_refused(tmp_path):
    source = tmp_path / "source.sql"
    source.write_text("x")
    with pytest.raises(bs.BackupError, match="at least 12"):
        bs._encrypt_file(source, tmp_path / "backup.cftbak", "too short")
