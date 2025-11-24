'''Market seller-side cloud market environment'''

import gymnasium
import numpy as np

import pufferlib

# Try to import binding from local build first, then fall back to pufferlib's
try:
    from . import binding
except ImportError:
    try:
        from pufferlib.ocean.market import binding
    except ImportError:
        raise ImportError(
            "Could not import Market binding. Please build the C extension:\n"
            "  cd app/environment && uv run python build_binding.py\n"
            "Or ensure pufferlib.ocean.market.binding is available."
        )

class Market(pufferlib.PufferEnv):
    def __init__(self, num_envs=1, render_mode=None, log_interval=128, buf=None, seed=0,
            episode_length=1000, max_job_duration=100,
            energy_gen=10, energy_storage=100, max_nodes=100, max_space_tb=100,
            buy_price_randomization=0.2, job_efficiency_randomization=0.2,
            reward_scale=0.0001, space_tb_price=0.03,
            a100_node_price=5.31, a100_node_energy_kw=6.5,
            h100_node_price=15.92, h100_node_energy_kw=10.0,
            energy_demand_base=1500.0, energy_price_base=20.0,
            energy_price_sensitivity=0.0001, energy_demand_threshold=1400,
            a1=-374, b1=-387, a2=-4.6, b2=-17.1, a3=3.2, b3=18.9):
        self.single_observation_space = gymnasium.spaces.Box(low=0, high=1,
            shape=(14,), dtype=np.float32)
        self.single_action_space = gymnasium.spaces.MultiDiscrete([9, 2])
        self.render_mode = render_mode
        self.num_agents = num_envs

        super().__init__(buf)
        self.c_envs = binding.vec_init(self.observations, self.actions, self.rewards,
            self.terminals, self.truncations, num_envs, seed,
            episode_length=episode_length,
            max_job_duration=max_job_duration,
            energy_gen=energy_gen,
            energy_storage=energy_storage,
            max_nodes=max_nodes,
            max_space_tb=max_space_tb,
            buy_price_randomization=buy_price_randomization,
            job_efficiency_randomization=job_efficiency_randomization,
            reward_scale=reward_scale,
            space_tb_price=space_tb_price,
            a100_node_price=a100_node_price,
            a100_node_energy_kw=a100_node_energy_kw,
            h100_node_price=h100_node_price,
            h100_node_energy_kw=h100_node_energy_kw,
            energy_demand_base=energy_demand_base,
            energy_price_base=energy_price_base,
            energy_price_sensitivity=energy_price_sensitivity,
            energy_demand_threshold=energy_demand_threshold,
            a1=a1, b1=b1, a2=a2, b2=b2, a3=a3, b3=b3,
        )
 
    def reset(self, seed=0):
        binding.vec_reset(self.c_envs, seed)
        return self.observations, []

    def step(self, actions):
        self.actions[:] = actions
        binding.vec_step(self.c_envs)
        info = [binding.vec_log(self.c_envs)]
        return (self.observations, self.rewards,
            self.terminals, self.truncations, info)

    def render(self):
        binding.vec_render(self.c_envs, 0)

    def close(self):
        binding.vec_close(self.c_envs)

if __name__ == '__main__':
    N = 4096
    env = Market(num_envs=N)
    env.reset()
    steps = 0

    CACHE = 1024
    actions = np.random.randn(CACHE, N, env.single_action_space.shape[0])

    import time
    start = time.time()
    while time.time() - start < 10:
        env.step(actions[steps % CACHE])
        steps += 1

    print('Squared SPS:', int(env.num_agents*steps / (time.time() - start)))

