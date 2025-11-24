#include "market.h"

int main() {
    Market env = {
        .episode_length=1000,
        .max_job_duration=100,
        .energy_gen=10,
        .energy_storage=100,
        .max_nodes=100,
        .max_space_tb=100,
        .buy_price_randomization=0.2,
        .job_efficiency_randomization=0.2,
        .reward_scale=0.0001,
        .space_tb_price=0.03,
        .a100_node_price=5.31,
        .a100_node_energy_kw=6.5,
        .h100_node_price=15.92,
        .h100_node_energy_kw=10.0,
        .energy_demand_base=1500.0,
        .energy_price_base=20.0,
        .energy_price_sensitivity=0.0001,
        .energy_demand_threshold=1400,
        .a1=-374,
        .b1=-387,
        .a2=-4.6,
        .b2=-17.1,
        .a3=3.2,
        .b3=18.9,
    };
    init(&env);
    env.observations = (float*)calloc(14, sizeof(float));
    env.actions = (int*)calloc(2, sizeof(int));
    env.rewards = (float*)calloc(1, sizeof(float));
    env.terminals = (unsigned char*)calloc(1, sizeof(unsigned char));

    c_reset(&env);
    for (int i=0; i<10000000; i++) {
        env.actions[0] = 4;
        env.actions[1] = 0;
        c_step(&env);
        if (env.terminals[0]) {
            c_reset(&env);
        }
    }
    float n = env.log.n;
    printf("N: %f\n", n);
    printf("Profit: %f\n", env.log.profit/n);
    printf("Job Revenue: %f\n", env.log.job_revenue/n);
    printf("Energy Revenue: %f\n", env.log.energy_revenue/n);
    printf("Energy Expense: %f\n", env.log.energy_expense/n);
    printf("Episode Length: %f\n", env.log.episode_length/n);
    printf("Episode Return: %f\n", env.log.episode_return/n);
 
    free(env.observations);
    free(env.actions);
    free(env.rewards);
    free(env.terminals);
    c_close(&env);
}

