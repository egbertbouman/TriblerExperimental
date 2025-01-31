import logging
import os
import os.path
import sys
from pathlib import Path
from typing import List

from PyQt5.QtCore import QCoreApplication, QEvent, Qt

from tribler.gui.app_manager import AppManager
from tribler.gui.code_executor import CodeExecutor
from tribler.gui.single_application import QtSingleApplication
from tribler.gui.utilities import connect

# Set the QT application parameters before creating any instances of the application.
QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"


# fmt: off

class TriblerApplication(QtSingleApplication):
    """
    This class represents the main Tribler application.
    """

    def __init__(self):
        QtSingleApplication.__init__(self, "triblerapp")
        self._logger = logging.getLogger(self.__class__.__name__)
        self.code_executor = None
        connect(self.message_received, self.on_app_message)
        self.manager = AppManager(self)

    def on_app_message(self, msg):
        if msg.startswith('file') or msg.startswith('magnet'):
            self.handle_uri(msg)

    def handle_uri(self, uri):
        if self.tribler_window:
            self.tribler_window.handle_uri(uri)

    def parse_sys_args(self, args):
        for arg in args[1:]:
            if os.path.exists(arg):
                file_path = arg.decode()
                uri = Path(file_path).as_uri()
                self.handle_uri(uri)
            elif arg.startswith('magnet'):
                self.handle_uri(arg)

        if '--allow-code-injection' in sys.argv[1:]:
            variables = globals().copy()
            variables.update(locals())
            variables['window'] = self.tribler_window
            self.code_executor = CodeExecutor(5500, shell_variables=variables)
            connect(self.tribler_window.events_manager.core_connected, self.code_executor.on_core_connected)
            connect(self.tribler_window.tribler_crashed, self.code_executor.on_crash)

        if '--testnet' in sys.argv[1:]:
            os.environ['TESTNET'] = "YES"
        if '--chant-testnet' in sys.argv[1:]:
            os.environ['CHANT_TESTNET'] = "YES"
        if '--tunnel-testnet' in sys.argv[1:]:
            os.environ['TUNNEL_TESTNET'] = "YES"

    @staticmethod
    def get_urls_from_sys_args() -> List[str]:
        urls = []
        for arg in sys.argv[1:]:
            if os.path.exists(arg) and arg.endswith(".torrent"):
                urls.append(Path(arg).as_uri())
            elif arg.startswith('magnet'):
                urls.append(arg)
        return urls

    def send_torrent_file_path_to_primary_process(self):
        urls_to_send = self.get_urls_from_sys_args()
        if not urls_to_send:
            return

        if not self.connected_to_previous_instance:
            self._logger.warning("Can't send torrent url: do not have a connection to a primary process")
            return

        count = len(urls_to_send)
        self._logger.info(f'Sending {count} torrent file{"s" if count > 1 else ""} to a primary process')
        for url in urls_to_send:
            self.send_message(url)

    def event(self, event):
        if event.type() == QEvent.FileOpen and event.file().endswith(".torrent"):
            uri = Path(event.file()).as_uri()
            self.handle_uri(uri)
        return QtSingleApplication.event(self, event)
