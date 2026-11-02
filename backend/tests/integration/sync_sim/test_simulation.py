"""Seeded multi-client runs (sync protocol §13): SYNC_SIM_SEEDS seeds from
SYNC_SIM_SEED_START (500 by default, 10,000 nightly and with `make sync-sim`)."""

import datetime as dt

import pytest

from tests.integration.sync_sim.conftest import SEED_START, SEEDS
from tests.integration.sync_sim.invariants import run_seed

pytestmark = pytest.mark.sync_sim
CHUNK = 50
CLIENTS, STEPS = 3, 40


@pytest.mark.parametrize(
    "start", range(SEED_START, SEED_START + SEEDS, CHUNK), ids=lambda s: f"seeds{s}"
)
def test_seeds_hold_the_invariants(start, sim_engine, tmp_path):
    failures = []
    for seed in range(start, min(start + CHUNK, SEED_START + SEEDS)):
        report = run_seed(seed, clients=CLIENTS, steps=STEPS, engine=sim_engine, tmp=tmp_path)
        if report.violations:
            failures.append(report.describe())
    assert not failures, "\n\n".join(failures)


@pytest.mark.parametrize("seed", [SEED_START, SEED_START + 1, SEED_START + 2])
def test_clock_skew_changes_nothing_but_informational_fields(seed, sim_engine, tmp_path):
    normal = run_seed(seed, clients=CLIENTS, steps=STEPS, engine=sim_engine, tmp=tmp_path)
    skewed = run_seed(
        seed,
        clients=CLIENTS,
        steps=STEPS,
        engine=sim_engine,
        tmp=tmp_path,
        clock_skew=dt.timedelta(days=-400, hours=7),
    )
    assert skewed.state == normal.state  # I6
