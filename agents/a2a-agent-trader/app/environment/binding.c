#include "market.h"

#define Env Market 
#include "../env_binding.h"

static int my_init(Env* env, PyObject* args, PyObject* kwargs) {
    env->episode_length = unpack(kwargs, "episode_length");
    env->max_job_duration = unpack(kwargs, "max_job_duration");
    env->energy_gen = unpack(kwargs, "energy_gen");
    env->energy_storage = unpack(kwargs, "energy_storage");
    env->max_nodes = unpack(kwargs, "max_nodes");
    env->max_space_tb = unpack(kwargs, "max_space_tb");
    env->buy_price_randomization = unpack(kwargs, "buy_price_randomization");
    env->job_efficiency_randomization = unpack(kwargs, "job_efficiency_randomization");
    env->reward_scale = unpack(kwargs, "reward_scale");
    env->space_tb_price = unpack(kwargs, "space_tb_price");
    env->a100_node_price = unpack(kwargs, "a100_node_price");
    env->a100_node_energy_kw = unpack(kwargs, "a100_node_energy_kw");
    env->h100_node_price = unpack(kwargs, "h100_node_price");
    env->h100_node_energy_kw = unpack(kwargs, "h100_node_energy_kw");
    env->energy_demand_base = unpack(kwargs, "energy_demand_base");
    env->energy_price_base = unpack(kwargs, "energy_price_base");
    env->energy_price_sensitivity = unpack(kwargs, "energy_price_sensitivity");
    env->energy_demand_threshold = unpack(kwargs, "energy_demand_threshold");
    env->a1 = unpack(kwargs, "a1");
    env->b1 = unpack(kwargs, "b1");
    env->a2 = unpack(kwargs, "a2");
    env->b2 = unpack(kwargs, "b2");
    env->a3 = unpack(kwargs, "a3");
    env->b3 = unpack(kwargs, "b3");
    init(env);
    return 0;
}

static int my_log(PyObject* dict, Log* log) {
    assign_to_dict(dict, "score", log->score);
    assign_to_dict(dict, "profit", log->profit);
    assign_to_dict(dict, "job_revenue", log->job_revenue);
    assign_to_dict(dict, "energy_revenue", log->energy_revenue);
    assign_to_dict(dict, "energy_expense", log->energy_expense);
    assign_to_dict(dict, "episode_length", log->episode_length);
    assign_to_dict(dict, "episode_return", log->episode_return);
    return 0;
}