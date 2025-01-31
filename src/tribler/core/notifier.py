from __future__ import annotations

import typing
from collections import defaultdict
from enum import Enum
from typing import Callable, Optional

from ipv8.messaging.anonymization.tunnel import Circuit


class Desc(typing.NamedTuple):
    name: str
    fields: list[str]
    types: list[type]


class Notification(Enum):
    torrent_finished = Desc("torrent_finished", ["infohash", "name", "hidden"], [str, str, bool])
    tribler_shutdown_state = Desc("tribler_shutdown_state", ["state"], [str])
    tribler_new_version = Desc("tribler_new_version", ["version"], [str])
    channel_discovered = Desc("channel_discovered", ["data"], [dict])
    remote_query_results = Desc("remote_query_results", ["data"], [dict])
    local_query_results = Desc("local_query_results", ["data"], [dict])
    circuit_removed = Desc("circuit_removed", ["circuit", "additional_info"], [str, Circuit])
    tunnel_removed = Desc("tunnel_removed", ["circuit_id", "bytes_up", "bytes_down", "uptime", "additional_info"],
                          [int, int, int, float, str])
    watch_folder_corrupt_file = Desc("watch_folder_corrupt_file", ["file_name"], [str])
    channel_entity_updated = Desc("channel_entity_updated", ["channel_update_dict"], [dict])
    low_space = Desc("low_space", ["disk_usage_data"], [dict])
    events_start = Desc("events_start", ["public_key", "version"], [str, str])
    tribler_exception = Desc("tribler_exception", ["error"], [dict])
    content_discovery_community_unknown_torrent_added = Desc("content_discovery_community_unknown_torrent_added",
                                                             [], [])
    report_config_error = Desc("report_config_error", ["error"], [str])
    peer_disconnected = Desc("peer_disconnected", ["peer_id"], [bytes])
    tribler_torrent_peer_update = Desc("tribler_torrent_peer_update", ["peer_id", "infohash", "balance"],
                                       [bytes, bytes, int])
    torrent_metadata_added = Desc("torrent_metadata_added", ["metadata"], [dict])
    new_torrent_metadata_created = Desc("new_torrent_metadata_created", ["infohash", "title"],
                                        [Optional[bytes], Optional[str]])


class Notifier:

    def __init__(self) -> None:
        self.observers = defaultdict(list)
        self.delegates = set()

    def add(self, topic: Notification, observer: Callable) -> None:
        self.observers[topic].append(observer)

    def notify(self, topic: Notification | str, /, **kwargs) -> None:
        if isinstance(topic, str):
            topic = getattr(Notification, topic)
        topic_name, args, types = topic.value
        if set(args) ^ set(kwargs.keys()):
            message = f"{topic_name} expecting arguments {args} (of types {types}) but received {kwargs}"
            raise ValueError(message)
        for observer in self.observers[topic]:
            observer(**kwargs)
        for delegate in self.delegates:
            delegate(topic, **kwargs)
