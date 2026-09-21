import asyncio

import pytest

from simsland_mw.data.provider import DataProvider, MissingDependency
from simsland_mw.data.registry import Registry, UnknownDataType, build_default_registry
from simsland_mw.data.resolver import DependencyCycle, Resolver, TTLCache


async def _const(ctx, v=1):
    return v


def _reg(*specs):
    return Registry(DataProvider(t, _const, depends_on=tuple(d)) for t, d in specs)


def test_plan_orders_waves_by_dependency():
    r = Resolver(_reg(("a", []), ("b", ["a"]), ("c", ["a"]), ("d", ["b", "c"])))
    assert r.plan(["d"]) == [["a"], ["b", "c"], ["d"]]


def test_plan_expands_transitive_dependencies():
    r = Resolver(build_default_registry())
    waves = r.plan(["environment.nearby_characters"])
    assert waves == [["character.location"], ["environment.nearby_characters"]]


def test_cycle_and_unknown_type():
    with pytest.raises(DependencyCycle):
        Resolver(_reg(("a", ["b"]), ("b", ["a"]))).plan(["a"])
    with pytest.raises(UnknownDataType):
        Resolver(_reg(("a", []))).plan(["nope"])


async def test_duplicate_registration_rejected():
    reg = _reg(("a", []))
    with pytest.raises(ValueError):
        reg.register(DataProvider("a", _const))


async def test_wave_runs_concurrently(sim):
    running, peak = 0, 0

    async def slow(ctx):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return True

    reg = Registry(DataProvider(t, slow) for t in "abc")
    await Resolver(reg).resolve(["a", "b", "c"], sim, "kim")
    assert peak == 3


async def test_section_fetched_once_per_decision(sim):
    res = await Resolver(build_default_registry()).resolve(
        ["character.identity", "character.body", "character.traits", "character.intentions"], sim, "kim")
    assert not res.errors
    assert sim.snapshot_calls == [["character"]]  # four providers, one HTTP call


async def test_failure_is_isolated_and_skips_dependents(sim):
    async def boom(ctx):
        raise RuntimeError("simsland hiccup")

    async def needs_a(ctx):
        return ctx.dep("a")

    reg = Registry([DataProvider("a", boom), DataProvider("b", needs_a, depends_on=("a",)),
                    DataProvider("ok", _const)])
    res = await Resolver(reg).resolve(["b", "ok"], sim, "kim")
    assert res.values == {"ok": 1}
    assert "hiccup" in res.errors["a"] and "dependency failed" in res.errors["b"]


async def test_undeclared_dependency_is_an_error(sim):
    async def sneaky(ctx):
        return ctx.dep("a")

    reg = Registry([DataProvider("a", _const), DataProvider("b", sneaky)])  # forgot depends_on
    res = await Resolver(reg).resolve(["a", "b"], sim, "kim")
    assert "MissingDependency" in res.errors["b"] or "not resolved" in res.errors["b"]


async def test_ttl_cache_serves_slow_data_and_expires(sim):
    now = [0.0]
    r = Resolver(build_default_registry(), TTLCache(clock=lambda: now[0]))
    first = await r.resolve(["character.traits"], sim, "kim")
    assert first.cache_hits == []
    second = await r.resolve(["character.traits"], sim, "kim")
    assert second.cache_hits == ["character.traits"]
    now[0] = 301
    third = await r.resolve(["character.traits"], sim, "kim")
    assert third.cache_hits == []


async def test_volatile_types_never_cached(sim):
    r = Resolver(build_default_registry())
    await r.resolve(["character.body"], sim, "kim")
    again = await r.resolve(["character.body"], sim, "kim")
    assert again.cache_hits == []
