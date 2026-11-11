"""Compact, checked and encrypted packets of readings (TM355).

Pipeline used by the encrypted backup export:

    readings --(quantise 0.1 °C, delta, zig-zag, varint; columns)--> bytes
             --(DEFLATE = LZ77 + Huffman via zlib; or our own Huffman)--> compressed payload
             --(frame: magic, version, method, length, CRC-32)-->    frame
             --(scrypt key from passphrase, AES-256-GCM)-->          encrypted file

CRC-32 detects accidental bit errors (noisy channel); the GCM tag detects deliberate tampering.
Hamming(7,4) is included for the channel-coding experiments in the notebook.
"""
import heapq
import os
import struct
import zlib
from collections import Counter

MAGIC = b"HRR1"
ENC_MAGIC = b"HRRE"
METHOD_RAW, METHOD_HUFFMAN, METHOD_ZLIB = 0, 1, 2


# ----------------------------------------------------------------- varints
def zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def unzigzag(z: int) -> int:
    return (z >> 1) ^ -(z & 1)


def put_varint(out: bytearray, n: int) -> None:
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def get_varint(buf, pos):
    shift = result = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


# ----------------------------------------------------------------- column encoding
def _runs(values):
    """Run-length encode a list into (value, count) pairs."""
    out = []
    for v in values:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def encode_readings(readings) -> bytes:
    """readings: list of (ts:int, temp_c:float|None, battery:int|None, charging:bool), sorted by ts.

    Columns: time deltas, temperature deltas in tenths of °C (missing values skipped and
    marked by a run-length mask), battery deltas (same), charging as runs.
    """
    out = bytearray()
    put_varint(out, len(readings))
    if not readings:
        return bytes(out)
    put_varint(out, int(readings[0][0]))
    prev = int(readings[0][0])
    for ts, *_ in readings[1:]:
        put_varint(out, int(ts) - prev)
        prev = int(ts)
    for col, scale in ((1, 10), (2, 1)):
        present = [r[col] is not None for r in readings]
        runs = _runs(present)
        put_varint(out, len(runs))
        out.append(1 if runs[0][0] else 0)
        for _, n in runs:
            put_varint(out, n)
        prev = 0
        for r in readings:
            if r[col] is not None:
                q = int(round(r[col] * scale))
                put_varint(out, zigzag(q - prev))
                prev = q
    runs = _runs([bool(r[3]) for r in readings])
    put_varint(out, len(runs))
    out.append(1 if runs[0][0] else 0)
    for _, n in runs:
        put_varint(out, n)
    return bytes(out)


def decode_readings(buf: bytes):
    pos = 0
    n, pos = get_varint(buf, pos)
    if n == 0:
        return []
    ts = [0] * n
    ts[0], pos = get_varint(buf, pos)
    for i in range(1, n):
        d, pos = get_varint(buf, pos)
        ts[i] = ts[i - 1] + d
    cols = []
    for scale in (10, 1):
        nruns, pos = get_varint(buf, pos)
        flag = bool(buf[pos])
        pos += 1
        mask = []
        for _ in range(nruns):
            k, pos = get_varint(buf, pos)
            mask += [flag] * k
            flag = not flag
        vals, prev = [], 0
        for present in mask:
            if present:
                z, pos = get_varint(buf, pos)
                prev += unzigzag(z)
                vals.append(prev / scale if scale != 1 else prev)
            else:
                vals.append(None)
        cols.append(vals)
    nruns, pos = get_varint(buf, pos)
    flag = bool(buf[pos])
    pos += 1
    charging = []
    for _ in range(nruns):
        k, pos = get_varint(buf, pos)
        charging += [flag] * k
        flag = not flag
    return [(ts[i], cols[0][i], cols[1][i], charging[i]) for i in range(n)]


# ----------------------------------------------------------------- Huffman coding
def huffman_lengths(data: bytes):
    """Code length for each byte value (optimal prefix code)."""
    freq = Counter(data)
    if len(freq) == 1:
        return {next(iter(freq)): 1}
    heap = [(f, i, (sym,)) for i, (sym, f) in enumerate(freq.items())]
    heapq.heapify(heap)
    lengths = dict.fromkeys(freq, 0)
    uid = len(heap)
    while len(heap) > 1:
        f1, _, s1 = heapq.heappop(heap)
        f2, _, s2 = heapq.heappop(heap)
        for s in s1 + s2:
            lengths[s] += 1
        heapq.heappush(heap, (f1 + f2, uid, s1 + s2))
        uid += 1
    return lengths


def canonical_codes(lengths):
    """Canonical Huffman: codes follow from the lengths alone, so only lengths are stored."""
    code, prev_len, codes = 0, 0, {}
    for sym, ln in sorted(lengths.items(), key=lambda x: (x[1], x[0])):
        code <<= ln - prev_len
        codes[sym] = (code, ln)
        code += 1
        prev_len = ln
    return codes


