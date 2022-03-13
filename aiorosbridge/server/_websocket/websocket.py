from io import StringIO
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
import anyio.abc
import wsproto
import wsproto.events
import wsproto.utilities

BUFFER_SIZE = 4096


class WebSocketHandler:
    _running = False

    _sock = None
    _ws = None

    def __init__(self):
        self._buffer = StringIO()

        self._read_lock = anyio.Lock()
        self._write_lock = anyio.Lock()

    def _save_data_to_buffer(self, data: str) -> None:
        self._buffer.write(data)

    def _read_buffer_data(self) -> str:
        self._buffer.seek(0)
        data = self._buffer.read()
        self._buffer.seek(0)
        self._buffer.truncate()
        return data

    async def _receive_event(self):
        async with self._read_lock:
            while True:
                if not self._running:
                    return wsproto.events.CloseConnection(code=500, reason="Resource is closed")

                event: wsproto.events.Event
                for event in self._ws.events():
                    if isinstance(event, wsproto.events.Message):
                        self._save_data_to_buffer(event.data)
                        if not event.message_finished:
                            continue
                        event = wsproto.events.TextMessage(
                            data=self._read_buffer_data(), frame_finished=True, message_finished=True)

                    return event

                if self._sock is None:
                    return wsproto.events.CloseConnection(code=500, reason="Socket is closed")

                data = await self._sock.receive(BUFFER_SIZE)
                if not data:
                    return wsproto.events.CloseConnection(code=500, reason="Socket is closed")
                self._ws.receive_data(data)

    async def _transmit_event(self, event: wsproto.events.Event) -> None:
        async with self._write_lock:
            out_data = self._ws.send(event)
            await self._sock.send(out_data)

    async def start(self, sock: anyio.abc.SocketStream) -> None:
        assert self._running == False
        self._running = True

        self._sock = sock
        self._ws = wsproto.WSConnection(wsproto.ConnectionType.SERVER)

        event = await self._receive_event()
        if not isinstance(event, wsproto.events.Request):
            raise ConnectionError("Invalid handshake message received", event)

        subprotocol = event.subprotocols[0] if event.subprotocols else None
        await self._transmit_event(wsproto.events.AcceptConnection(subprotocol=subprotocol))

    async def send(self, event: str, message_finished: bool = True):
        """
        Send the given text to the client.
        """
        await self._transmit_event(wsproto.events.TextMessage(data=event, message_finished=message_finished))

    async def aclose(self, code: int = 1006, reason: str = "Connection closed"):
        """
        Close all the resources.
        """
        if not self._running:
            return

        async with self._write_lock:
            async with self._read_lock:
                self._running = False

                try:
                    data = self._ws.send(
                        wsproto.events.CloseConnection(code=code, reason=reason))
                except wsproto.utilities.LocalProtocolError:
                    pass
                else:
                    await self._sock.send(data)

                await self._sock.aclose()

                self._sock = None
                self._ws = None
                self._buffer.seek(0)
                self._buffer.truncate()

    async def __aiter__(self):
        while self._running:
            event = await self._receive_event()
            if isinstance(event, wsproto.events.CloseConnection):
                return
            yield event


@asynccontextmanager
async def upgrade_to_websocket(sock) -> AsyncIterator[WebSocketHandler]:
    ws_handler = WebSocketHandler()
    await ws_handler.start(sock)
    yield ws_handler
    await ws_handler.aclose()
