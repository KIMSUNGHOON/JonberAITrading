"""개발용 백엔드 런처 — 점유된 포트를 자동으로 비켜 뜬다.

이 머신에서는 :8000을 다른 프로젝트(예: AgentHub)가 점유하는 일이 잦다.
uvicorn을 직접 쓰면 그 경우 기동이 실패하므로, 8000부터 빈 포트를 스캔해
기동한다. FE dev 프록시(frontend vite.config의 detectBackendOrigin)가
같은 범위를 스캔해 이 서버를 자동으로 찾아 연결한다.

실행 (backend/ 에서):
    python run_dev.py [--reload] [--start-port 8000]
"""

import argparse
import socket


def find_free_port(start: int = 8000, attempts: int = 6) -> int:
    """start부터 attempts개 포트를 스캔해 첫 빈 포트를 반환한다."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"포트 {start}~{start + attempts - 1}가 전부 점유되어 있습니다"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="dev backend launcher")
    parser.add_argument("--reload", action="store_true", help="uvicorn --reload")
    parser.add_argument("--start-port", type=int, default=8000)
    args = parser.parse_args()

    port = find_free_port(start=args.start_port)
    if port != args.start_port:
        print(f"[run_dev] :{args.start_port} 점유됨 → :{port} 로 기동합니다 "
              f"(FE dev 프록시가 자동 탐지)")

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=args.reload)


if __name__ == "__main__":
    main()
