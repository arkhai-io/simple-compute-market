"""Smoke tests for the current Arkhai market environment integration."""

from __future__ import annotations

import numpy as np
import pytest


def _build_market_env():
    from pufferlib.ocean.arkhai.arkhai import Arkhai

    return Arkhai(
        num_envs=1,
        seed=42,
        node_types=3,
        ai_sellers=1,
        ai_buyers=0,
        scripted_sellers=0,
        scripted_buyers=3,
        episode_length=25,
        request_timeout=5,
        job_gpu_0_nodes=10,
        job_gpu_0_nodes_dr=0.2,
        job_gpu_1_nodes=10,
        job_gpu_1_nodes_dr=0.2,
        job_gpu_2_nodes=10,
        job_gpu_2_nodes_dr=0.2,
        job_duration=10,
        job_duration_dr=0.2,
        job_tb_usage=0.2,
        job_tb_usage_dr=0.2,
        job_efficiency=0.8,
        job_efficiency_dr=0.2,
        scripted_buy_price=0.9,
        scripted_buy_price_dr=0.2,
        scripted_sell_price=0.9,
        scripted_sell_price_dr=0.2,
        reward_scale=0.0001,
        tb_price=0.03,
        gpu_0_price=5.31,
        gpu_0_kw=6.5,
        gpu_1_price=15.92,
        gpu_1_kw=10.0,
        gpu_2_price=0.37,
        gpu_2_kw=1.0,
        energy_demand_base=1500.0,
        kwh_price_base=0.02,
        kwh_price_sensitivity=0.0000001,
        kwh_demand_threshold=1400,
        a1=-374,
        b1=-387,
        a2=-4.6,
        b2=-17.1,
        a3=3.2,
        b3=18.9,
        randomize_offset=1,
        preset=0,
        cluster_gpu_0_capacity=100,
        cluster_gpu_0_capacity_dr=0.2,
        cluster_gpu_1_capacity=100,
        cluster_gpu_1_capacity_dr=0.2,
        cluster_gpu_2_capacity=100,
        cluster_gpu_2_capacity_dr=0.2,
        cluster_tb_capacity=100,
        cluster_tb_capacity_dr=0.2,
        cluster_kwh_capacity=100,
        cluster_kwh_capacity_dr=0.2,
        cluster_kw_generation=10,
        cluster_kw_generation_dr=0.2,
    )


@pytest.fixture
def market_cls():
    from pufferlib.ocean.arkhai.arkhai import Arkhai

    return Arkhai


@pytest.fixture
def env():
    market_env = _build_market_env()
    try:
        yield market_env
    finally:
        market_env.close()


def test_market_import(market_cls) -> None:
    assert market_cls is not None


def test_market_initialization(env) -> None:
    assert env.num_agents >= 1
    assert env.single_observation_space is not None
    assert env.single_action_space is not None


def test_market_reset(env) -> None:
    observations, info = env.reset(seed=42)
    assert observations.shape[0] == env.num_agents
    assert observations.shape[1:] == env.single_observation_space.shape
    assert observations.dtype == np.float32
    assert isinstance(info, list)


def test_market_step(env) -> None:
    env.reset(seed=42)
    actions = np.array([[4, 0]] * env.num_agents, dtype=np.int32)
    observations, rewards, terminals, truncations, info = env.step(actions)

    assert observations.shape[0] == env.num_agents
    assert rewards.shape[0] == env.num_agents
    assert terminals.shape[0] == env.num_agents
    assert truncations.shape[0] == env.num_agents
    assert isinstance(info, list)


def test_market_multiple_steps(env) -> None:
    env.reset(seed=42)
    total_reward = 0.0

    for _ in range(5):
        actions = np.array([[4, 0]] * env.num_agents, dtype=np.int32)
        _, rewards, terminals, _, _ = env.step(actions)
        total_reward += float(rewards.sum())

        if bool(terminals.any()):
            env.reset(seed=42)

    assert np.isfinite(total_reward)
