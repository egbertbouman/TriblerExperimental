from __future__ import annotations

from asyncio import sleep
from typing import Callable
from unittest.mock import AsyncMock, Mock, call

from aiohttp.web_urldispatcher import UrlMappingMatchInfo
from ipv8.test.base import TestBase
from multidict import MultiDict, MultiDictProxy

from tribler.core.database.layers.knowledge import ResourceType, SimpleStatement
from tribler.core.database.restapi.database_endpoint import SNIPPETS_TO_SHOW, DatabaseEndpoint, parse_bool
from tribler.core.database.serialization import REGULAR_TORRENT, SNIPPET
from tribler.core.restapi.rest_endpoint import HTTP_BAD_REQUEST
from tribler.test_unit.base_restapi import MockRequest, response_to_json


class TorrentHealthRequest(MockRequest):
    """
    A MockRequest that mimics TorrentHealthRequests.
    """

    def __init__(self, query: dict, infohash: str) -> None:
        """
        Create a new TorrentHealthRequest.
        """
        super().__init__(query, "GET", f"/metadata/torrents/{infohash}/health")
        self._infohash = infohash

    @property
    def match_info(self) -> UrlMappingMatchInfo:
        """
        Get the match info (the infohash in the url).
        """
        return UrlMappingMatchInfo({"infohash": self._infohash}, Mock())


class PopularTorrentsRequest(MockRequest):
    """
    A MockRequest that mimics PopularTorrentsRequests.
    """

    def __init__(self, query: dict) -> None:
        """
        Create a new PopularTorrentsRequest.
        """
        super().__init__(query, "GET", "/metadata/torrents/popular")


class SearchLocalRequest(MockRequest):
    """
    A MockRequest that mimics SearchLocalRequests.
    """

    def __init__(self, query: dict) -> None:
        """
        Create a new SearchLocalRequest.
        """
        super().__init__(query, "GET", "/metadata/search/local")


class SearchCompletionsRequest(MockRequest):
    """
    A MockRequest that mimics SearchCompletionsRequests.
    """

    def __init__(self, query: dict) -> None:
        """
        Create a new SearchCompletionsRequest.
        """
        super().__init__(query, "GET", "/metadata/search/completions")


