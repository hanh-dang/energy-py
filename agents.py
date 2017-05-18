import random
import itertools
import copy
import numpy as np
import pandas as pd
import assets.value_functions
import assets.utils


class Q_learner(object):

    def __init__(self, env, verbose, device):
        self.timer = assets.utils.Timer()
        self.verbose = verbose
        self.env = env
        input_length = len(self.env.s_mins) + len(self.env.a_mins)
        self.network = assets.value_functions.Dense_Q(input_length, device=device)
        self.batch_size = 64  # size of batch for sampling memory
        self.epochs = 500

        self.memory, self.network_memory, self.info = [], [], []
        self.save_csv = False

        self.epsilon = 1.0  # initial exploration factor
        self.policy_ = 0   # 0 = naive, 1 = e-greedy
        self.discount = 0.9  # discount factor for next_state
        self.test_state_actions = self.get_test_state_actions()

    def single_episode(self, episode_number):
        print('Starting episode ' + str(episode_number))
        state = self.env.reset()
        done = False
        while done is not True:
            state = self.env.state
            action, state_action, choice = self.policy(state)
            next_state, reward, done, env_info = self.env.step(action)

            self.memory.append([
                copy.copy(state),
                copy.copy(action),
                copy.copy(state_action),
                copy.copy(reward),
                copy.copy(next_state),
                copy.copy(episode_number),
                copy.copy(self.env.steps),
                copy.copy(self.epsilon),
                copy.copy(choice),
                copy.copy(done)])

            self.network_memory.append([
                copy.copy(self.normalize([state_action])),
                copy.copy(reward),
                self.state_to_state_actions(next_state),
                copy.copy(done)])

            if episode_number == 0:
                final_loss = 0

            elif episode_number > 0:
                hist = self.train_model()
                final_loss = hist.history['loss'][-1]
                self.epsilon = self.decay_epsilon(episode_number)

            self.info.append([
                self.timer.get_time(),
                np.mean(self.network.predict(self.test_state_actions)),
                final_loss])

            if self.verbose > 0:
                print('episode ' + str(episode_number) +
                      ' - step ' + str(self.env.steps) +
                      ' - choice ' + str(choice))
                print('state ' + str(state))
                print('last action was ' + str(self.env.last_actions))
                print('action ' + str(action))
                print('state action ' + str(state_action))
                print('next state ' + str(next_state))
                print('reward ' + str(reward) +
                      ' - epsilon ' + str(self.epsilon))
        print('Finished episode ' + str(episode_number))
        print('Total run time is ' + self.timer.get_time())
        return self

    def decay_epsilon(self, episode_number):
        # TODO harcoded to be at 0.1 after 25 episodes
        if self.epsilon != 0:
            self.epsilon = max(0.1, -0.0375 * episode_number + 1.0375)
        return self.epsilon

    def policy(self, state):
        if self.policy_ == 0:  # naive
            choice = 'NAIVE'
            action = [action_space.high for action_space in self.env.action_space]
        elif self.policy_ == 1:  # e-greedy
            if random.random() < self.epsilon:
                choice = 'RANDOM'
                action = [np.random.choice(np.array(action_space.sample()).flatten())
                          for action_space in self.env.action_space]
            else:
                choice = 'GREEDY'
                state_actions = self.state_to_state_actions(state)
                v_stack = np.vstack(state_actions)
                returns = self.network.predict(v_stack)
                optimal_state_action = list(state_actions[np.argmax(returns)].flatten())
                optimal_action = optimal_state_action[len(self.env.state):]
                normalized_action = copy.copy(optimal_action)
                lb, ub = self.env.a_mins, self.env.a_maxs
                denormalized_action = [
                    lb[i] + act * (ub[i] - lb[i])
                    for i, act in enumerate(normalized_action)
                    ]
                action = denormalized_action
                action = [int(act) for act in action]
        action = np.array(action).reshape(-1)
        state_action = np.concatenate([state, action])
        return action, state_action, choice

    def state_to_state_actions(self, state):
        action_space = self.env.create_action_space()
        bounds = []
        for asset in action_space:
            try:
                inner_bounds = []
                for action in asset.spaces:
                    rng = np.linspace(start=action.low,
                                      stop=action.high,
                                      num=(action.high - action.low) + 1)
                    inner_bounds.append(rng)
                inner_bounds = np.concatenate(inner_bounds)
                bounds.append(inner_bounds)
            except AttributeError:  # catches case that isn't Tuple
                rng = np.linspace(start=asset.low,
                                  stop=asset.high,
                                  num=(asset.high - asset.low) + 1)
                bounds.append(rng)

        actions = [np.array(tup) for tup in list(itertools.product(*bounds))]
        state_actions = [np.concatenate((state, a)) for a in actions]
        norm_state_actions = self.normalize(state_actions)
        return norm_state_actions

    def normalize(self, state_actions):
        mins, maxs = list(self.env.mins), list(self.env.maxs)
        norm_state_action, norm_state_actions = [], []
        for state_action in state_actions:
            length = len(state_action)

            for j, variable in enumerate(state_action):
                lb, ub = mins[j], maxs[j]
                normalized = (variable - lb) / (ub - lb)
                norm_state_action.append(normalized)

            norm_array = np.array(norm_state_action).reshape(-1, length)
            norm_state_actions.append(norm_array)
            norm_state_action = []
        norm_state_actions = np.array(norm_state_actions).reshape(-1,length)
        return norm_state_actions

    def train_model(self):
        if self.verbose > 0:
            print('Starting training')
        sample_size = min(len(self.network_memory), self.batch_size)
        memory_length = -50000
        batch = np.array(random.sample(self.network_memory[memory_length:],
                                       sample_size))
        features = np.hstack(batch[:, 0]).reshape(sample_size, -1)
        reward = batch[:, 1]
        next_state_actions = batch[:, 2]

        lengths = [np.vstack(item).shape[0] for item in next_state_actions]
        total_length = np.sum(lengths)
        start, stop = np.zeros(shape=len(lengths)), np.zeros(shape=len(lengths))
        unstacked = np.vstack(next_state_actions).reshape(total_length, -1)
        next_state_pred, num_not_unique = self.train_on_uniques(sa=unstacked)

        start, returns = 0, []
        for k in range(0, sample_size):
            stop = start + lengths[k]
            if batch[k, 3] is True:  # if last step
                rtn = 0
            else:
                rtn = np.max(next_state_pred[start:stop])
            start = stop
            returns.append(rtn)
        target = reward + returns
        X = features
        Y = target
        hist = self.network.fit(
            X, Y, epochs=self.epochs, batch_size=sample_size, verbose=self.verbose
            )

        return hist

    def train_on_uniques(self, sa):
        b = np.ascontiguousarray(sa).view(np.dtype(
            (np.void, sa.dtype.itemsize * sa.shape[1])))
        _, idx, inv = np.unique(b, return_index=True, return_inverse=True)
        uniques = sa[idx]
        unique_predictions = self.discount * self.network.predict(uniques)
        all_preds = unique_predictions[inv]
        pct_not_unique = 100 * (sa.shape[0] - uniques.shape[0]) / sa.shape[0]
        if self.verbose == 1:
            print('number of state actions ' + str(sa.shape[0]))
            print('number of unique ' + str(uniques.shape[0]))
            print('Pct not unique was {0:.0f}%'.format(pct_not_unique))
        return all_preds, pct_not_unique

    def get_test_state_actions(self):
        Q_test = pd.read_csv('assets/Q_test.csv', index_col=[0])
        Q_test.iloc[:, 1:] = Q_test.iloc[:, 1:].apply(pd.to_numeric)
        test_state_actions = np.array(Q_test.iloc[:, 1:])
        test_state_actions = self.normalize(test_state_actions)
        return test_state_actions
