import logging
import os

import numpy as np

from energy_py.agents import BaseAgent, EpsilonGreedy


class DQN(BaseAgent):
    """
    energy_py implementation of DQN
    aka Q-learning with experience replay & target network

    args
        env                 : energy_py environment
        Q                   : energy_py Action-Value Function Q(s,a)
        discount
        batch_size
        memory_length       : int : length of experience replay
        epsilon_decay_steps : int
        epsilon_start       : int
        update_target_net   : int : steps before target network update
        scale_targets       : bool : whether to scale Q(s,a) when learning

    inherits from
        Base_Agent          : the energy_py class used for agents

    Based on the DeepMind Atari work
    Reference = Mnih et. al (2013), Mnih et. al (2015)
    """
    def __init__(self, 
                 env,
                 discount,

                 Q,
                 batch_size,
                 brain_path,

                 memory_length=100000,
                 epsilon_decay_steps=10000,
                 epsilon_start=1.0,
                 update_target_net=1000,
                 scale_targets=True,
                 load_agent_brain=False,
                 
                 process_reward=False,
                 process_return=False):

        #  passing the environment to the BaseAgent class
        super().__init__(env, discount, brain_path, process_reward, process_return)

        Q = Q
        batch_size = batch_size
        load_agent_brain = load_agent_brain

        self.update_target_net = update_target_net
        self.scale_targets = scale_targets

        #  setup self.scaled_actions (used by all_state_actions method)
        self.scaled_actions = self.setup_all_state_actions(spc_len=20)

        #  model dict gets passed into the Action-Value function objects
        model_dict = {'type' : 'feedforward',
                      'input_dim' : self.observation_dim + self.num_actions,
                      'layers'    : [25, 25],
                      'output_dim': 1,
                      'lr'        : 0.001,
                      'batch_size': batch_size,
                      'epochs'    : 1}

        #  make our two action value functions
        self.Q_actor = Q(model_dict)
        self.Q_target = Q(model_dict)

        #  create an object to decay epsilon
        self.e_greedy = EpsilonGreedy(decay_steps=epsilon_decay_steps,
                                      epsilon_start=epsilon_start)

        if load_agent_brain:
            self.load_brain()

    def _reset(self):
        """
        Resets the agent
        """
        self.Q_actor.model.reset_weights()
        self.Q_target.model.reset_weights()
        self.e_greedy.reset()

    def _act(self, observation):
        """
        Act using an epsilon-greedy policy

        args
            observation : np array (1, observation_dim)

        return
            action      : np array (1, num_actions)
        """
        #  because our observation comes directly from the env
        #  we need to scale the observation
        observation = self.scale_array(observation, self.observation_space)

        #  get the current value of epsilon
        epsilon = self.e_greedy.epsilon
        self.memory.agent_stats['epsilon'].append(epsilon)

        if np.random.uniform() < epsilon:
            logging.info('epsilon {:.3f} - acting randomly'.format(epsilon))
            action = [space.sample() for space in self.action_space]

        else:

            #  create all possible combinations of our single observation
            #  and our n-dimensional action space
            state_acts, acts = self.all_state_actions(observation)

            #  get predictions from the action_value function Q
            Q_estimates = [self.Q_actor.predict(sa.reshape(1,-1))
                           for sa in state_acts]

            #  select the action with the highest Q
            #  note that we index the unscaled action
            #  as this action is sent directly to the environment
            action = acts[np.argmax(Q_estimates)]
            max_Q = np.max(Q_estimates)
            logging.info('epsilon {:.3f} - using Q_actor - max(Q_est)={:.3f}'.format(epsilon, max_Q))

            #  save the Q estimates
            self.memory.agent_stats['acting max Q estimates'].append(max_Q)

        action = np.array(action).reshape(1, self.num_actions)
        assert len(self.action_space) == action.shape[1]

        return action

    def _learn(self, **kwargs):
        """
        Update Q_actor using the Bellman Equation

        observations, actions, rewards should all be either
        normalized or standardized

        args
            observations        : np array (batch_size, observation_dim)
            actions             : np array (batch_size, num_actions)
            rewards             : np array (batch_size, 1)
            next_observations   : np array (batch_size, observataion_dim)

        returns
            history             : list
        """
        observations = kwargs.pop('observations')
        actions = kwargs.pop('actions')
        rewards = kwargs.pop('rewards')
        next_observations = kwargs.pop('next_observations')

        #  check that we have equal number of all of our inputs
        assert observations.shape[0] == actions.shape[0]
        assert observations.shape[0] == rewards.shape[0]
        assert observations.shape[0] == next_observations.shape[0]

        #  iterate over the experience to create the input and target
        inputs = np.zeros(shape=(observations.shape[0],
                                 self.observation_dim + self.num_actions))
        targets = np.array([])
        logging.info('starting input & target creation')
        for j, (obs, act, rew, next_obs) in enumerate(zip(observations,
                                                          actions,
                                                          rewards,
                                                          next_observations)):
            #  first the inputs
            inputs[j] = np.append(obs, act)

            #  second the targets
            #  TODO this is a bit hacky (maybe have s'='TERMINAL' or something?)
            if next_obs.all() == -999999:
                #  if the next state is terminal
                #  the return of our current state is equal to the reward
                #  i.e. Q(s',a) = 0 for any a
                target = rew
            else:
                #  for non terminal states
                #  get all possible combinations of our next state
                #  across the action space
                state_actions, _ = self.all_state_actions(next_obs)

                #  now predict the value of each of the state_actions
                #  note that we use Q_target here
                max_q = max([self.Q_target.predict(sa.reshape(-1, state_actions.shape[1]))
                             for sa in state_actions])

                #  the Bellman equation
                target = rew + self.discount * max_q

            targets = np.append(targets, target)

        #  save the unscaled targets so we can visualize later
        self.memory.agent_stats['unscaled Q targets'].extend(list(targets.flatten()))
        logging.info('Improving Q_actor - avg unscaled target={0:.3f}'.format(np.mean(targets)))

        #  scaling the targets by normalizing
        if self.scale_targets:
            #  normalizing
            #  targets = (targets - targets.min()) / (targets.max() - targets.min())

            #  scaling using standard deviation
            #  intentionally choose not to shift mean
            targets = targets / targets.std()

        #  reshape targets into 2 dimensions
        targets = targets.reshape(-1,1)

        #  update our Q function
        logging.info('Input shape {}'.format(inputs.shape))
        logging.info('Target shape {}'.format(targets.shape))
        hist = self.Q_actor.improve(state_actions=inputs, targets=targets)

        #  save loss and the training targets for visualization later
        self.memory.agent_stats['loss'].append(hist.history['loss'][-1])
        self.memory.agent_stats['training Q targets'].extend(list(targets.flatten()))

        return hist

    def _load_brain(self):
        """
        Loads experiences, Q_actor and Q_target

        TODO repeated code, maybe put this into Base_Agent init
        """

        #  load the action value functions
        Q_actor_path = os.path.join(self.brain_path, 'Q_actor.h5')
        self.Q_actor.load_model(Q_actor_path)
        self.Q_target = self.Q_actor

    def _save_brain(self):
        """
        Saves experiences, Q_actor and Q_target
        """
        #  add the acting Q network
        #  we don't add the target network - we just use the acting network
        #  to initialize Q_target when we load_brain

        #  not reccomended to use pickle for Keras models
        #  so we use h5py to save Keras models
        Q_actor_path = os.path.join(self.brain_path, 'Q_actor.h5')
        self.Q_actor.save_model(Q_actor_path)

    def update_target_network(self):
        """
        Copies weights from Q_actor into Q_target
        """
        logging.info('Updating Q_target by copying weights from Q_actor')
        self.Q_target.copy_weights(parent=self.Q_actor.model)