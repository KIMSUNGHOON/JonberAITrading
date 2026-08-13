"""dev 런처의 빈 포트 스캔 (run_dev.find_free_port).

:8000을 타 프로젝트가 점유해도 백엔드가 에러로 죽지 않고 다음 빈 포트로
비켜 뜨게 한다 — FE dev 프록시(detectBackendOrigin)가 그 포트를 자동 탐지.
"""

import socket

from run_dev import find_free_port


def test_returns_start_port_when_free():
    # OS가 배정한 빈 포트를 얻어 닫은 직후 — start가 비어 있으면 그대로 반환
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    assert find_free_port(start=free_port, attempts=3) == free_port


def test_skips_occupied_port():
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        occupied = holder.getsockname()[1]
        holder.listen(1)
        chosen = find_free_port(start=occupied, attempts=5)
    assert chosen != occupied
    assert occupied < chosen <= occupied + 4


def test_raises_when_no_port_free():
    holders = []
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1]
        held = []
        for p in range(base, base + 3):
            sock = socket.socket()
            try:
                sock.bind(("127.0.0.1", p))
                sock.listen(1)
                held.append(p)
                holders.append(sock)
            except OSError:
                sock.close()
        if len(held) < 3:
            import pytest

            pytest.skip("could not occupy 3 consecutive ports on this host")
        try:
            find_free_port(start=base, attempts=3)
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError when all ports busy")
    finally:
        for sock in holders:
            sock.close()
