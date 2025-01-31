from __future__ import annotations

import json
import logging
from asyncio.exceptions import TimeoutError as AsyncTimeoutError
from binascii import hexlify, unhexlify
from copy import deepcopy
from ssl import SSLError

import libtorrent as lt
from aiohttp import (BaseConnector, ClientConnectorError, ClientResponseError, ClientSession, ClientTimeout,
                     ServerConnectionError, web)
from aiohttp.typedefs import LooseHeaders
from aiohttp_apispec import docs
from ipv8.REST.schema import schema
from marshmallow.fields import String
from yarl import URL

from tribler.core.database.orm_bindings.torrent_metadata import tdef_to_metadata_dict
from tribler.core.libtorrent.download_manager.download_manager import DownloadManager
from tribler.core.libtorrent.torrentdef import TorrentDef
from tribler.core.libtorrent.uris import unshorten, url_to_path
from tribler.core.notifier import Notification
from tribler.core.restapi.rest_endpoint import (
    HTTP_BAD_REQUEST,
    HTTP_INTERNAL_SERVER_ERROR,
    RESTEndpoint,
    RESTResponse,
)

logger = logging.getLogger(__name__)


def recursive_unicode(obj, ignore_errors=False):
    """
    Converts any bytes within a data structure to unicode strings. Bytes are assumed to be UTF-8 encoded text.

    :param obj: object comprised of lists/dicts/strings/bytes
    :return: obj: object comprised of lists/dicts/strings
    """
    if isinstance(obj, dict):
        return {recursive_unicode(k, ignore_errors): recursive_unicode(v, ignore_errors) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [recursive_unicode(i, ignore_errors) for i in obj]
    elif isinstance(obj, bytes):
        try:
            return obj.decode()
        except UnicodeDecodeError:
            if ignore_errors:
                return "".join(chr(c) for c in obj)
            raise
    return obj


async def query_uri(uri: str, connector: BaseConnector | None = None, headers: LooseHeaders | None = None,
                    timeout: ClientTimeout | None = None, return_json: bool = False, ) -> bytes | dict:
    kwargs = {'headers': headers}
    if timeout:
        # ClientSession uses a sentinel object for the default timeout. Therefore, it should only be specified if an
        # actual value has been passed to this function.
        kwargs['timeout'] = timeout

    async with ClientSession(connector=connector, raise_for_status=True) as session:
        async with await session.get(uri, **kwargs) as response:
            if return_json:
                return await response.json(content_type=None)
            return await response.read()


class TorrentInfoEndpoint(RESTEndpoint):
    """
    This endpoint is responsible for handing all requests regarding torrent info in Tribler.
    """
    path = '/torrentinfo'

    def __init__(self, download_manager: DownloadManager):
        super().__init__()
        self.download_manager = download_manager
        self.app.add_routes([web.get('', self.get_torrent_info)])

    @docs(
        tags=["Libtorrent"],
        summary="Return metainfo from a torrent found at a provided URI.",
        parameters=[{
            'in': 'query',
            'name': 'torrent',
            'description': 'URI for which to return torrent information. This URI can either represent '
                           'a file location, a magnet link or a HTTP(S) url.',
            'type': 'string',
            'required': True
        }],
        responses={
            200: {
                'description': 'Return a hex-encoded json-encoded string with torrent metainfo',
                "schema": schema(GetMetainfoResponse={'metainfo': String})
            }
        }
    )
    async def get_torrent_info(self, request):
        params = request.query
        hops = params.get('hops')
        uri = params.get('uri')
        self._logger.info(f'URI: {uri}')
        if hops:
            try:
                hops = int(hops)
            except ValueError:
                return RESTResponse({"error": f"wrong value of 'hops' parameter: {hops}"}, status=HTTP_BAD_REQUEST)

        if not uri:
            return RESTResponse({"error": "uri parameter missing"}, status=HTTP_BAD_REQUEST)

        uri = await unshorten(uri)
        scheme = URL(uri).scheme

        if scheme == "file":
            file = url_to_path(uri)
            try:
                tdef = await TorrentDef.load(file)
                metainfo = tdef.metainfo
            except (FileNotFoundError, TypeError, ValueError, RuntimeError):
                return RESTResponse({"error": f"error while decoding torrent file: {file}"},
                                    status=HTTP_INTERNAL_SERVER_ERROR)
        elif scheme in ("http", "https"):
            try:
                response = await query_uri(uri)
            except (ServerConnectionError, ClientResponseError, SSLError, ClientConnectorError,
                    AsyncTimeoutError, ValueError) as e:
                self._logger.warning(f'Error while querying http uri: {e}')
                return RESTResponse({"error": str(e)}, status=HTTP_INTERNAL_SERVER_ERROR)

            if response.startswith(b'magnet'):
                try:
                    try:
                        # libtorrent 1.2.19
                        infohash = lt.parse_magnet_uri(uri)["info_hash"]
                    except TypeError:
                        # libtorrent 2.0.9
                        infohash = unhexlify(str(lt.parse_magnet_uri(uri).info_hash))
                except RuntimeError as e:
                    return RESTResponse(
                        {"error": f'Error while getting an infohash from magnet: {e.__class__.__name__}: {e}'},
                        status=HTTP_INTERNAL_SERVER_ERROR
                    )

                metainfo = await self.download_manager.get_metainfo(infohash, timeout=10.0, hops=hops,
                                                                    url=response.decode())
            else:
                metainfo = lt.bdecode(response)
        elif scheme == "magnet":
            self._logger.info(f'magnet scheme detected')

            try:
                try:
                    # libtorrent 1.2.19
                    infohash = lt.parse_magnet_uri(uri)["info_hash"]
                except TypeError:
                    # libtorrent 2.0.9
                    infohash = unhexlify(str(lt.parse_magnet_uri(uri).info_hash))
            except RuntimeError as e:
                return RESTResponse(
                    {"error": f'Error while getting an infohash from magnet: {e.__class__.__name__}: {e}'},
                    status=HTTP_BAD_REQUEST
                )
            metainfo = await self.download_manager.get_metainfo(infohash, timeout=10.0, hops=hops, url=uri)
        else:
            return RESTResponse({"error": "invalid uri"}, status=HTTP_BAD_REQUEST)

        if not metainfo:
            return RESTResponse({"error": "metainfo error"}, status=HTTP_INTERNAL_SERVER_ERROR)

        if not isinstance(metainfo, dict) or b'info' not in metainfo:
            self._logger.warning("Received metainfo is not a valid dictionary")
            return RESTResponse({"error": "invalid response"}, status=HTTP_INTERNAL_SERVER_ERROR)

        # Add the torrent to metadata.db
        torrent_def = TorrentDef.load_from_dict(metainfo)
        metadata_dict = tdef_to_metadata_dict(torrent_def)
        self.download_manager.notifier.notify(Notification.torrent_metadata_added, metadata=metadata_dict)

        download = self.download_manager.downloads.get(metadata_dict["infohash"])
        metainfo_request = self.download_manager.metainfo_requests.get(metadata_dict["infohash"], [None])[0]
        download_is_metainfo_request = download == metainfo_request

        # Check if the torrent is already in the downloads
        encoded_metainfo = deepcopy(metainfo)

        ready_for_unicode = recursive_unicode(encoded_metainfo, ignore_errors=True)
        json_dump = json.dumps(ready_for_unicode, ensure_ascii=False)
        encoded_metainfo = hexlify(json_dump.encode()).decode()
        return RESTResponse({"metainfo": encoded_metainfo,
                             "download_exists": download and not download_is_metainfo_request})
