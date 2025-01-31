import dataclasses
from typing import TYPE_CHECKING

from pony.orm import Required

if TYPE_CHECKING:
    @dataclasses.dataclass
    class RendezvousCertificate:
        public_key: bytes
        ip: bytes
        port: int
        ping: float
        start: float
        stop: float


def define_binding(db):
    class RendezvousCertificate(db.Entity):
        public_key = Required(bytes, index=True)
        ip = Required(bytes)
        port = Required(int)
        ping = Required(float)
        start = Required(float)
        stop = Required(float)

    return RendezvousCertificate
