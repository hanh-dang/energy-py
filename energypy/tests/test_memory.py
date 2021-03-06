import numpy as np

import energypy


def test_load_pickle_memory():
    env = energypy.make_env('cartpole-v0')

    mem = energypy.make_memory(
        memory_id='array', env=env)

    state = env.observation_space.sample()
    action = env.action_space.sample()
    reward = 1
    next_state = env.observation_space.sample()
    done = False

    experience = state, action, reward, next_state, done

    mem.remember(*experience)

    mem.save('./results/test_mem.pkl')

    new_mem = energypy.make_memory(
        load_path='./results/test_mem.pkl'
    )

    saved_exp = new_mem[0]

    for exp, saved in zip(experience, saved_exp):

        exp, saved = np.array(exp), np.array(saved)

        np.testing.assert_equal(exp, saved)
