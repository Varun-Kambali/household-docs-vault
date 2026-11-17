import pytest

from household_vault.secrets.gate import SecretsGate
from household_vault.secrets.store import SecretsLocked, SecretsStore
from household_vault.vaultroot import SECRETS_FILE
from tests.conftest import MASTER_PASSWORD, FakeClock


def test_the_gate_forgets_after_ten_minutes(vault):
    clock = FakeClock(0.0)
    gate = SecretsGate(vault, clock)
    gate.create(MASTER_PASSWORD)
    clock.t = 601.0
    with pytest.raises(SecretsLocked):
        gate.store()


def test_the_gate_is_open_until_the_time_is_up(vault):
    clock = FakeClock(100.0)
    gate = SecretsGate(vault, clock)
    assert not gate.is_open()
    gate.create(MASTER_PASSWORD)
    clock.t = 700.0
    assert gate.is_open() and gate.store().version[0] == 4
    clock.t = 700.5
    assert not gate.is_open()


def test_unlock_needs_the_right_password_and_lock_closes(vault):
    SecretsStore.create(vault, MASTER_PASSWORD)
    gate = SecretsGate(vault, FakeClock(0.0))
    with pytest.raises(SecretsLocked):
        gate.unlock("wrong")
    assert not gate.is_open()
    gate.unlock(MASTER_PASSWORD)
    assert gate.is_open()
    gate.lock()
    assert not gate.is_open()
    with pytest.raises(SecretsLocked):
        gate.store()


def test_unlocking_again_restarts_the_ten_minutes(vault):
    clock = FakeClock(0.0)
    gate = SecretsGate(vault, clock, unlock_seconds=60.0)
    gate.create(MASTER_PASSWORD)
    clock.t = 50.0
    gate.unlock(MASTER_PASSWORD)
    clock.t = 100.0
    assert gate.is_open()
    clock.t = 111.0
    assert not gate.is_open()


def test_an_expired_gate_lets_go_of_the_store(vault):
    clock = FakeClock(0.0)
    gate = SecretsGate(vault, clock, unlock_seconds=10.0)
    gate.create(MASTER_PASSWORD)
    clock.t = 11.0
    assert not gate.is_open()
    assert gate._store is None  # nothing stays in memory after the time is up


def test_the_gate_never_writes_the_password(vault):
    gate = SecretsGate(vault, FakeClock(0.0))
    gate.create(MASTER_PASSWORD)
    assert MASTER_PASSWORD.encode() not in vault.read_bytes(SECRETS_FILE)
    assert MASTER_PASSWORD not in repr(gate)
