"""The Dramatiq worker on Valkey: jobs run, SIGTERM lets the running job finish, and the
logs are JSON lines on stdout.

The ping actor is bound to the test broker by the integration conftest. Each test starts
and ends with the ping keys and the broker's keys for the ping queue deleted (never
FLUSHALL), so a value left by an earlier run cannot pass a test.
"""

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import dramatiq
import pytest
from dramatiq import Message
from dramatiq.brokers.redis import RedisBroker
from redis import Redis

from app.workers.broker import NAMESPACE
from app.workers.jobs import ping
from tests.integration.conftest import collect_integration_tests

BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKER_KEY_PATTERNS = (
    "opennote:ping:*",
    f"{NAMESPACE}:{ping.queue_name}*",  # the queue, its messages, delay and dead-letter queues
    f"{NAMESPACE}:__acks__.*",
    f"{NAMESPACE}:__heartbeats__",
)
# The worker as the container starts it, and with forkserver forced: Python 3.14's default
# start method, under which worker processes inherit nothing from the main process.
WORKER_COMMANDS = {
    "python-m": ["-m", "app.workers"],
    "forkserver": [
        "-c",
        "import multiprocessing, runpy; multiprocessing.set_start_method('forkserver'); "
        "runpy.run_module('app.workers', run_name='__main__', alter_sys=True)",
    ],
}


def delete_worker_keys(client: Redis) -> None:
    for pattern in WORKER_KEY_PATTERNS:
        if keys := list(client.scan_iter(match=pattern)):
            client.delete(*keys)


def wait_until(condition: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def job_is_queued(token: str) -> bool:
    """True when a ping message for `token` waits in its queue again (requeued, not lost)."""
    client = cast(RedisBroker, ping.broker).client
    queue = f"{NAMESPACE}:{ping.queue_name}"
    return any(
        Message.decode(client.hget(f"{queue}.msgs", message_id)).args[0] == token
        for message_id in client.lrange(queue, 0, -1)
    )


class InProcessWorker:
    """A dramatiq Worker in the test process. join() returns once the ping queue is
    drained and the job in progress has finished."""

    def __init__(self, broker: dramatiq.Broker, worker: dramatiq.Worker) -> None:
        self.broker = broker
        self.worker = worker

    def join(self) -> None:
        # The timeout keeps a failing job (retried with backoff) from hanging the suite.
        self.broker.join(ping.queue_name, timeout=10_000)
        self.worker.join()


class WorkerProcess:
    """`python -m app.workers` in a subprocess, as the container runs it; its stdout and
    stderr go to files."""

    def __init__(
        self, process: subprocess.Popen[bytes], valkey: Redis, stdout: Path, stderr: Path
    ) -> None:
        self.process = process
        self.valkey = valkey
        self.stdout = stdout
        self.stderr = stderr

    def wait_job_started(self, token: str, timeout: float) -> bool:
        return wait_until(
            lambda: self.valkey.get(f"opennote:ping:{token}:started") == b"1", timeout
        )

    def sigterm(self) -> None:
        self.process.send_signal(signal.SIGTERM)

    def wait(self, timeout: float) -> int:
        return self.process.wait(timeout=timeout)

    def output(self) -> tuple[str, str]:
        return self.stdout.read_text(), self.stderr.read_text()


@pytest.fixture
def valkey(valkey_url: str) -> Iterator[Redis]:
    client = Redis.from_url(valkey_url)
    delete_worker_keys(client)
    yield client
    delete_worker_keys(client)
    client.close()


@pytest.fixture
def worker(valkey: Redis) -> Iterator[InProcessWorker]:
    worker = dramatiq.Worker(ping.broker, worker_timeout=100)
    worker.start()
    yield InProcessWorker(ping.broker, worker)
    worker.stop()


@pytest.fixture
def worker_valkey_url(valkey_url: str) -> str:
    """The worker process's OPENNOTE_VALKEY_URL; a test may parametrize it."""
    return valkey_url


@pytest.fixture(params=WORKER_COMMANDS.values(), ids=WORKER_COMMANDS.keys())
def worker_process(
    request: pytest.FixtureRequest, valkey: Redis, worker_valkey_url: str, tmp_path: Path
) -> Iterator[WorkerProcess]:
    stdout, stderr = tmp_path / "stdout", tmp_path / "stderr"
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(  # noqa: S603 - the commands are WORKER_COMMANDS
            [sys.executable, *request.param],
            cwd=BACKEND_DIR,
            env=os.environ | {"OPENNOTE_VALKEY_URL": worker_valkey_url},
            stdout=out,
            stderr=err,
            start_new_session=True,  # its own process group, for the kill below
        )
    worker = WorkerProcess(process, valkey, stdout, stderr)
    yield worker
    if process.poll() is None:  # the test failed before the worker stopped
        # The group: under forkserver the worker processes are not the main one's children.
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    print(*worker.output(), sep="\n")  # shown when the test fails


def test_ping_job_completes(worker, valkey):
    ping.send("t1")
    worker.join()
    assert valkey.get("opennote:ping:t1") == b"1"


def test_sigterm_during_job_exits_within_grace(worker_process, valkey):
    ping.send("t2", delay_seconds=2)
    assert worker_process.wait_job_started("t2", timeout=10)  # start barrier
    worker_process.sigterm()
    assert worker_process.wait(timeout=10) == 0
    assert valkey.get("opennote:ping:t2") == b"1" or job_is_queued("t2")


def test_ping_keys_expire_within_60_seconds(worker, valkey):
    ping.send("t1")
    worker.join()
    assert 0 < valkey.ttl("opennote:ping:t1") <= 60
    assert 0 < valkey.ttl("opennote:ping:t1:started") <= 60


def test_worker_logs_json_lines_on_stdout(worker_process, valkey_url):
    ping.send("t3")
    assert worker_process.wait_job_started("t3", timeout=10)
    worker_process.sigterm()
    assert worker_process.wait(timeout=10) == 0
    out, err = worker_process.output()
    records = [json.loads(line) for line in out.splitlines()]  # every line is JSON
    loggers = {record["logger"] for record in records}
    assert {"dramatiq.MainProcess", "dramatiq.WorkerProcess(0)"} <= loggers
    assert err == ""
    assert valkey_url not in out


# Nothing listens on port 9, so every connection is refused at once.
@pytest.mark.parametrize(
    "worker_valkey_url", [f"redis://:{secrets.token_hex(16)}@127.0.0.1:9/1"], ids=["dead"]
)
def test_worker_logs_no_valkey_password_when_valkey_is_unreachable(
    worker_process, worker_valkey_url
):
    password = urlsplit(worker_valkey_url).password
    assert wait_until(lambda: '"level": "CRITICAL"' in worker_process.output()[0], timeout=10)
    worker_process.sigterm()
    assert worker_process.wait(timeout=10) == 0
    out, err = worker_process.output()
    assert password
    assert password not in out
    assert password not in err


@pytest.mark.parametrize(
    "url",
    [
        "redis://127.0.0.1:6379/0",
        "redis://127.0.0.1:6379/-1",
        f"redis://:{secrets.token_hex(16)}@127.0.0.1:no-port/1",
    ],
    ids=["database-0", "negative-database", "invalid-with-password"],
)
def test_integration_tests_refuse_valkey_database_0_or_an_invalid_url(url):
    result = collect_integration_tests(OPENNOTE_TEST_VALKEY_URL=url)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "OPENNOTE_TEST_VALKEY_URL must" in result.stderr
    output = result.stdout + result.stderr
    assert url not in output
    password = urlsplit(url).password
    assert password is None or password not in output