def huffman_encode(data: bytes) -> bytes:
    if not data:
        return struct.pack(">IH", 0, 0)
    lengths = huffman_lengths(data)
    codes = canonical_codes(lengths)
    out = bytearray(struct.pack(">IH", len(data), len(lengths)))
    for sym, ln in sorted(lengths.items()):
        out += bytes((sym, ln))
    acc = nbits = 0
    for b in data:
        c, ln = codes[b]
        acc = (acc << ln) | c
        nbits += ln
        while nbits >= 8:
            nbits -= 8
            out.append((acc >> nbits) & 0xFF)
        acc &= (1 << nbits) - 1
    if nbits:
        out.append((acc << (8 - nbits)) & 0xFF)
    return bytes(out)


def huffman_decode(buf: bytes) -> bytes:
    n, nsym = struct.unpack_from(">IH", buf, 0)
    pos = 6
    lengths = {}
    for _ in range(nsym):
        lengths[buf[pos]] = buf[pos + 1]
        pos += 2
    decode = {(c, ln): s for s, (c, ln) in canonical_codes(lengths).items()}
    out = bytearray()
    code = ln = 0
    for byte in buf[pos:]:
        for bit in range(7, -1, -1):
            code = (code << 1) | ((byte >> bit) & 1)
            ln += 1
            sym = decode.get((code, ln))
            if sym is not None:
                out.append(sym)
                if len(out) == n:
                    return bytes(out)
                code = ln = 0
    return bytes(out)


# ----------------------------------------------------------------- framing with CRC-32
class FrameError(ValueError):
    pass


def make_frame(readings, method=METHOD_ZLIB) -> bytes:
    raw = encode_readings(readings)
    payload = {METHOD_RAW: lambda b: b, METHOD_HUFFMAN: huffman_encode,
               METHOD_ZLIB: lambda b: zlib.compress(b, 9)}[method](raw)
    head = MAGIC + struct.pack(">BBI", 1, method, len(payload))
    body = head + payload
    return body + struct.pack(">I", zlib.crc32(body))


def read_frame(frame: bytes):
    if len(frame) < 14 or frame[:4] != MAGIC:
        raise FrameError("not a Harara frame")
    body, (crc,) = frame[:-4], struct.unpack(">I", frame[-4:])
    if zlib.crc32(body) != crc:
        raise FrameError("CRC mismatch: frame damaged")
    _, method, length = struct.unpack_from(">BBI", frame, 4)
    payload = body[10:10 + length]
    raw = {METHOD_RAW: lambda b: b, METHOD_HUFFMAN: huffman_decode, METHOD_ZLIB: zlib.decompress}[method](payload)
    return decode_readings(raw)


# ----------------------------------------------------------------- encryption (AES-256-GCM)
def _key(passphrase: str, salt: bytes) -> bytes:
    import hashlib
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def encrypt_frame(frame: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(passphrase, salt)).encrypt(nonce, frame, ENC_MAGIC)
    return ENC_MAGIC + salt + nonce + ct


def decrypt_frame(blob: bytes, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if blob[:4] != ENC_MAGIC:
        raise FrameError("not an encrypted Harara backup")
    salt, nonce, ct = blob[4:20], blob[20:32], blob[32:]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, ct, ENC_MAGIC)
    except InvalidTag:
        raise FrameError("wrong passphrase or file was changed") from None


def export_backup(readings, passphrase: str, path: str) -> int:
    blob = encrypt_frame(make_frame(readings, METHOD_ZLIB), passphrase)   # DEFLATE beat order-0 Huffman (TM355 notebook)
    with open(path, "wb") as f:
        f.write(blob)
    return len(blob)


def import_backup(path: str, passphrase: str):
    with open(path, "rb") as f:
        return read_frame(decrypt_frame(f.read(), passphrase))


# ----------------------------------------------------------------- Hamming(7,4)
def hamming74_encode_bits(bits):
    """4 data bits -> 7 code bits [p1 p2 d1 p3 d2 d3 d4]; corrects any single bit error."""
    out = []
    for i in range(0, len(bits), 4):
        d1, d2, d3, d4 = (list(bits[i:i + 4]) + [0, 0, 0])[:4]
        out += [d1 ^ d2 ^ d4, d1 ^ d3 ^ d4, d1, d2 ^ d3 ^ d4, d2, d3, d4]
    return out


def hamming74_decode_bits(code):
    out = []
    for i in range(0, len(code), 7):
        c = list(code[i:i + 7])
        s = (c[0] ^ c[2] ^ c[4] ^ c[6]) | (c[1] ^ c[2] ^ c[5] ^ c[6]) << 1 | (c[3] ^ c[4] ^ c[5] ^ c[6]) << 2
        if s:
            c[s - 1] ^= 1          # syndrome = position of the wrong bit
        out += [c[2], c[4], c[5], c[6]]
    return out


def to_bits(data: bytes):
    return [(b >> (7 - k)) & 1 for b in data for k in range(8)]


def from_bits(bits):
    return bytes(sum(bit << (7 - k) for k, bit in enumerate(bits[i:i + 8])) for i in range(0, len(bits) - 7, 8))
