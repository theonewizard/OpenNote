"""`python -m app.workers`: Dramatiq's command line, run in this process, with one worker
process of four threads on the Valkey broker.

On SIGTERM or SIGINT the main process passes SIGTERM to the worker process, which stops
taking messages, finishes the jobs in progress, puts prefetched messages back on their
queue and exits; the main process then exits 0.
"""

import sys

from dramatiq import cli

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers.broker import configure_broker

DRAMATIQ_ARGS = [
    # Dramatiq calls this first in each worker process, then imports the jobs.
    "app.workers.__main__:setup_worker_process",
    "app.workers.jobs",
    "--processes",
    "1",
    "--threads",
    "4",
    "--skip-logging",  # configure_logging, not Dramatiq's logging.basicConfig
]


def setup_worker_process() -> None:
    """Configure logging and the broker in a worker process. Since Python 3.14 Dramatiq
    starts worker processes with forkserver, so they inherit neither from the main
    process."""
    settings = get_settings()
    # Dramatiq points sys.stdout at a pipe that its main process copies to stderr; the
    # JSON lines go to the real stdout instead, as everywhere else.
    configure_logging(settings.log_level, stream=sys.__stdout__)
    configure_broker(settings)


def main() -> None:
    # Settings are loaded here first, so invalid settings stop the worker before it starts
    # any process.
    configure_logging(get_settings().log_level)
    # dramatiq.cli has no type annotations.
    parser = cli.make_argument_parser()  # type: ignore[no-untyped-call]
    sys.exit(cli.main(parser.parse_args(DRAMATIQ_ARGS)))  # type: ignore[no-untyped-call]


if __name__ == "__main__":
    main()
