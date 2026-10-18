"""`python -m app.workers`: Dramatiq's command line, run in this process, with one worker
process of four threads on the Valkey broker.

On SIGTERM or SIGINT the main process passes SIGTERM to the worker process, which stops
taking messages, finishes the jobs in progress, puts prefetched messages back on their
queue and exits; the main process then exits 0.
"""

import sys

from dramatiq import cli

from app.core.config import SettingsError, get_settings
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
    # Wait at most 50 s for running jobs, inside the 60 s stop grace period the deployments
    # give the worker. A job still running then is killed with the process and delivered
    # again once the broker finds the worker dead (at-least-once).
    "--worker-shutdown-timeout",
    "50000",
    "--skip-logging",  # configure_logging, not Dramatiq's logging.basicConfig
]


def setup_worker_process() -> None:
    """Configure logging and the broker in a worker process. Needed wherever Dramatiq's
    start method is not fork (forkserver on Linux from Python 3.14, spawn on macOS): the
    worker processes then inherit neither from the main process."""
    settings = get_settings()
    # Dramatiq points sys.stdout at a pipe that its main process copies to stderr; the
    # JSON lines go to the real stdout instead, as everywhere else.
    configure_logging(settings.log_level, stream=sys.__stdout__)
    configure_broker(settings)


def main() -> None:
    # Settings are loaded here first, so invalid settings stop the worker before it starts
    # any process.
    try:
        settings = get_settings()
    except SettingsError as exc:
        # One line on stderr and exit status 1; the message names fields, never values.
        sys.exit(f"OpenNote worker cannot start: {exc}")
    configure_logging(settings.log_level)
    # dramatiq.cli has no type annotations.
    parser = cli.make_argument_parser()  # type: ignore[no-untyped-call]
    sys.exit(cli.main(parser.parse_args(DRAMATIQ_ARGS)))  # type: ignore[no-untyped-call]


if __name__ == "__main__":
    main()
