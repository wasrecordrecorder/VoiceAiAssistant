import argparse
import asyncio
import faulthandler
import sys
import traceback
from pathlib import Path

from .server import AssistantServer


def configure_diagnostics(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "backend.log"
    stream = log_path.open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    faulthandler.enable(file=stream)
    sys.excepthook = lambda exception_type, value, value_traceback: traceback.print_exception(exception_type, value, value_traceback, file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=48761)
    parser.add_argument("--token", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    configure_diagnostics(args.data_dir)
    print("WebViewDA backend starting", flush=True)
    server = AssistantServer(args.host, args.port, args.token, args.data_dir)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
