from __future__ import annotations

import struct
from binascii import hexlify
from datetime import datetime, timedelta
from typing import List, Tuple

from ipv8.keyvault.crypto import default_eccrypto
from ipv8.messaging.lazy_payload import VariablePayload, vp_compile
from ipv8.messaging.serialization import default_serializer, VarLenUtf8
from ipv8.types import Payload, PrivateKey
from typing_extensions import Self

default_serializer.add_packer('varlenIutf8', VarLenUtf8('>I'))
EPOCH = datetime(1970, 1, 1)

SIGNATURE_SIZE = 64
NULL_SIG = b'\x00' * 64
NULL_KEY = b'\x00' * 64

# Metadata types. Should have been an enum, but in Python its unwieldy.
COLLECTION_NODE = 220
REGULAR_TORRENT = 300
CHANNEL_TORRENT = 400
SNIPPET = 600


def time2int(date_time: datetime, epoch: datetime = EPOCH) -> int:
    """
    Convert a datetime object to an int.

    :param date_time: The datetime object to convert.
    :param epoch: The epoch time, defaults to Jan 1, 1970.
    :return: The int representation of date_time.

    WARNING: TZ-aware timestamps are madhouse...
    """
    return int((date_time - epoch).total_seconds())


def int2time(timestamp: int, epoch: datetime = EPOCH) -> datetime:
    """
    Convert an int into a datetime object.

    :param timestamp: The timestamp to be converted.
    :param epoch: The epoch time, defaults to Jan 1, 1970.
    :return: The datetime representation of timestamp.
    """
    return epoch + timedelta(seconds=timestamp)


class KeysMismatchException(Exception):
    pass


class UnknownBlobTypeException(Exception):
    pass


def read_payload_with_offset(data: bytes, offset: int = 0) -> tuple[Payload, int]:
    # First we have to determine the actual payload type
    metadata_type = struct.unpack_from('>H', data, offset=offset)[0]

    if metadata_type != REGULAR_TORRENT:
        raise UnknownBlobTypeException

    payload, offset = default_serializer.unpack_serializable(TorrentMetadataPayload, data, offset=offset)
    payload.signature = data[offset: offset + 64]
    return payload, offset + 64


@vp_compile
class SignedPayload(VariablePayload):
    names = ['metadata_type', 'reserved_flags', 'public_key']
    format_list = ['H', 'H', '64s']

    signature: bytes = NULL_SIG
    metadata_type: int
    reserved_flags: int
    public_key: bytes

    def serialized(self) -> bytes:
        return default_serializer.pack_serializable(self)

    @classmethod
    def from_signed_blob(cls: type[Self], serialized: bytes) -> Self:
        payload, offset = default_serializer.unpack_serializable(cls, serialized)
        payload.signature = serialized[offset:]
        return payload

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in (self.names + ['signature'])}

    @classmethod
    def from_dict(cls: type[Self], **kwargs) -> Self:
        out = cls(**{key: value for key, value in kwargs.items() if key in cls.names})
        if kwargs.get("signature") is not None:
            out.signature = kwargs.get("signature")
        return out

    def add_signature(self, key: PrivateKey) -> None:
        self.public_key = key.pub().key_to_bin()[10:]
        self.signature = default_eccrypto.create_signature(key, self.serialized())

    def has_signature(self) -> bool:
        return self.public_key != NULL_KEY or self.signature != NULL_SIG

    def check_signature(self) -> bool:
        return default_eccrypto.is_valid_signature(
                default_eccrypto.key_from_public_bin(b"LibNaCLPK:" + self.public_key),
                self.serialized(),
                self.signature
        )


@vp_compile
class ChannelNodePayload(SignedPayload):
    names = SignedPayload.names + ['id_', 'origin_id', 'timestamp']
    format_list = SignedPayload.format_list + ['Q', 'Q', 'Q']

    id_: int
    origin_id: int
    timestamp: int


@vp_compile
class TorrentMetadataPayload(ChannelNodePayload):
    """
    Payload for metadata that stores a torrent.
    """

    names = ChannelNodePayload.names + ['infohash', 'size', 'torrent_date', 'title', 'tags', 'tracker_info']
    format_list = ChannelNodePayload.format_list + ['20s', 'Q', 'I', 'varlenIutf8', 'varlenIutf8', 'varlenIutf8']

    infohash: bytes
    size: int
    torrent_date: int
    title: str
    tags: str
    tracker_info: str

    def fix_pack_torrent_date(self, value: datetime | int) -> int:
        if isinstance(value, datetime):
            return time2int(value)
        return value

    @classmethod
    def fix_unpack_torrent_date(cls, value: int) -> datetime:
        return int2time(value)

    def get_magnet(self) -> str:
        return f"magnet:?xt=urn:btih:{hexlify(self.infohash).decode()}&dn={self.title.encode('utf8')}" + (
            f"&tr={self.tracker_info.encode('utf8')}" if self.tracker_info else ""
        )


@vp_compile
class HealthItemsPayload(VariablePayload):
    """
    Payload for health item information. See the details of binary format in MetadataCompressor class description.
    """

    format_list = ['varlenI']
    names = ['data']

    data: bytes

    def serialize(self) -> bytes:
        return default_serializer.pack_serializable(self)

    @classmethod
    def unpack(cls, data) -> List[Tuple[int, int, int]]:
        data = default_serializer.unpack_serializable(cls, data)[0].data
        items = data.split(b';')[:-1]
        return [cls.parse_health_data_item(item) for item in items]

    @classmethod
    def parse_health_data_item(cls, item: bytes) -> Tuple[int, int, int]:
        if not item:
            return 0, 0, 0

        # The format is forward-compatible: currently only three first elements of data are used,
        # and later it is possible to add more fields without breaking old clients
        try:
            seeders, leechers, last_check = map(int, item.split(b',')[:3])
        except Exception:
            return 0, 0, 0

        # Safety check: seelders, leechers and last_check values cannot be negative
        if seeders < 0 or leechers < 0 or last_check < 0:
            return 0, 0, 0

        return seeders, leechers, last_check
