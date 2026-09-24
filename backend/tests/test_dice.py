import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.dice import roll


def test_simple_roll():
    r = roll("2d6+3", rng=random.Random(0))
    assert len(r.rolls) == 2
    assert all(1 <= x <= 6 for x in r.rolls)
    assert r.total == sum(r.rolls) + 3


def test_flat_number():
    assert roll("5").total == 5


def test_advantage_keeps_highest():
    r = roll("1d20adv", rng=random.Random(1))
    assert len(r.rolls) == 2
    assert r.kept == [max(r.rolls)]


def test_keep_highest():
    r = roll("4d6kh3", rng=random.Random(2))
    assert len(r.rolls) == 4
    assert len(r.kept) == 3
    assert r.kept == sorted(r.rolls, reverse=True)[:3]


def test_bad_expression():
    import pytest
    with pytest.raises(ValueError):
        roll("fireball")