class TestDatabaseEndpoint(TestBase):
    """
    Tests for the DatabaseEndpoint REST endpoint.
    """

    async def mds_run_now(self, callback: Callable[[], tuple[dict, int, int]]) -> tuple[dict, int, int]:
        """
        Run an mds callback immediately.
        """
        await sleep(0)
        return callback()

    def test_sanitize(self) -> None:
        """
        Test if parameters are properly sanitized.
        """
        soiled = MultiDictProxy(MultiDict([("first", "7"), ("last", "42"), ("sort_by", "name"), ("sort_desc", "0"),
                                           ("txt_filter", "test"), ("hide_xxx", "0"), ("category", "TEST"),
                                           ("origin_id", "13"), ("tags", "tag1"), ("tags", "tag2"), ("tags", "tag3"),
                                           ("max_rowid", "1337"), ("channel_pk", "AA")]))

        sanitized = DatabaseEndpoint.sanitize_parameters(soiled)

        self.assertEqual(7, sanitized["first"])
        self.assertEqual(42, sanitized["last"])
        self.assertEqual("title", sanitized["sort_by"])
        self.assertFalse(sanitized["sort_desc"])
        self.assertEqual("test", sanitized["txt_filter"])
        self.assertFalse(sanitized["hide_xxx"])
        self.assertEqual("TEST", sanitized["category"])
        self.assertEqual(13, sanitized["origin_id"])
        self.assertEqual(["tag1", "tag2", "tag3"], sanitized["tags"])
        self.assertEqual(1337, sanitized["max_rowid"])
        self.assertEqual(b"\xaa", sanitized["channel_pk"])

    def test_parse_bool(self) -> None:
        """
        Test if parse bool fulfills its promises.
        """
        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool("1"))
        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool("0"))

    def test_add_statements_to_metadata_list(self) -> None:
        """
        Test if statements can be added to an existing metadata dict.
        """
        metadata = {"type": REGULAR_TORRENT, "infohash": "AA"}
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.tribler_db = Mock(knowledge=Mock(get_simple_statements=Mock(return_value=[
            SimpleStatement(ResourceType.TORRENT, "AA", ResourceType.TAG, "tag")
        ])))
        endpoint.add_statements_to_metadata_list([metadata])

        self.assertEqual(ResourceType.TORRENT, metadata["statements"][0]["subject_type"])
        self.assertEqual("AA", metadata["statements"][0]["subject"])
        self.assertEqual(ResourceType.TAG, metadata["statements"][0]["predicate"])
        self.assertEqual("tag", metadata["statements"][0]["object"])

    async def test_get_torrent_health_bad_timeout(self) -> None:
        """
        Test if a bad timeout value in get_torrent_health leads to a HTTP_BAD_REQUEST status.
        """
        endpoint = DatabaseEndpoint(None, None, None)

        response = await endpoint.get_torrent_health(TorrentHealthRequest({"timeout": "AA"}, infohash="AA"))

        self.assertEqual(HTTP_BAD_REQUEST, response.status)

    async def test_get_torrent_health_no_checker(self) -> None:
        """
        Test if calling get_torrent_health without a torrent checker leads to a false checking status.
        """
        endpoint = DatabaseEndpoint(None, None, None)

        response = await endpoint.get_torrent_health(TorrentHealthRequest({}, infohash="AA"))
        response_body_json = await response_to_json(response)

        self.assertEqual(200, response.status)
        self.assertFalse(response_body_json["checking"])

    async def test_get_torrent_health(self) -> None:
        """
        Test if calling get_torrent_health with a valid request leads to a true checking status.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        check_torrent_health = AsyncMock()
        endpoint.torrent_checker = Mock(check_torrent_health=check_torrent_health)

        response = await endpoint.get_torrent_health(TorrentHealthRequest({}, infohash="AA"))
        response_body_json = await response_to_json(response)

        self.assertEqual(200, response.status)
        self.assertTrue(response_body_json["checking"])
        self.assertEqual(call(b'\xaa', timeout=20, scrape_now=True), check_torrent_health.call_args)

    def test_add_download_progress_to_metadata_list(self) -> None:
        """
        Test if progress can be added to an existing metadata dict.
        """
        metadata = {"type": REGULAR_TORRENT, "infohash": "AA"}
        download = Mock(get_state=Mock(return_value=Mock(get_progress=Mock(return_value=1.0))),
                        tdef=Mock(infohash="AA"))
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.download_manager = Mock(get_download=Mock(return_value=download), metainfo_requests=[])
        endpoint.add_download_progress_to_metadata_list([metadata])

        self.assertEqual(1.0, metadata["progress"])

    def test_add_download_progress_to_metadata_list_none(self) -> None:
        """
        Test if progress is not added to an existing metadata dict if no download exists.
        """
        metadata = {"type": REGULAR_TORRENT, "infohash": "AA"}
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.download_manager = Mock(get_download=Mock(return_value=None), metainfo_requests=[])
        endpoint.add_download_progress_to_metadata_list([metadata])

        self.assertNotIn("progress", metadata)

    def test_add_download_progress_to_metadata_list_metainfo_requests(self) -> None:
        """
        Test if progress is not added to an existing metadata dict if it is in metainfo_requests.
        """
        metadata = {"type": REGULAR_TORRENT, "infohash": "AA"}
        download = Mock(get_state=Mock(return_value=Mock(get_progress=Mock(return_value=1.0))),
                        tdef=Mock(infohash="AA"))
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.download_manager = Mock(get_download=Mock(return_value=download), metainfo_requests=["AA"])
        endpoint.add_download_progress_to_metadata_list([metadata])

        self.assertNotIn("progress", metadata)

    async def test_get_popular_torrents(self) -> None:
        """
        Test if we can bring everything together into a popular torrents request.

        Essentially, this combines ``add_download_progress_to_metadata_list`` and ``add_statements_to_metadata_list``.
        """
        metadata = {"type": REGULAR_TORRENT, "infohash": "AA"}
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.tribler_db = Mock(knowledge=Mock(get_simple_statements=Mock(return_value=[
            SimpleStatement(ResourceType.TORRENT, "AA", ResourceType.TAG, "tag")
        ])))
        download = Mock(get_state=Mock(return_value=Mock(get_progress=Mock(return_value=1.0))),
                        tdef=Mock(infohash="AA"))
        endpoint.download_manager = Mock(get_download=Mock(return_value=download), metainfo_requests=[])
        endpoint.mds = Mock(get_entries=Mock(return_value=[Mock(to_simple_dict=Mock(return_value=metadata))]))

        response = await endpoint.get_popular_torrents(PopularTorrentsRequest(metadata))
        response_body_json = await response_to_json(response)
        response_results = response_body_json["results"][0]

        self.assertEqual(200, response.status)
        self.assertEqual(1, response_body_json["first"])
        self.assertEqual(50, response_body_json["last"])
        self.assertEqual(300, response_results["type"])
        self.assertEqual("AA", response_results["infohash"])
        self.assertEqual(1.0, response_results["progress"])
        self.assertEqual(ResourceType.TORRENT.value, response_results["statements"][0]["subject_type"])
        self.assertEqual("AA", response_results["statements"][0]["subject"])
        self.assertEqual(ResourceType.TAG.value, response_results["statements"][0]["predicate"])
        self.assertEqual("tag", response_results["statements"][0]["object"])

    def test_build_snippets_empty(self) -> None:
        """
        Test if building snippets without results leads to no snippets.
        """
        endpoint = DatabaseEndpoint(None, None, None)

        value = endpoint.build_snippets([])

        self.assertEqual([], value)

    def test_build_snippets_one_empty(self) -> None:
        """
        Test if building snippets with an empty result leads to an empty snippet.
        """
        endpoint = DatabaseEndpoint(None, None, None)

        value = endpoint.build_snippets([{}])

        self.assertEqual([{}], value)

    def test_build_snippets_one_filled_no_knowledge(self) -> None:
        """
        Test if building snippets with a result without a knowledge db entry leads to itself.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.tribler_db = Mock(knowledge=Mock(get_objects=Mock(return_value=[])))
        search_result = {"infohash": "AA"}

        value = endpoint.build_snippets([search_result])

        self.assertEqual([search_result], value)

    def test_build_snippets_one_filled_with_knowledge(self) -> None:
        """
        Test if building snippets with a result with a knowledge db entry leads to a properly defined snippet.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.tribler_db = Mock(knowledge=Mock(get_objects=Mock(return_value=["AA"])))
        search_result = {"infohash": "AA", "num_seeders": 1}

        value = endpoint.build_snippets([search_result])

        self.assertEqual(SNIPPET, value[0]["type"])
        self.assertEqual("", value[0]["category"])
        self.assertEqual("AA", value[0]["infohash"])
        self.assertEqual("AA", value[0]["name"])
        self.assertEqual("AA", value[0]["torrents_in_snippet"][0]["infohash"])
        self.assertEqual(1, value[0]["torrents_in_snippet"][0]["num_seeders"])
        self.assertEqual(1, value[0]["torrents"])

    def test_build_snippets_two_filled_with_knowledge(self) -> None:
        """
        Test if building snippets with a result with multiple knowledge db entries leads to properly defined snippets.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.tribler_db = Mock(knowledge=Mock(get_objects=Mock(return_value=["AA", "BB"])))
        search_result = {"infohash": "AA", "num_seeders": 1}

        value = endpoint.build_snippets([search_result])

        for snippet_id in range(2):
            self.assertEqual(SNIPPET, value[snippet_id]["type"])
            self.assertEqual("", value[snippet_id]["category"])
            self.assertEqual(value[snippet_id]["name"], value[snippet_id]["infohash"])
            self.assertIn(value[snippet_id]["infohash"], {"AA", "BB"})
            self.assertIn(value[snippet_id]["name"], {"AA", "BB"})
            self.assertEqual("AA", value[snippet_id]["torrents_in_snippet"][0]["infohash"])
            self.assertEqual(1, value[snippet_id]["torrents_in_snippet"][0]["num_seeders"])
            self.assertEqual(1, value[snippet_id]["torrents"])

    def test_build_snippets_max_filled_with_knowledge(self) -> None:
        """
        Test if building snippets with too many results get constrained.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        mock_results = [chr(ord("A") + i) * 2 for i in range(SNIPPETS_TO_SHOW + 1)]
        endpoint.tribler_db = Mock(knowledge=Mock(get_objects=Mock(return_value=mock_results)))
        search_result = {"infohash": "AA", "num_seeders": 1}

        value = endpoint.build_snippets([search_result])

        self.assertEqual(SNIPPETS_TO_SHOW, len(value))

    async def test_local_search_bad_query(self) -> None:
        """
        Test if a bad value leads to a bad request status.
        """
        endpoint = DatabaseEndpoint(None, None, None)

        response = await endpoint.local_search(SearchLocalRequest({"first": "bla"}))

        self.assertEqual(HTTP_BAD_REQUEST, response.status)

    async def test_local_search_errored_search(self) -> None:
        """
        Test if a search that threw an Exception leads to a bad request status.

        The exception here stems from the ``mds`` being set to ``None``.
        """
        endpoint = DatabaseEndpoint(None, None, None)

        response = await endpoint.local_search(SearchLocalRequest({}))

        self.assertEqual(HTTP_BAD_REQUEST, response.status)

    async def test_local_search_no_knowledge(self) -> None:
        """
        Test if performing a local search without a tribler db set returns mds results.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.mds = Mock(run_threaded=self.mds_run_now, get_total_count=Mock(), get_max_rowid=Mock(),
                            get_entries=Mock(return_value=[Mock(to_simple_dict=Mock(return_value={"test": "test"}))]))

        response = await endpoint.local_search(SearchLocalRequest({}))
        response_body_json = await response_to_json(response)

        self.assertEqual(200, response.status)
        self.assertEqual("test", response_body_json["results"][0]["test"])
        self.assertEqual(1, response_body_json["first"])
        self.assertEqual(50, response_body_json["last"])
        self.assertEqual(None, response_body_json["sort_by"])
        self.assertEqual(True, response_body_json["sort_desc"])

    async def test_local_search_no_knowledge_include_total(self) -> None:
        """
        Test if performing a local search with requested total, includes a total.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.mds = Mock(run_threaded=self.mds_run_now, get_total_count=Mock(return_value=1),
                            get_max_rowid=Mock(return_value=7),
                            get_entries=Mock(return_value=[Mock(to_simple_dict=Mock(return_value={"test": "test"}))]))

        response = await endpoint.local_search(SearchLocalRequest({"include_total": "I would like this"}))
        response_body_json = await response_to_json(response)

        self.assertEqual(200, response.status)
        self.assertEqual("test", response_body_json["results"][0]["test"])
        self.assertEqual(1, response_body_json["first"])
        self.assertEqual(50, response_body_json["last"])
        self.assertEqual(None, response_body_json["sort_by"])
        self.assertEqual(True, response_body_json["sort_desc"])
        self.assertEqual(1, response_body_json["total"])
        self.assertEqual(7, response_body_json["max_rowid"])

    async def test_local_search_with_knowledge_no_tags(self) -> None:
        """
        Test if performing a local search with a tribler db also returns knowledge results.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.tribler_db = Mock(knowledge=Mock(get_simple_statements=Mock(return_value=[
            SimpleStatement(ResourceType.TORRENT, "AA", ResourceType.TAG, "tag")
        ]), get_objects=Mock(return_value=["AA"])))
        endpoint.mds = Mock(run_threaded=self.mds_run_now, get_total_count=Mock(), get_max_rowid=Mock(),
                            get_entries=Mock(return_value=[Mock(to_simple_dict=Mock(return_value={
                                "type": REGULAR_TORRENT,
                                "infohash": "AA",
                                "num_seeders": 1
                            }))]))

        response = await endpoint.local_search(SearchLocalRequest({}))
        response_body_json = await response_to_json(response)
        result = response_body_json["results"][0]

        self.assertEqual(200, response.status)
        self.assertEqual(1, response_body_json["first"])
        self.assertEqual(50, response_body_json["last"])
        self.assertEqual(None, response_body_json["sort_by"])
        self.assertEqual(True, response_body_json["sort_desc"])
        self.assertEqual(SNIPPET, result["type"])
        self.assertEqual("", result["category"])
        self.assertEqual("AA", result["infohash"])
        self.assertEqual("AA", result["name"])
        self.assertEqual("AA", result["torrents_in_snippet"][0]["infohash"])
        self.assertEqual(1, result["torrents_in_snippet"][0]["num_seeders"])
        self.assertEqual(1, result["torrents"])

    async def test_local_search_with_knowledge_with_tags(self) -> None:
        """
        Test if performing a local search with a tribler db and a tag filter also returns knowledge results.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.tribler_db = Mock(knowledge=Mock(
            get_simple_statements=Mock(return_value=[SimpleStatement(ResourceType.TORRENT, "AA",
                                                                     ResourceType.TAG, "tag")]),
            get_objects=Mock(return_value=["AA"]),
            get_subjects_intersection=Mock(return_value={"AA"})
        ))
        endpoint.mds = Mock(run_threaded=self.mds_run_now, get_total_count=Mock(), get_max_rowid=Mock(),
                            get_entries=Mock(return_value=[Mock(to_simple_dict=Mock(return_value={
                                "type": REGULAR_TORRENT,
                                "infohash": "AA",
                                "num_seeders": 1
                            }))]))

        response = await endpoint.local_search(SearchLocalRequest({"tags": "tag"}))
        response_body_json = await response_to_json(response)
        result = response_body_json["results"][0]

        self.assertEqual(200, response.status)
        self.assertEqual(1, response_body_json["first"])
        self.assertEqual(50, response_body_json["last"])
        self.assertEqual(None, response_body_json["sort_by"])
        self.assertEqual(True, response_body_json["sort_desc"])
        self.assertEqual(SNIPPET, result["type"])
        self.assertEqual("", result["category"])
        self.assertEqual("AA", result["infohash"])
        self.assertEqual("AA", result["name"])
        self.assertEqual(REGULAR_TORRENT, result["torrents_in_snippet"][0]["type"])
        self.assertEqual("AA", result["torrents_in_snippet"][0]["infohash"])
        self.assertEqual(1, result["torrents_in_snippet"][0]["num_seeders"])
        self.assertEqual(ResourceType.TORRENT.value, result["torrents_in_snippet"][0]["statements"][0]["subject_type"])
        self.assertEqual("AA", result["torrents_in_snippet"][0]["statements"][0]["subject"])
        self.assertEqual(ResourceType.TAG.value, result["torrents_in_snippet"][0]["statements"][0]["predicate"])
        self.assertEqual("tag", result["torrents_in_snippet"][0]["statements"][0]["object"])
        self.assertEqual(1, result["torrents"])

    async def test_completions_bad_query(self) -> None:
        """
        Test if a missing query leads to a bad request status.
        """
        endpoint = DatabaseEndpoint(None, None, None)

        response = await endpoint.completions(SearchCompletionsRequest({}))

        self.assertEqual(HTTP_BAD_REQUEST, response.status)

    async def test_completions_lowercase_search(self) -> None:
        """
        Test if a normal lowercase search leads to results.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.mds = Mock(get_auto_complete_terms=Mock(return_value=["test1", "test2"]))

        response = await endpoint.completions(SearchCompletionsRequest({"q": "test"}))
        response_body_json = await response_to_json(response)

        self.assertEqual(200, response.status)
        self.assertEqual(["test1", "test2"], response_body_json["completions"])
        self.assertEqual(call("test", max_terms=5), endpoint.mds.get_auto_complete_terms.call_args)

    async def test_completions_mixed_case_search(self) -> None:
        """
        Test if a mixed case search leads to results.
        """
        endpoint = DatabaseEndpoint(None, None, None)
        endpoint.mds = Mock(get_auto_complete_terms=Mock(return_value=["test1", "test2"]))

        response = await endpoint.completions(SearchCompletionsRequest({"q": "TeSt"}))
        response_body_json = await response_to_json(response)

        self.assertEqual(200, response.status)
        self.assertEqual(["test1", "test2"], response_body_json["completions"])
        self.assertEqual(call("test", max_terms=5), endpoint.mds.get_auto_complete_terms.call_args)
