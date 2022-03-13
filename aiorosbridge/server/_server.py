import sys
import threading
import logging
import signal
from contextlib import asynccontextmanager
from typing import Optional
import uuid

import anyio
import anyio.abc
import wsproto.events
from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from aioros._utils._logging import ColoredFormatter

from ._websocket import upgrade_to_websocket

logger = logging.getLogger(__name__)


def init_logging(log_level: int = logging.INFO) -> None:
    root = logging.getLogger()
    formatter = ColoredFormatter(
        "%(asctime)s rosbridge[%(process)d] %(message)s",
        "%b %d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(log_level)
    root.propagate = False


async def handle_connection(sock: anyio.abc.SocketStream):
    remote_host, remote_port = sock.extra(
        anyio.abc.SocketAttribute.remote_address)
    logger.debug(f'Client connected {remote_host}:{remote_port}')

    fragment_timeout = 600                  # seconds
    delay_between_messages = 0              # seconds
    max_message_size = 10 * 1024 * 1024     # bytes
    unregister_timeout = 10.0               # seconds
    bson_only_mode = False

    async with upgrade_to_websocket(sock) as ws:
        client_id = uuid.uuid4()
        parameters = {
            "fragment_timeout": fragment_timeout,
            "delay_between_messages": delay_between_messages,
            "max_message_size": max_message_size,
            "unregister_timeout": unregister_timeout,
            "bson_only_mode": bson_only_mode,
        }
        protocol = RosbridgeProtocol(client_id, parameters)

        last_response = None
        response_processed_event = threading.Event()

        def set_last_response(response) -> None:
            nonlocal last_response
            last_response = response
            response_processed_event.set()

        protocol.outgoing = set_last_response

        async for message in ws:
            if not isinstance(message, wsproto.events.Message):
                break

            logger.debug(message.data)
            protocol.incoming(message.data)
            response_processed_event.wait()
            logger.debug(last_response)
            if last_response is not None:
                await ws.send(last_response)

    logger.debug(f'Client disconnected {remote_host}:{remote_port}')


@asynccontextmanager
async def start_server(local_address: str = None, rosbridge_port: int = 9090) -> None:
    async with anyio.create_task_group() as task_group:
        server = await anyio.create_tcp_listener(local_host=local_address, local_port=rosbridge_port)

        logger.debug("Starting rosbridge on %s", rosbridge_port)
        task_group.start_soon(server.serve, handle_connection, task_group)

        yield

        logger.debug('Server stopped')
        task_group.cancel_scope.cancel()


async def run(
    rosbridge_port: int = 0,
    local_address: Optional[str] = None,
    debug: bool = False,
) -> None:
    init_logging(logging.DEBUG if debug else logging.INFO)
    async with start_server(local_address=local_address, rosbridge_port=rosbridge_port):
        async with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
            async for signum in signals:
                if signum == signal.SIGINT:
                    print("Ctrl+C pressed!")
                else:
                    print("Terminated!")
                break
