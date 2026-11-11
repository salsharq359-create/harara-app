import os
import random
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.packet import (METHOD_HUFFMAN, METHOD_RAW, METHOD_ZLIB, FrameError, decode_readings, decrypt_frame,
                         encode_readings, encrypt_frame, export_backup, from_bits, hamming74_decode_bits,
                         hamming74_encode_bits, huffman_decode, huffman_encode, import_backup, make_frame,
                         read_frame, to_bits, unzigzag, zigzag)


def sample(n=600, seed=1):
    rng = random.Random(seed)
    t, temp, batt, out = 1_789_344_000, 33.0, 70, []
    for i in range(n):
        t += 60
        temp = round(temp + rng.uniform(-0.4, 0.4), 1)
        batt = max(1, min(100, batt + rng.choice([-1, 0, 0, 1])))
        out.append((t, None if i % 97 == 5 else temp, None if i % 211 == 7 else batt, (i // 120) % 2 == 0))
    return out


def test_zigzag_roundtrip():
    for n in (0, 1, -1, 63, -64, 10**6, -10**6):
        assert unzigzag(zigzag(n)) == n


def test_column_encoding_roundtrip_with_missing_values():
    r = sample()
    assert decode_readings(encode_readings(r)) == r
    assert decode_readings(encode_readings([])) == []
    assert len(encode_readings(r)) < len(r) * 4            # vs 8+8+8 bytes as doubles


def test_huffman_roundtrip_and_gain():
    data = bytes(random.Random(2).choices(range(6), weights=[50, 20, 10, 10, 5, 5], k=5000))
    enc = huffman_encode(data)
    assert huffman_decode(enc) == data and len(enc) < len(data) / 3
    assert huffman_decode(huffman_encode(b"aaaa")) == b"aaaa"
    assert huffman_decode(huffman_encode(b"")) == b""


def test_frames_all_methods_and_crc_detects_damage():
    r = sample()
    for m in (METHOD_RAW, METHOD_HUFFMAN, METHOD_ZLIB):
        f = make_frame(r, m)
        assert read_frame(f) == r
    bad = bytearray(make_frame(r))
    bad[30] ^= 0x04                                          # one flipped bit
    with pytest.raises(FrameError):
        read_frame(bytes(bad))


def test_encrypted_backup_roundtrip_wrong_key_and_tamper():
    r = sample(300)
    path = os.path.join(tempfile.mkdtemp(), "b.harara")
    export_backup(r, "correct horse", path)
    assert import_backup(path, "correct horse") == r
    with pytest.raises(FrameError):
        import_backup(path, "wrong")
    blob = bytearray(open(path, "rb").read())
    blob[-20] ^= 1
    with pytest.raises(FrameError):
        decrypt_frame(bytes(blob), "correct horse")
    assert encrypt_frame(b"x", "k") != encrypt_frame(b"x", "k")    # random salt + nonce


def test_hamming74_corrects_every_single_bit_error():
    data = bytes(range(16))
    code = hamming74_encode_bits(to_bits(data))
    for i in range(len(code)):
        damaged = list(code)
        damaged[i] ^= 1
        assert from_bits(hamming74_decode_bits(damaged)) == data
