"""One entry per seed the simulation found failing, kept after its fix (CLAUDE.md §9).
Each runs with the parameters it failed under."""

import pytest

from tests.integration.sync_sim.invariants import run_seed

pytestmark = pytest.mark.sync_sim

# seed: what failed
REGRESSIONS = {
    60: "a server move whose source folder was gone raised FileNotFoundError",
    82: "harness: an edit on the server's disk absorbed by a commit was not counted as one "
    "side's content, so its conflict copy looked invented",
    102: "harness: a rejected move of a deleted file hid the live file now at that path from I3",
    347: "harness: a pull that revived a deleted file overwrote another local file at its path",
    434: "harness: a superseded delete wrote the revived file over another local file at its path",
    583: "harness: a retried conflict result recreated a conflict copy the client had moved",
    667: "a create onto an unscanned server file absorbed it as a revision of the new file",
    4461: "harness: a move that waited for its target to be freed was never finished",
    6096: "harness: a file stayed marked rejected after a later edit of it won and was applied",
    6575: "harness: a deleted file's stale override let an older pull entry bring it back",
    8112: "harness: as 4461, a deferred relocation after a rejected move",
}


@pytest.mark.parametrize("seed", sorted(REGRESSIONS), ids=lambda s: f"seed{s}")
def test_regression_seed(seed, sim_engine, tmp_path):
    report = run_seed(seed, clients=3, steps=40, engine=sim_engine, tmp=tmp_path)
    assert not report.violations, report.describe()
