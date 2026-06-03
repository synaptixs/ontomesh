"""
federation._crypto — pure-stdlib Ed25519 helpers
==================================================
The toolkit is stdlib-only by design.  Python ships ``hashlib`` /
``secrets`` but no Ed25519 primitive, so this module provides a
self-contained RFC 8032 implementation.  It is used strictly for the
federation handshake and capability-manifest signing.

Two public entry points are exposed:

  * :func:`generate_keypair` → ``(sk_b64, pk_b64)``
  * :func:`sign(msg, sk_b64)` → signature as b64
  * :func:`verify(msg, sig_b64, pk_b64)` → ``bool``

All byte strings cross the module boundary as URL-safe base-64 so
they can sit in JSON without escaping.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Tuple

# ── Edwards-curve constants (RFC 8032) ───────────────────────────────
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _sha512(b: bytes) -> bytes:
    return hashlib.sha512(b).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _x_recover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx % _P, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = (4 * _inv(5)) % _P
_BX = _x_recover(_BY)
_B = (_BX % _P, _BY % _P, 1, (_BX * _BY) % _P)


def _edwards_add(P, Q):
    x1, y1, z1, t1 = P
    x2, y2, z2, t2 = Q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    d = z1 * 2 * z2 % _P
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _scalarmult(P, e: int):
    if e == 0:
        return (0, 1, 1, 0)
    Q = _scalarmult(P, e // 2)
    Q = _edwards_add(Q, Q)
    if e & 1:
        Q = _edwards_add(Q, P)
    return Q


def _encode_int(y: int) -> bytes:
    return y.to_bytes(32, "little")


def _decode_int(b: bytes) -> int:
    return int.from_bytes(b, "little")


def _encode_point(P) -> bytes:
    x, y, z, _t = P
    zi = _inv(z)
    x = (x * zi) % _P
    y = (y * zi) % _P
    enc = bytearray(_encode_int(y))
    enc[31] |= (x & 1) << 7
    return bytes(enc)


def _decode_point(s: bytes):
    if len(s) != 32:
        raise ValueError("invalid point length")
    y = _decode_int(bytes(s))
    x_sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    x = _x_recover(y)
    if x & 1 != x_sign:
        x = _P - x
    return (x, y, 1, (x * y) % _P)


def _secret_expand(sk: bytes) -> Tuple[int, bytes]:
    h = _sha512(sk)
    a = bytearray(h[:32])
    a[0] &= 248
    a[31] &= 127
    a[31] |= 64
    return (_decode_int(bytes(a)), h[32:])


# ── Public helpers ──────────────────────────────────────────────────


def generate_keypair() -> Tuple[str, str]:
    """Return ``(secret_key_b64, public_key_b64)`` both 32-byte URL-safe."""
    sk = secrets.token_bytes(32)
    a, _ = _secret_expand(sk)
    pk = _encode_point(_scalarmult(_B, a))
    return _b64(sk), _b64(pk)


def sign(msg: bytes, sk_b64: str) -> str:
    """Ed25519 sign ``msg`` with secret key encoded as URL-safe base-64."""
    sk = _b64d(sk_b64)
    a, prefix = _secret_expand(sk)
    pk = _encode_point(_scalarmult(_B, a))
    r = _decode_int(_sha512(prefix + msg)) % _L
    R = _encode_point(_scalarmult(_B, r))
    h = _decode_int(_sha512(R + pk + msg)) % _L
    S = (r + h * a) % _L
    return _b64(R + _encode_int(S))


def verify(msg: bytes, sig_b64: str, pk_b64: str) -> bool:
    """Return True iff ``sig_b64`` is a valid Ed25519 signature for ``msg``."""
    try:
        sig = _b64d(sig_b64)
        pk = _b64d(pk_b64)
        if len(sig) != 64 or len(pk) != 32:
            return False
        R = _decode_point(sig[:32])
        S = _decode_int(sig[32:])
        A = _decode_point(pk)
        h = _decode_int(_sha512(sig[:32] + pk + msg)) % _L
        left = _scalarmult(_B, S)
        right = _edwards_add(R, _scalarmult(A, h))
        return _encode_point(left) == _encode_point(right)
    except Exception:
        return False


# ── URL-safe base-64 helpers (no padding) ───────────────────────────


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)
