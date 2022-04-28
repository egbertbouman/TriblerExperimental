from unittest.mock import AsyncMock, Mock

import pytest

from tribler.core.components.ipv8.eva.protocol import EVAProtocol
from tribler.core.components.ipv8.eva.transfer.incoming_transfer import IncomingTransfer
from tribler.core.components.ipv8.eva.transfer.transfer_window import TransferWindow


@pytest.fixture
def incoming_transfer() -> IncomingTransfer:
    return IncomingTransfer(info=b'info', data_size=100, nonce=0, on_complete=AsyncMock(), peer=Mock(),
                            protocol=EVAProtocol(Mock(), block_size=10))


def test_on_data_normal_packet(incoming_transfer: IncomingTransfer):
    incoming_transfer.window = Mock(is_finished=Mock(return_value=False))
    incoming_transfer.make_acknowledgement = Mock()
    incoming_transfer.update = Mock()
    incoming_transfer.attempt = 2

    incoming_transfer.on_data(3, b'data')

    assert incoming_transfer.window.add.called_with(3, b'data')
    assert incoming_transfer.update.called
    assert incoming_transfer.attempt == 0
    assert not incoming_transfer.make_acknowledgement.called


def test_on_data_window_is_finished(incoming_transfer: IncomingTransfer):
    incoming_transfer.window = Mock(is_finished=Mock(return_value=True))
    incoming_transfer.make_acknowledgement = Mock()
    incoming_transfer.update = Mock()
    incoming_transfer.attempt = 2

    incoming_transfer.on_data(3, b'data')

    assert incoming_transfer.window.add.called_with(3, b'data')
    assert incoming_transfer.update.called
    assert incoming_transfer.attempt == 0
    assert incoming_transfer.make_acknowledgement.called
    assert not incoming_transfer.finished


def test_on_data_window_is_last_and_finished(incoming_transfer: IncomingTransfer):
    incoming_transfer.window = Mock(is_finished=Mock(return_value=True))
    incoming_transfer.make_acknowledgement = Mock()
    incoming_transfer.update = Mock()
    incoming_transfer.finish = Mock()
    incoming_transfer.attempt = 2
    incoming_transfer.last_window = True

    incoming_transfer.on_data(3, b'data')

    assert incoming_transfer.window.add.called_with(3, b'data')
    assert incoming_transfer.update.called
    assert incoming_transfer.attempt == 0
    assert incoming_transfer.make_acknowledgement.called
    assert incoming_transfer.finish.called


def test_on_data_final_packet(incoming_transfer: IncomingTransfer):
    incoming_transfer.window = TransferWindow(0, 10)
    index = 3

    incoming_transfer.on_data(index, b'')

    assert incoming_transfer.last_window
    assert len(incoming_transfer.window.blocks) == index + 1


def test_make_acknowledgement_no_window(incoming_transfer: IncomingTransfer):
    assert not incoming_transfer.window

    acknowledgement = incoming_transfer.make_acknowledgement()

    assert incoming_transfer.window
    assert acknowledgement
    assert acknowledgement.number == 0
    assert acknowledgement.window_size == incoming_transfer.protocol.window_size


def test_make_acknowledgement_next_window(incoming_transfer: IncomingTransfer):
    incoming_transfer.window = TransferWindow(10, 7)
    incoming_transfer.window.blocks = [b'd', b'a', b't', b'a', None, None, None]

    acknowledgement = incoming_transfer.make_acknowledgement()

    assert len(incoming_transfer.data_list) == 4
    assert incoming_transfer.window
    assert incoming_transfer.window.start == 4
    assert incoming_transfer.window.processed == 0
    assert len(incoming_transfer.window.blocks) == incoming_transfer.protocol.window_size
    assert acknowledgement
    assert acknowledgement.number == 4
    assert acknowledgement.window_size == incoming_transfer.protocol.window_size


async def test_finish(incoming_transfer: IncomingTransfer):
    eva = incoming_transfer.protocol
    incoming_transfer.data_list = [b'data', b'list']
    eva.incoming[incoming_transfer.peer] = incoming_transfer

    incoming_transfer.finish()

    assert incoming_transfer.data_list is None
    assert not eva.incoming
