import os
import hashlib

def _asn1_length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    elif n < 0x100:
        return bytes([0x81, n])
    else:
        return bytes([0x82, (n >> 8) & 0xFF, n & 0xFF])

def _asn1_tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _asn1_length(len(value)) + value

def _encode_uint(n: int) -> bytes:
    if n == 0:
        return b'\x00'
    result = []
    while n > 0:
        result.append(n & 0xFF)
        n >>= 8
    return bytes(reversed(result))

def generate_preimage(size: int = 32) -> bytes:
    return os.urandom(size)

def make_fulfillment(preimage: bytes) -> bytes:
    return _asn1_tlv(0xA0, _asn1_tlv(0x80, preimage))

def make_condition(preimage: bytes) -> bytes:
    fingerprint = hashlib.sha256(preimage).digest()
    cost        = _encode_uint(len(preimage))
    inner = _asn1_tlv(0x80, fingerprint) + _asn1_tlv(0x81, cost)
    return _asn1_tlv(0xA0, inner)

def condition_hex(preimage: bytes) -> str:
    return make_condition(preimage).hex().upper()

def fulfillment_hex(preimage: bytes) -> str:
    return make_fulfillment(preimage).hex().upper()

def verify_fulfillment(fulfillment_h: str, condition_h: str) -> bool:
    try:
        ff = bytes.fromhex(fulfillment_h)
        assert ff[0] == 0xA0
        i = 1
        l = ff[i]; i += 1
        if l >= 0x80:
            nb = l & 0x7F
            l = int.from_bytes(ff[i:i+nb], 'big'); i += nb
        assert ff[i] == 0x80; i += 1
        plen = ff[i]; i += 1
        preimage = ff[i:i+plen]
        return condition_hex(preimage) == condition_h.upper()
    except Exception:
        return False

def _selftest():
    preimage = bytes(32)
    ff   = make_fulfillment(preimage)
    cond = make_condition(preimage)

    assert ff[0] == 0xA0,   f"ff tag: {ff[0]:02X}"
    assert ff[1] == 0x22,   f"ff len: {ff[1]:02X} (attendu 22)"
    assert ff[2] == 0x80,   f"ff inner tag: {ff[2]:02X}"
    assert ff[3] == 0x20,   f"ff inner len: {ff[3]:02X}"

    assert cond[0] == 0xA0, f"cond tag: {cond[0]:02X}"
    assert cond[1] == 0x25, f"cond len: {cond[1]:02X} (attendu 25, pas 27)"
    assert cond[2] == 0x80, f"cond fp tag: {cond[2]:02X}"
    assert cond[3] == 0x20, f"cond fp len: {cond[3]:02X}"

    assert cond[36] == 0x81, f"cost tag: {cond[36]:02X}"
    assert cond[37] == 0x01, f"cost len: {cond[37]:02X}"
    assert cond[38] == 0x20, f"cost val: {cond[38]:02X}"
    
    assert len(cond) == 39,  f"cond trop long: {len(cond)} (attendu 39, sans subtypes)"

    assert verify_fulfillment(ff.hex(), cond.hex()), "verify échoué"
    print("Crypto condition selftest OK — format XRPL validé")

_selftest()

class JobCryptoKeys:
    def __init__(self):
        self.preimage    = generate_preimage()
        self.condition   = condition_hex(self.preimage)
        self.fulfillment = fulfillment_hex(self.preimage)

    def __repr__(self):
        return (
            f"JobCryptoKeys(\n"
            f"  condition   = {self.condition[:32]}...\n"
            f"  fulfillment = {self.fulfillment[:32]}...\n"
            f")"
        )