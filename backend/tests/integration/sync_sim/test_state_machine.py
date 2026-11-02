"""The same world driven by Hypothesis rules, so a failing run shrinks to a short list of
actions (testing strategy §4). The seeded runs cover breadth; this covers minimal repros."""

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, run_state_machine_as_test

from tests.integration.sync_sim.invariants import check_idempotent, check_invariants, check_no_loops
from tests.integration.sync_sim.world import CRASH_POINTS, World

pytestmark = pytest.mark.sync_sim
CLIENTS = 3
client_index = st.integers(0, CLIENTS - 1)


def test_rule_based_sync_holds_the_invariants(sim_engine, tmp_path):
    class SyncMachine(RuleBasedStateMachine):
        def __init__(self) -> None:
            super().__init__()
            self.dir = tempfile.TemporaryDirectory(dir=tmp_path)
            self.world = World(0, sim_engine, Path(self.dir.name), CLIENTS)

        @rule(i=client_index, attachment=st.booleans())
        def create(self, i, attachment):
            self.world.clients[i].create(attachment=attachment)

        @rule(i=client_index)
        def edit(self, i):
            self.world.clients[i].edit()

        @rule(i=client_index)
        def move(self, i):
            self.world.clients[i].move()

        @rule(i=client_index)
        def delete(self, i):
            self.world.clients[i].delete()

        @rule(i=client_index)
        def sync(self, i):
            self.world.clients[i].sync()

        @rule(i=client_index)
        def toggle_online(self, i):
            c = self.world.clients[i]
            c.online = not c.online

        @rule(i=st.integers(-1, CLIENTS - 1))
        def external_edit(self, i):
            w = self.world
            w.external_edit(w.server_root if i < 0 else w.clients[i].root)

        @rule()
        def server_scan(self):
            self.world.server_scan()

        @rule(point=st.sampled_from(CRASH_POINTS))
        def arm_crash(self, point):
            self.world.crash_next = point

        def teardown(self) -> None:
            try:
                self.world.quiesce()
                violations = check_invariants(self.world) + check_no_loops(self.world)
                violations += check_idempotent(self.world)
                assert not violations, violations
            finally:
                self.world.close()
                self.dir.cleanup()

    run_state_machine_as_test(
        SyncMachine,
        settings=settings(
            max_examples=25,
            stateful_step_count=30,
            deadline=None,
            suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
        ),
    )
