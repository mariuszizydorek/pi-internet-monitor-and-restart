"""Minimal DNS A-query used to test public resolvers directly."""

from __future__ import annotations

import os
import socket


def response_has_answer(packet: bytes) -> bool:
    if len(packet) < 12:
        return False
    rcode = packet[3] & 0x0F
    ancount = int.from_bytes(packet[6:8], "big")
    return rcode == 0 and ancount > 0


def build_query(name: str) -> bytes:
    header = os.urandom(2) + b"\x01\x00" + b"\x00\x01" + b"\x00\x00" + b"\x00\x00" + b"\x00\x00"
    question = b"".join(_label(part) for part in name.strip(".").split(".")) + b"\x00"
    return header + question + b"\x00\x01" + b"\x00\x01"


def query_a(name: str, server: str, timeout: float) -> bool:
    packet = build_query(name)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (server, 53))
            reply, _ = sock.recvfrom(512)
        except OSError:
            return False
    return response_has_answer(reply)


def resolve_system(name: str, timeout: float) -> bool:
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        socket.getaddrinfo(name, 80, type=socket.SOCK_STREAM)
        return True
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(previous)


def _label(part: str) -> bytes:
    raw = part.encode("idna")
    if len(raw) > 63:
        raise ValueError(f"DNS label too long: {part}")
    return bytes([len(raw)]) + raw
