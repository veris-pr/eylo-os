"""Single-attempt HTTP/2 transport; AWS's SDK still owns signing and event coding."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from aws_sdk_transcribe_streaming.config import Config
from awscrt.aio.http import AIOHttp2ClientConnection, AIOHttp2ClientStream
from awscrt.http import HttpHeaders, HttpRequest
from awscrt.io import ClientTlsContext, SocketOptions, TlsContextOptions
from smithy_core.aio.types import AsyncBytesProvider
from smithy_http import Field, Fields
from smithy_http.aio import HTTPResponse
from smithy_http.aio.interfaces import HTTPRequest

_HTTPS_PORT = 443
_CONNECT_TIMEOUT_MS = 5_000
_RESPONSE_WINDOW_BYTES = 65_536
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_INVALID_HEADER_VALUE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def _observe[T](task: asyncio.Future[T]) -> None:
    if not task.cancelled():
        task.exception()


class AmazonTranscribeHTTP2Transport:
    """Own one connection, request and writer, including late acquisition.

    Installed CRT 0.32.2's generic async stream has no request-body implementation;
    use its HTTP/2-specific connection/stream. No private SDK pool is inspected.
    Caller cancellation never cancels callback-owned CRT futures. ``close`` is
    idempotent and completes only after native shutdown and owned tasks settle.
    """

    TIMEOUT_EXCEPTIONS: tuple[type[Exception], ...] = (TimeoutError,)

    def __init__(self, *, tls_context: ClientTlsContext | None = None) -> None:
        self._tls = tls_context or ClientTlsContext(TlsContextOptions())
        self._body: AsyncBytesProvider | None = None
        self._connection: AIOHttp2ClientConnection | None = None
        self._connect: asyncio.Task[AIOHttp2ClientConnection] | None = None
        self._request: asyncio.Task[HTTPResponse] | None = None
        self._writer: asyncio.Task[object] | None = None
        self._completion: asyncio.Task[int] | None = None
        self._cleanup: asyncio.Task[None] | None = None

    def install(self, config: Config) -> None:
        """Install after per-operation config deepcopy; the owner keeps this identity."""
        config.transport = self

    async def send(self, request: HTTPRequest) -> HTTPResponse:
        if self._request is not None or self._cleanup is not None:
            raise RuntimeError("Transcribe transport accepts exactly one request.")
        self._request = asyncio.create_task(self._send(request))
        self._request.add_done_callback(_observe)
        return await asyncio.shield(self._request)

    async def _send(self, request: HTTPRequest) -> HTTPResponse:
        if self._cleanup is not None:
            raise RuntimeError("Transcribe transport is closing.")
        if request.destination.scheme != "https":
            raise ValueError("Transcribe transport requires HTTPS.")
        if not isinstance(request.body, AsyncBytesProvider):
            raise TypeError("Transcribe requires the SDK's streaming request buffer.")
        native_request = _native_request(request)
        self._body = request.body
        tls_options = self._tls.new_connection_options()
        tls_options.set_server_name(request.destination.host)
        tls_options.set_alpn_list(["h2"])
        socket_options = SocketOptions()
        socket_options.connect_timeout_ms = _CONNECT_TIMEOUT_MS
        self._connect = asyncio.create_task(
            AIOHttp2ClientConnection.new(
                host_name=request.destination.host,
                port=request.destination.port or _HTTPS_PORT,
                socket_options=socket_options,
                tls_connection_options=tls_options,
                manual_window_management=True,
                initial_window_size=_RESPONSE_WINDOW_BYTES,
            )
        )
        self._connect.add_done_callback(_observe)
        self._connection = await asyncio.shield(self._connect)
        if self._cleanup is not None:
            raise RuntimeError("Transcribe transport closed during connection setup.")
        stream = self._connection.request(
            native_request, request_body_generator=self._input_chunks(self._body)
        )
        self._completion = asyncio.create_task(stream.wait_for_completion())
        self._completion.add_done_callback(_observe)
        headers = asyncio.create_task(_response_headers(stream))
        try:
            await asyncio.wait(
                (headers, self._completion), return_when=asyncio.FIRST_COMPLETED
            )
            if headers.done():
                status, fields = headers.result()
                return HTTPResponse(
                    status=status, fields=fields, body=self._output_chunks(stream)
                )
            # Completion can fail before the native header futures resolve.
            await self._completion
            raise ConnectionError("Transcribe ended before sending response headers.")
        finally:
            if not headers.done():
                # Only reached after stream completion, never while callbacks can
                # still supply response headers. No live native future is cancelled.
                headers.cancel()
            await asyncio.gather(headers, return_exceptions=True)

    async def _input_chunks(self, body: AsyncBytesProvider) -> AsyncIterator[bytes]:
        # CRT creates the writer task; capture it through the public iterator it
        # invokes so a failed native write cannot become an unobserved task error.
        self._writer = asyncio.current_task()
        if self._writer is None:
            raise RuntimeError("Transcribe input requires an asyncio task.")
        self._writer.add_done_callback(_observe)
        async for chunk in body:
            yield chunk

    async def _output_chunks(
        self, stream: AIOHttp2ClientStream
    ) -> AsyncIterator[bytes]:
        while chunk := await stream.get_next_response_chunk():
            yield chunk
            stream.update_window(len(chunk))
        if self._completion is not None and self._completion.done():
            # Native chunk EOF alone also represents failed transport completion.
            self._completion.result()

    async def close(self) -> None:
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._close())
            self._cleanup.add_done_callback(_observe)
        await asyncio.shield(self._cleanup)

    async def _close(self) -> None:
        if self._body is not None:
            await self._body.close(flush=False)
        if self._connect is not None:
            try:
                self._connection = await asyncio.shield(self._connect)
            except Exception:
                # Failed acquisition has no native connection to dispose.
                pass
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                shutdown = self._connection.shutdown_future
                if not shutdown.done() or shutdown.cancelled():
                    raise
                # The shutdown future carries the reason the connection ended;
                # a completed error still proves physical shutdown finished.
        for task in (self._request, self._writer, self._completion):
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)


async def _response_headers(stream: AIOHttp2ClientStream) -> tuple[int, Fields]:
    status = await stream.get_response_status_code()
    fields = Fields()
    for name, value in await stream.get_response_headers():
        if name in fields:
            fields[name].add(value)
        else:
            fields[name] = Field(name=name, values=[value])
    return status, fields


def _native_request(request: HTTPRequest) -> HttpRequest:
    """Preserve signed headers/path and reject invalid header bytes before CRT."""
    headers: list[tuple[str, str]] = []
    for field in request.fields.entries.values():
        if field.kind != "header":
            continue
        if _HEADER_NAME.fullmatch(field.name) is None:
            raise ValueError("Transcribe request contains an invalid header name.")
        for value in field.values:
            if _INVALID_HEADER_VALUE.search(value) is not None:
                raise ValueError("Transcribe request contains an invalid header value.")
            headers.append((field.name, value))
    if "host" not in request.fields:
        headers.append(("host", request.destination.netloc))
    path = request.destination.path or "/"
    if request.destination.query is not None:
        path = f"{path}?{request.destination.query}"
    return HttpRequest(method=request.method, path=path, headers=HttpHeaders(headers))
