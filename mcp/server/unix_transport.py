"""Serve the official MCP stdio protocol over a private Unix socket.

SSH clients use socat to connect their stdio to this socket. Each connection
gets its own SDK session while sharing the HTTP server's Python runtime.
"""

import asyncio
import errno
import fcntl
import logging
import os
import socket
import stat
from pathlib import Path

from mcp.server.stdio import stdio_server

LOG = logging.getLogger(__name__)
MAX_LINE_BYTES = 1024 * 1024
MAX_CONNECTIONS = 32


class _SocketInput:
    """The async text iterator consumed by the SDK's stdin reader."""

    def __init__(self, reader):
        self.reader = reader

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            line = await self.reader.readuntil(b'\n')
        except asyncio.IncompleteReadError as error:
            line = error.partial
            if not line:
                raise StopAsyncIteration from None
        if len(line) > MAX_LINE_BYTES:
            raise ValueError('MCP message exceeds the Unix transport limit.')
        return line.decode('utf-8')


class _SocketOutput:
    """The write/flush interface consumed by the SDK's stdout writer."""

    def __init__(self, writer):
        self.writer = writer

    async def write(self, text):
        self.writer.write(text.encode('utf-8'))

    async def flush(self):
        await self.writer.drain()


def _prepare_directory(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError('Unix socket directory must be a directory owned by the server user.')
    directory.chmod(0o700)


def _remove_stale_socket(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError('Refusing to replace an unowned socket or a non-socket path.')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        result = probe.connect_ex(str(path))
    if result != errno.ECONNREFUSED:
        raise RuntimeError('Unix socket is active or its status cannot be established safely.')
    # The caller holds the transport lock. Verify the entry was not replaced.
    current = path.lstat()
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise RuntimeError('Unix socket changed during the stale socket check.')
    path.unlink()


async def _serve_connection(mcp, reader, writer):
    from fastmcp.server.context import reset_transport, set_transport

    token = set_transport('stdio')
    try:
        async with mcp._lifespan_manager():
            async with stdio_server(stdin=_SocketInput(reader), stdout=_SocketOutput(writer)) as streams:
                await mcp._mcp_server.run(
                    streams[0], streams[1],
                    mcp._mcp_server.create_initialization_options(),
                )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        # Do not log exception text: validation errors can contain chat content.
        LOG.warning('Unix MCP connection ended (%s).', type(error).__name__)
    finally:
        reset_transport(token)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=1)
        except (OSError, asyncio.TimeoutError):
            pass


async def run_unix_server(mcp, path):
    """Run a private listener until cancelled; remove only its own socket.

    Call this in the same event loop as the HTTP server. The directory must
    belong to the process user; SSH access is the authentication boundary.
    """
    path = Path(path).absolute()
    _prepare_directory(path.parent)
    lock_fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    server = None
    owned = None
    connections = set()
    try:
        lock_info = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid():
            raise RuntimeError('Unix transport lock must be an owned regular file.')
        os.fchmod(lock_fd, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another Unix MCP listener owns this path.') from None
        _remove_stale_socket(path)

        def accepted(reader, writer):
            if len(connections) >= MAX_CONNECTIONS:
                writer.close()
                return
            task = asyncio.create_task(_serve_connection(mcp, reader, writer))
            connections.add(task)
            task.add_done_callback(connections.discard)

        server = await asyncio.start_unix_server(
            accepted, path=str(path), limit=MAX_LINE_BYTES, start_serving=False,
        )
        info = path.lstat()
        owned = (info.st_dev, info.st_ino)
        path.chmod(0o600)
        await server.start_serving()
        LOG.info('Private Unix MCP listener ready.')
        await server.serve_forever()
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()
        running = list(connections)
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        if owned is not None:
            try:
                info = path.lstat()
                if (info.st_dev, info.st_ino) == owned:
                    path.unlink()
            except FileNotFoundError:
                pass
        os.close(lock_fd)
