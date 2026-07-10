#!/usr/bin/env python3
"""Minimal Source-RCON client library for driving the headless Factorio server."""
import socket, struct

SERVERDATA_AUTH, SERVERDATA_EXECCOMMAND = 3, 2


class Rcon:
    def __init__(self, host, port, pw):
        self.s = socket.create_connection((host, port), timeout=10)
        self.i = 0
        self._send(SERVERDATA_AUTH, pw)
        # Factorio sends an empty RESPONSE_VALUE (type 0) then the AUTH_RESPONSE
        # (type 2). Drain until we see the auth response, or auth fails (-1).
        while True:
            rid, typ, _ = self._recv()
            if typ in (2, 3):
                if rid == -1:
                    raise SystemExit("RCON auth failed")
                break

    def _send(self, typ, body):
        self.i += 1
        payload = struct.pack("<ii", self.i, typ) + body.encode() + b"\x00\x00"
        self.s.sendall(struct.pack("<i", len(payload)) + payload)
        return self.i

    def _recv(self):
        (ln,) = struct.unpack("<i", self._recvn(4))
        data = self._recvn(ln)
        rid, typ = struct.unpack("<ii", data[:8])
        return rid, typ, data[8:-2].decode(errors="replace")

    def _recvn(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise SystemExit("RCON connection closed")
            buf += chunk
        return buf

    def cmd(self, s):
        self._send(SERVERDATA_EXECCOMMAND, s)
        return self._recv()[2]

    def lua(self, code):
        """Run a multi-line Lua chunk as a silent-command (newlines preserved so
        `--` comments don't swallow the rest of the line)."""
        return self.cmd("/silent-command " + code.strip())
