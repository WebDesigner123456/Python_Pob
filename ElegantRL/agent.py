import os
import torch
import numpy as np
import numpy.random as rd
from copy import deepcopy

from elegantrl2.net import QNet, QNetDuel, QNetTwin, QNetTwinDuel
from elegantrl2.net import Actor, ActorSAC, ActorPPO, ActorDiscretePPO
from elegantrl2.net import Critic, CriticAdv, CriticTwin

# from elegantrl2.net import SharedDPG, SharedSPG, SharedPPO

"""[ElegantRL](https://github.com/AI4Finance-LLC/ElegantRL)"""


class AgentBase:
    def __init__(self):
        self.state = None
        self.device = None
        self.if_on_policy = None
        self.get_obj_critic = None

        self.criterion = torch.nn.SmoothL1Loss()
        self.cri = self.cri_optim = self.Cri = None  # self.Cri is the class of cri
        self.act = self.act_optim = self.Act = None  # self.Act is the class of cri
        self.cri_target = self.if_use_cri_target = None
        self.act_target = self.if_use_act_target = None

    def init(self, net_dim, state_dim, action_dim, learning_rate=1e-4, if_per_or_gae=False):
        """initialize the self.object in `__init__()`

        replace by different DRL algorithms
        explict call self.init() for multiprocessing.

        `int net_dim` the dimension of networks (the width of neural networks)
        `int state_dim` the dimension of state (the number of state vector)
        `int action_dim` the dimension of action (the number of discrete action)
        `float learning_rate`: learning rate of optimizer
        `bool if_per_or_gae`: PER (off-policy) or GAE (on-policy) for sparse reward
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.cri = self.Cri(net_dim, state_dim, action_dim).to(self.device)
        self.act = self.Act(net_dim, state_dim, action_dim).to(self.device) if self.Act is not None else self.cri
        self.cri_target = deepcopy(self.cri) if self.if_use_cri_target else self.cri
        self.act_target = deepcopy(self.act) if self.if_use_act_target else self.act

        self.cri_optim = torch.optim.Adam(self.cri.parameters(), learning_rate)
        self.act_optim = torch.optim.Adam(self.act.parameters(), learning_rate) if self.Act is not None else self.cri
        del self.Cri, self.Act, self.if_use_cri_target, self.if_use_act_target

    def select_action(self, state) -> np.ndarray:
        """Select actions for exploration

        `array state` state.shape==(state_dim, )
        return `array action` action.shape==(action_dim, ),  -1 < action < +1
        """
        pass  # sample form an action distribution

    def explore_env(self, env, target_step, reward_scale, gamma) -> list:
        """actor explores in env, then returns the trajectory_list (env transition)

        `object env` RL training environment. env.reset() env.step()
        `int target_step` explored target_step number of step in env
        `float reward_scale` scale reward, 'reward * reward_scale'
        `float gamma` discount factor, 'mask = 0.0 if done else gamma'
        return `list trajectory_list` buffer.extend_buffer_from_trajectory(trajectory_list)
        """
        trajectory_list = list()

        state = self.state
        for _ in range(target_step):
            action = self.select_action(state)
            next_s, reward, done, _ = env.step(action)
            other = (reward * reward_scale, 0.0 if done else gamma, *action)
            trajectory_list.append((state, other))

            state = env.reset() if done else next_s
        self.state = state
        return trajectory_list

    def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:
        """update the neural network by sampling batch data from ReplayBuffer

        replace by different DRL algorithms.
        return the objective value as training information to help fine-tuning

        `buffer` Experience replay buffer.
        `int batch_size` sample batch_size of data for Stochastic Gradient Descent
        `float repeat_times` the times of sample batch = int(target_step * repeat_times) in off-policy
        `float soft_update_tau` target_net = target_net * (1-tau) + current_net * tau
        `return tuple` training logging. tuple = (float, float, ...)
        """

    @staticmethod
    def optim_update(optimizer, objective):
        optimizer.zero_grad()
        objective.backward()
        optimizer.step()

    @staticmethod
    def optim_update_amp(optimizer, objective):  # automatic mixed precision
        # # amp_scale = torch.cuda.amp.GradScaler()

        # optimizer.zero_grad()
        # amp_scale.scale(objective).backward()  # loss.backward()
        # amp_scale.unscale_(optimizer)  # amp
        #
        # # from torch.nn.utils import clip_grad_norm_
        # clip_grad_norm_(model.parameters(), max_norm=3.0)  # amp, clip_grad_norm_
        # amp_scale.step(optimizer)  # optimizer.step()
        # amp_scale.update()  # optimizer.step()
        pass

    @staticmethod
    def soft_update(target_net, current_net, tau):
        """soft update a target network via current network

        `nn.Module target_net` target network update via a current network, it is more stable
        `nn.Module current_net` current network update via an optimizer
        """
        for tar, cur in zip(target_net.parameters(), current_net.parameters()):
            tar.data.copy_(cur.data * tau + tar.data * (1 - tau))

    def save_load_model(self, cwd, if_save):
        """save or load model files

        `str cwd` current working directory, we save model file here
        `bool if_save` save model or load model
        """
        act_save_path = '{}/actor.pth'.format(cwd)
        cri_save_path = '{}/critic.pth'.format(cwd)

        def load_torch_file(network, save_path):
            network_dict = torch.load(save_path, map_location=lambda storage, loc: storage)
            network.load_state_dict(network_dict)

        if if_save:
            if self.act is not None:
                torch.save(self.act.state_dict(), act_save_path)
            if self.cri is not None:
                torch.save(self.cri.state_dict(), cri_save_path)
        elif (self.act is not None) and os.path.exists(act_save_path):
            load_torch_file(self.act, act_save_path)
            print("Loaded act:", cwd)
        elif (self.cri is not None) and os.path.exists(cri_save_path):
            load_torch_file(self.cri, cri_save_path)
            print("Loaded cri:", cwd)
        else:
            print("FileNotFound when load_model: {}".format(cwd))


'''Value-based Methods (DQN variances)'''


class AgentDQN(AgentBase):
    def __init__(self):
        super().__init__()
        self.explore_rate = 0.1  # the probability of choosing action randomly in epsilon-greedy
        self.action_dim = None
        self.if_use_cri_target = True

        self.Cri = QNet

    def init(self, net_dim, state_dim, action_dim, learning_rate=1e-4, if_use_per=False):
        super().init(net_dim, state_dim, action_dim, learning_rate=1e-4)
        if if_use_per:
            self.criterion = torch.nn.MSELoss(reduction='none')
            self.get_obj_critic = self.get_obj_critic_per
        else:
            self.criterion = torch.nn.MSELoss(reduction='mean')
            self.get_obj_critic = self.get_obj_critic_raw

    def select_action(self, state) -> int:  # for discrete action space
        if rd.rand() < self.explore_rate:  # epsilon-greedy
            a_int = rd.randint(self.action_dim)  # choosing action randomly
        else:
            states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
            action = self.act(states)[0]
            a_int = action.argmax(dim=0).detach().cpu().numpy()
        return a_int

    def explore_env(self, env, target_step, reward_scale, gamma) -> list:
        trajectory_list = list()

        state = self.state
        for _ in range(target_step):
            action = self.select_action(state)  # assert isinstance(action, int)
            next_s, reward, done, _ = env.step(action)
            other = (reward * reward_scale, 0.0 if done else gamma, action)
            trajectory_list.append((state, other))

            state = env.reset() if done else next_s
        self.state = state
        return trajectory_list

    def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:
        buffer.update_now_len()

        obj_critic = q_value = None
        for _ in range(int(buffer.now_len / batch_size * repeat_times)):
            obj_critic, q_value = self.get_obj_critic(buffer, batch_size)
            self.optim_update(self.cri_optim, obj_critic)
            self.soft_update(self.cri_target, self.cri, soft_update_tau)
        return obj_critic.item(), q_value.mean().item()

    def get_obj_critic_raw(self, buffer, batch_size):
        with torch.no_grad():
            reward, mask, action, state, next_s = buffer.sample_batch(batch_size)
            next_q = self.cri_target(next_s).max(dim=1, keepdim=True)[0]
            q_label = reward + mask * next_q

        q_value = self.cri(state).gather(1, action.long())
        obj_critic = self.criterion(q_value, q_label)
        return obj_critic, q_value

    def get_obj_critic_per(self, buffer, batch_size):
        with torch.no_grad():
            reward, mask, action, state, next_s, is_weights = buffer.sample_batch(batch_size)
            next_q = self.cri_target(next_s).max(dim=1, keepdim=True)[0]
            q_label = reward + mask * next_q

        q_value = self.cri(state).gather(1, action.long())
        obj_critic = (self.criterion(q_value, q_label) * is_weights).mean()
        return obj_critic, q_value


class AgentDuelDQN(AgentDQN):
    def __init__(self):
        super().__init__()
        self.explore_rate = 0.25  # the probability of choosing action randomly in epsilon-greedy

        self.Cri = QNetDuel


class AgentDoubleDQN(AgentDQN):
    def __init__(self):
        super().__init__()
        self.explore_rate = 0.25  # the probability of choosing action randomly in epsilon-greedy
        self.softMax = torch.nn.Softmax(dim=1)

        self.Cri = QNetTwin

    def select_action(self, state) -> int:  # for discrete action space
        states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
        actions = self.act(states)
        if rd.rand() < self.explore_rate:  # epsilon-greedy
            action = self.softMax(actions)[0]
            a_prob = action.detach().cpu().numpy()  # choose action according to Q value
            a_int = rd.choice(self.action_dim, p=a_prob)
        else:
            action = actions[0]
            a_int = action.argmax(dim=0).detach().cpu().numpy()
        return a_int

    def get_obj_critic_raw(self, buffer, batch_size):
        with torch.no_grad():
            reward, mask, action, state, next_s = buffer.sample_batch(batch_size)
            next_q = torch.min(*self.cri_target.get_q1_q2(next_s))
            next_q = next_q.max(dim=1, keepdim=True)[0]
            q_label = reward + mask * next_q

        q1, q2 = [qs.gather(1, action.long()) for qs in self.act.get_q1_q2(state)]
        obj_critic = self.criterion(q1, q_label) + self.criterion(q2, q_label)
        return obj_critic, q1

    def get_obj_critic_per(self, buffer, batch_size):
        with torch.no_grad():
            reward, mask, action, state, next_s, is_weights = buffer.sample_batch(batch_size)
            next_q = torch.min(*self.cri_target.get_q1_q2(next_s))
            next_q = next_q.max(dim=1, keepdim=True)[0]
            q_label = reward + mask * next_q

        q1, q2 = [qs.gather(1, action.long()) for qs in self.act.get_q1_q2(state)]
        obj_critic = ((self.criterion(q1, q_label) + self.criterion(q2, q_label)) * is_weights).mean()
        return obj_critic, q1


class AgentD3QN(AgentDoubleDQN):  # D3QN: Dueling Double DQN
    def __init__(self):
        super().__init__()
        self.Cri = QNetTwinDuel


'''Actor-Critic Methods (Policy Gradient)'''


class AgentDDPG(AgentBase):
    def __init__(self):
        super().__init__()
        self.ou_explore_noise = 0.3  # explore noise of action
        self.ou_noise = None
        self.if_use_cri_target = self.if_use_act_target = True

        self.Act = Actor
        self.Cri = Critic

    def init(self, net_dim, state_dim, action_dim, learning_rate=1e-4, if_use_per=False):
        super().init(net_dim, state_dim, action_dim, learning_rate)
        self.ou_noise = OrnsteinUhlenbeckNoise(size=action_dim, sigma=self.ou_explore_noise)

        if if_use_per:
            self.criterion = torch.nn.SmoothL1Loss(reduction='none' if if_use_per else 'mean')
            self.get_obj_critic = self.get_obj_critic_per
        else:
            self.criterion = torch.nn.SmoothL1Loss(reduction='none' if if_use_per else 'mean')
            self.get_obj_critic = self.get_obj_critic_raw

    def select_action(self, state) -> np.ndarray:
        states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
        action = self.act(states)[0].detach().cpu().numpy()
        return (action + self.ou_noise()).clip(-1, 1)

    def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:
        buffer.update_now_len()

        obj_critic = obj_actor = None
        for _ in range(int(buffer.now_len / batch_size * repeat_times)):
            obj_critic, state = self.get_obj_critic(buffer, batch_size)
            self.optim_update(self.cri_optim, obj_critic)
            self.soft_update(self.cri_target, self.cri, soft_update_tau)

            action_pg = self.act(state)  # policy gradient
            obj_actor = -self.cri(state, action_pg).mean()
            self.optim_update(self.act_optim, obj_actor)
            self.soft_update(self.act_target, self.act, soft_update_tau)
        return obj_actor.item(), obj_critic.item()

    def get_obj_critic_raw(self, buffer, batch_size):
        with torch.no_grad():
            reward, mask, action, state, next_s = buffer.sample_batch(batch_size)
            next_q = self.cri_target(next_s, self.act_target(next_s))
            q_label = reward + mask * next_q
        q_value = self.cri(state, action)
        obj_critic = self.criterion(q_value, q_label)
        return obj_critic, state

    def get_obj_critic_per(self, buffer, batch_size):
        with torch.no_grad():
            reward, mask, action, state, next_s, is_weights = buffer.sample_batch(batch_size)
            next_q = self.cri_target(next_s, self.act_target(next_s))
            q_label = reward + mask * next_q
        q_value = self.cri(state, action)
        obj_critic = (self.criterion(q_value, q_label) * is_weights).mean()

        td_error = (q_label - q_value.detach()).abs()
        buffer.td_error_update(td_error)
        return obj_critic, state


class AgentTD3(AgentDDPG):
    def __init__(self):
        super().__init__()
        self.explore_noise = 0.1  # standard deviation of explore noise
        self.policy_noise = 0.2  # standard deviation of policy noise
        self.update_freq = 2  # delay update frequency, for soft target update

        self.Cri = CriticTwin

    def select_action(self, state) -> np.ndarray:
        states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
        action = self.act(states)[0]
        action = (action + torch.randn_like(action) * self.explore_noise).clamp(-1, 1)
        return action.detach().cpu().numpy()

    def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:
        buffer.update_now_len()

        obj_critic = obj_actor = None
        for update_c in range(int(buffer.now_len / batch_size * repeat_times)):
            obj_critic, state = self.get_obj_critic(buffer, batch_size)
            self.optim_update(self.cri_optim, obj_critic)

            action_pg = self.act(state)  # policy gradient
            obj_actor = -self.cri_target(state, action_pg).mean()  # use cri_target instead of cri for stable training
            self.optim_update(self.act_optim, obj_actor)
            if update_c % self.update_freq == 0:  # delay update
                self.soft_update(self.cri_target, self.cri, soft_update_tau)
                self.soft_update(self.act_target, self.act, soft_update_tau)
        return obj_critic.item() / 2, obj_actor.item()

    def get_obj_critic_raw(self, buffer, batch_size):
        with torch.no_grad():
            reward, mask, action, state, next_s = buffer.sample_batch(batch_size)
            next_a = self.act_target.get_action(next_s, self.policy_noise)  # policy noise
            next_q = torch.min(*self.cri_target.get_q1_q2(next_s, next_a))  # twin critics
            q_label = reward + mask * next_q
        q1, q2 = self.cri.get_q1_q2(state, action)
        obj_critic = self.criterion(q1, q_label) + self.criterion(q2, q_label)  # twin critics
        return obj_critic, state

    def get_obj_critic_per(self, buffer, batch_size):
        """Prioritized Experience Replay

        Contributor: Github GyChou
        """
        with torch.no_grad():
            reward, mask, action, state, next_s, is_weights = buffer.sample_batch(batch_size)
            next_a = self.act_target.get_action(next_s, self.policy_noise)  # policy noise
            next_q = torch.min(*self.cri_target.get_q1_q2(next_s, next_a))  # twin critics
            q_label = reward + mask * next_q

        q1, q2 = self.cri.get_q1_q2(state, action)
        obj_critic = ((self.criterion(q1, q_label) + self.criterion(q2, q_label)) * is_weights).mean()

        td_error = (q_label - torch.min(q1, q2).detach()).abs()
        buffer.td_error_update(td_error)
        return obj_critic, state


class AgentSAC(AgentBase):
    def __init__(self):
        super().__init__()
        self.if_use_cri_target = True
        self.Act = ActorSAC
        self.Cri = CriticTwin

    def select_action(self, state) -> np.ndarray:
        states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
        action = self.act.get_action(states)[0]
        return action.detach().cpu().numpy()

    def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:
        buffer.update_now_len()

        log_alpha = self.act.log_alpha
        obj_critic = obj_actor = None
        for update_c in range(int(buffer.now_len / batch_size * repeat_times)):
            obj_critic, state = self.get_obj_critic(buffer, batch_size, log_alpha.exp())
            self.optim_update(self.cri_optim, obj_critic)

            action_pg, logprob = self.act.get_action_logprob(state)  # policy gradient
            obj_actor = (-torch.min(*self.cri_target.get_q1_q2(state, action_pg)).mean()
                         + logprob.mean() * log_alpha.exp().detach()
                         + self.act.get_obj_alpha(logprob))
            self.optim_update(self.act_optim, obj_actor)
            self.soft_update(self.cri_target, self.cri, soft_update_tau)
        return obj_critic.item() / 2, obj_actor.item(), log_alpha.item()

    def get_obj_critic_raw(self, buffer, batch_size, alpha):
        with torch.no_grad():
            reward, mask, action, state, next_s = buffer.sample_batch(batch_size)
            next_a, next_logprob = self.act.get_action_logprob(next_s)
            next_q = torch.min(*self.cri_target.get_q1_q2(next_s, next_a))
            q_label = reward + mask * (next_q + next_logprob * alpha)
        q1, q2 = self.cri.get_q1_q2(state, action)  # twin critics
        obj_critic = self.criterion(q1, q_label) + self.criterion(q2, q_label)
        return obj_critic, state

    def get_obj_critic_per(self, buffer, batch_size, alpha):
        with torch.no_grad():
            reward, mask, action, state, next_s, is_weights = buffer.sample_batch(batch_size)
            next_a, next_logprob = self.act.get_action_logprob(next_s)
            next_q = torch.min(*self.cri_target.get_q1_q2(next_s, next_a))
            q_label = reward + mask * (next_q + next_logprob * alpha)
        q1, q2 = self.cri.get_q1_q2(state, action)  # twin critics
        obj_critic = ((self.criterion(q1, q_label) + self.criterion(q2, q_label)) * is_weights).mean()

        td_error = (q_label - torch.min(q1, q2).detach()).abs()
        buffer.td_error_update(td_error)
        return obj_critic, state


class AgentModSAC(AgentSAC):  # Modified SAC using reliable_lambda and TTUR (Two Time-scale Update Rule)
    def __init__(self):
        super().__init__()
        self.if_use_dn = True  # plan to do
        self.if_use_act_target = True
        self.if_use_cri_target = True
        self.obj_c = (-np.log(0.5)) ** 0.5  # for reliable_lambda

    def select_action(self, state) -> np.ndarray:
        states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
        action = self.act.get_action(states)[0]
        return action.detach().cpu().numpy()

    def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:
        buffer.update_now_len()

        log_alpha = self.act.log_alpha
        # batch_size = int(batch_size * (1.0 + buffer.now_len / buffer.max_len))  # increase batch_size
        # plan to check

        obj_actor = None
        update_a = 0
        for update_c in range(1, int(buffer.now_len / batch_size * repeat_times)):
            alpha_log_clip = (log_alpha / 4).tanh() * 4 - 2  # keep alpha_log_clip in (-14, 2)

            '''objective of critic (loss function of critic)'''
            obj_critic, state = self.get_obj_critic(buffer, batch_size, alpha_log_clip.exp().detach())
            self.obj_c = 0.995 * self.obj_c + 0.0025 * obj_critic.item()  # for reliable_lambda
            self.optim_update(self.cri_optim, obj_critic)
            self.soft_update(self.cri_target, self.cri, soft_update_tau) if self.if_use_act_target else None

            '''objective of actor using reliable_lambda and TTUR (Two Time-scales Update Rule)'''
            reliable_lambda = np.exp(-self.obj_c ** 2)  # for reliable_lambda
            if_update_a = (update_a / update_c) < (1 / (2 - reliable_lambda))
            if if_update_a:  # auto TTUR
                update_a += 1

                action_pg, logprob = self.act.get_action_logprob(state)  # policy gradient
                obj_actor = (-torch.min(*self.cri_target.get_q1_q2(state, action_pg)).mean()
                             + logprob.mean() * log_alpha.exp().detach()
                             + self.act.get_obj_alpha(logprob))

                self.optim_update(self.act_optim, obj_actor)
                self.soft_update(self.cri_target, self.cri, soft_update_tau)

        return self.obj_c / 2, obj_actor.item(), log_alpha.item()


class AgentPPO(AgentBase):
    def __init__(self):
        super().__init__()
        self.if_on_policy = True
        self.ratio_clip = 0.2  # ratio.clamp(1 - clip, 1 + clip)
        self.lambda_entropy = 0.02  # could be 0.00~0.05
        self.lambda_gae_adv = 0.97  # could be 0.96~0.99
        self.get_reward_sum = None

        self.Act = ActorPPO
        self.Cri = CriticAdv

    def init(self, net_dim, state_dim, action_dim, learning_rate=1e-4, if_use_gae=False):
        super().init(net_dim, state_dim, action_dim, learning_rate)
        self.get_reward_sum = self.get_reward_sum_gae if if_use_gae else self.get_reward_sum_raw

    def select_action(self, state):
        states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
        actions, noises = self.act.get_action(states)  # plan to be get_action_a_noise
        return actions[0].detach().cpu().numpy(), noises[0].detach().cpu().numpy()

    def select_actions(self, states):
        # states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
        actions, noises = self.act.get_action(states)  # plan to be get_action_a_noise
        return actions, noises

    def explore_env(self, env, target_step, reward_scale, gamma):
        trajectory_list = list()

        state = self.state
        for _ in range(target_step):
            action, noise = self.select_action(state)
            next_s, reward, done, _ = env.step(np.tanh(action))
            other = (reward * reward_scale, 0.0 if done else gamma, *action, *noise)
            trajectory_list.append((state, other))

            state = env.reset() if done else next_s
        self.state = state
        return trajectory_list

    def explore_envs(self, env, target_step, reward_scale, gamma):
        state = self.state
        env_num = env.env_num

        buf_step = target_step // env_num
        states = torch.empty((buf_step, env_num, env.state_dim), dtype=torch.float32, device=self.device)
        actions = torch.empty((buf_step, env_num, env.action_dim), dtype=torch.float32, device=self.device)
        noises = torch.empty((buf_step, env_num, env.action_dim), dtype=torch.float32, device=self.device)
        rewards = torch.empty((buf_step, env_num), dtype=torch.float32, device=self.device)
        dones = torch.empty((buf_step, env_num), dtype=torch.float32, device=self.device)
        for i in range(buf_step):
            action, noise = self.select_actions(state)
            next_s, reward, done, _ = env.step(action.tanh())
            # other = (reward * reward_scale, 0.0 if done else gamma, *action, *noise)
            # trajectory_list.append((state, other))

            states[i] = state
            actions[i] = action
            noises[i] = noise
            rewards[i] = reward
            dones[i] = done

            # state = env.reset() if done else next_s
            state = next_s
        self.state = state
        rewards = rewards * reward_scale
        masks = (1 - dones) * gamma
        return states, rewards, masks, actions, noises

    def prepare_buffer(self, buffer):
        buffer.update_now_len()
        buf_len = buffer.now_len
        with torch.no_grad():  # compute reverse reward
            reward, mask, action, a_noise, state = buffer.sample_all()

            # print(';', [t.shape for t in (reward, mask, action, a_noise, state)])
            bs = 2 ** 10  # set a smaller 'BatchSize' when out of GPU memory.
            value = torch.cat([self.cri_target(state[i:i + bs]) for i in range(0, state.size(0), bs)], dim=0).squeeze(1)
            logprob = self.act.get_old_logprob(action, a_noise)

            pre_state = torch.as_tensor((self.state,), dtype=torch.float32, device=self.device)
            pre_r_sum = self.cri_target(pre_state).detach()
            r_sum, advantage = self.get_reward_sum(buf_len, reward, mask, value, pre_r_sum)
        buffer.empty_buffer()
        return state, action, r_sum, logprob, advantage

    def prepare_buffers(self, buffer):
        with torch.no_grad():  # compute reverse reward
            states, rewards, masks, actions, noises = buffer
            buf_len = states.size(0)
            env_num = states.size(1)

            values = torch.empty_like(rewards)
            logprobs = torch.empty_like(rewards)
            bs = 2 ** 10  # set a smaller 'BatchSize' when out of GPU memory.
            for j in range(env_num):
                for i in range(0, buf_len, bs):
                    values[i:i + bs, j] = self.cri_target(states[i:i + bs, j]).squeeze(1)
                logprobs[:, j] = self.act.get_old_logprob(actions[:, j], noises[:, j]).squeeze(1)

            pre_states = torch.as_tensor(self.state, dtype=torch.float32, device=self.device)
            pre_r_sums = self.cri_target(pre_states).detach().squeeze(1)

            r_sums, advantages = self.get_reward_sum((buf_len, env_num), rewards, masks, values, pre_r_sums)

        buf_len_vec = buf_len * env_num

        states = states.view((buf_len_vec, -1))
        actions = actions.view((buf_len_vec, -1))
        r_sums = r_sums.view(buf_len_vec)
        logprobs = logprobs.view(buf_len_vec)
        advantages = advantages.view(buf_len_vec)
        return states, actions, r_sums, logprobs, advantages

    def update_net(self, buffer, batch_size, repeat_times, soft_update_tau):
        if isinstance(buffer, list):
            buffer_tuple = list(map(list, zip(*buffer)))  # 2D-list transpose
            (buf_state, buf_action, buf_r_sum, buf_logprob, buf_advantage
             ) = [torch.cat(tensor_list, dim=0).to(self.device)
                  for tensor_list in buffer_tuple]
        elif isinstance(buffer, tuple):
            (buf_state, buf_action, buf_r_sum, buf_logprob, buf_advantage
             ) = buffer
        else:
            (buf_state, buf_action, buf_r_sum, buf_logprob, buf_advantage
             ) = self.prepare_buffer(buffer)
        buf_len = buf_state.size(0)

        '''PPO: Surrogate objective of Trust Region'''
        obj_critic = obj_actor = old_logprob = None
        r_sum_std = 1  # todo buf_r_sum.std() + 1e-6
        for _ in range(int(buf_len / batch_size * repeat_times)):
            indices = torch.randint(buf_len, size=(batch_size,), requires_grad=False, device=self.device)

            state = buf_state[indices]
            action = buf_action[indices]
            r_sum = buf_r_sum[indices]
            advantage = buf_advantage[indices]
            old_logprob = buf_logprob[indices]

            new_logprob, obj_entropy = self.act.get_new_logprob_entropy(state, action)
            ratio = (new_logprob - old_logprob.detach()).exp()
            surrogate1 = advantage * ratio
            surrogate2 = advantage * ratio.clamp(1 - self.ratio_clip, 1 + self.ratio_clip)
            obj_surrogate = -torch.min(surrogate1, surrogate2).mean()
            obj_actor = obj_surrogate + obj_entropy * self.lambda_entropy
            self.optim_update(self.act_optim, obj_actor)

            value = self.cri(state).squeeze(1)  # critic network predicts the reward_sum (Q value) of state
            obj_critic = self.criterion(value, r_sum) / r_sum_std
            self.optim_update(self.cri_optim, obj_critic)
            self.soft_update(self.cri_target, self.cri, soft_update_tau) if self.cri_target is not self.cri else None

        return obj_critic.item(), obj_actor.item(), old_logprob.mean().item()  # logging_tuple

    def get_reward_sum_raw(self, buf_len, buf_reward, buf_mask, buf_value, pre_r_sum) -> (torch.Tensor, torch.Tensor):
        """compute the excepted discounted episode return

        :int buf_len: the length of ReplayBuffer
        :torch.Tensor buf_reward: buf_reward.shape==(buf_len, )
        :torch.Tensor buf_mask:   buf_mask.shape  ==(buf_len, )
        :torch.Tensor buf_value:  buf_value.shape ==(buf_len, )
        :torch.Tensor pre_r_sum:  pre_r_sum.shape ==(1, 1)
        :return torch.Tensor buf_r_sum: buf_r_sum.shape     ==(buf_len, 1)
        :return torch.Tensor buf_advantage:  buf_advantage.shape ==(buf_len, 1)
        """
        buf_r_sum = torch.empty(buf_len, dtype=torch.float32, device=self.device)  # reward sum
        the_len = buf_len[0] if isinstance(buf_len, tuple) else buf_len
        for i in range(the_len - 1, -1, -1):
            buf_r_sum[i] = buf_reward[i] + buf_mask[i] * pre_r_sum
            pre_r_sum = buf_r_sum[i]
        buf_advantage = buf_r_sum - buf_mask * buf_value
        buf_advantage = (buf_advantage - buf_advantage.mean())  # todo / (buf_advantage.std() + 1e-5)
        return buf_r_sum, buf_advantage

    def get_reward_sum_gae(self, buf_len, buf_reward, buf_mask, buf_value, pre_r_sum) -> (torch.Tensor, torch.Tensor):
        buf_r_sum = torch.empty(buf_len, dtype=torch.float32, device=self.device)  # old policy value
        buf_advantage = torch.empty(buf_len, dtype=torch.float32, device=self.device)  # advantage value

        pre_advantage = pre_r_sum * (np.exp(self.lambda_gae_adv - 0.5) - 1)  # advantage value of previous step

        the_len = buf_len[0] if isinstance(buf_len, tuple) else buf_len
        for i in range(the_len - 1, -1, -1):
            buf_r_sum[i] = buf_reward[i] + buf_mask[i] * pre_r_sum
            pre_r_sum = buf_r_sum[i]

            buf_advantage[i] = buf_reward[i] + buf_mask[i] * (pre_advantage - buf_value[i])  # fix a bug here
            pre_advantage = buf_value[i] + buf_advantage[i] * self.lambda_gae_adv

        buf_advantage = (buf_advantage - buf_advantage.mean())  # todo / (buf_advantage.std() + 1e-5)
        return buf_r_sum, buf_advantage


class AgentDiscretePPO(AgentPPO):
    def __init__(self):
        super().__init__()
        self.Act = ActorDiscretePPO

    def explore_env(self, env, target_step, reward_scale, gamma):
        trajectory_list = list()

        state = self.state
        for _ in range(target_step):
            a_int, a_prob = self.select_action(state)
            next_s, reward, done, _ = env.step(a_int)
            other = (reward * reward_scale, 0.0 if done else gamma, a_int, *a_prob)
            trajectory_list.append((state, other))

            state = env.reset() if done else next_s
        self.state = state
        return trajectory_list


# class AgentSharedAC(AgentBase):  # use InterSAC instead of InterAC .Warning: sth. wrong with this code, need to check
#     def __init__(self):
#         super().__init__()
#         self.explore_noise = 0.2  # standard deviation of explore noise
#         self.policy_noise = 0.4  # standard deviation of policy noise
#         self.update_freq = 2 ** 7  # delay update frequency, for hard target update
#         self.avg_loss_c = (-np.log(0.5)) ** 0.5  # old version reliable_lambda
#         self.optimizer = None
#
#     def init(self, net_dim, state_dim, action_dim, learning_rate=1e-4, if_pre_or_gae=False):
#         self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
#
#         self.act = SharedDPG(state_dim, action_dim, net_dim).to(self.device)
#         self.act_target = deepcopy(self.act)
#
#         self.criterion = torch.nn.MSELoss(reduction='none') if if_pre_or_gae else torch.nn.MSELoss()
#         self.optimizer = torch.optim.Adam(self.act.parameters(), lr=learning_rate)
#
#     def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:
#         buffer.update_now_len()
#
#         actor_obj = None  # just for print return
#
#         k = 1.0 + buffer.now_len / buffer.max_len
#         batch_size_ = int(batch_size * k)
#
#         for i in range(int(buffer.now_len / batch_size * repeat_times)):
#             with torch.no_grad():
#                 reward, mask, action, state, next_state = buffer.sample_batch(batch_size_)
#
#                 next_q_label, next_action = self.act_target.next_q_action(state, next_state, self.policy_noise)
#                 q_label = reward + mask * next_q_label
#
#             """critic_obj"""
#             q_eval = self.act.critic(state, action)
#             critic_obj = self.criterion(q_eval, q_label)
#
#             '''auto reliable lambda'''
#             self.avg_loss_c = 0.995 * self.avg_loss_c + 0.005 * critic_obj.item() / 2  # soft update, twin critics
#             lamb = np.exp(-self.avg_loss_c ** 2)
#
#             '''actor correction term'''
#             actor_term = self.criterion(self.act(next_state), next_action)
#
#             if i % repeat_times == 0:
#                 '''actor obj'''
#                 action_pg = self.act(state)  # policy gradient
#                 actor_obj = -self.act_target.critic(state, action_pg).mean()  # policy gradient
#                 # NOTICE! It is very important to use act_target.critic here instead act.critic
#                 # Or you can use act.critic.deepcopy(). Whatever you cannot use act.critic directly.
#
#                 united_loss = critic_obj + actor_term * (1 - lamb) + actor_obj * (lamb * 0.5)
#             else:
#                 united_loss = critic_obj + actor_term * (1 - lamb)
#
#             """united loss"""
#             self.update_optimizer(self.optimizer, united_loss)
#             if i % self.update_freq == self.update_freq and lamb > 0.1:
#                 self.act_target.load_state_dict(self.act.state_dict())  # Hard Target Update
#
#         return actor_obj.item(), self.avg_loss_c
#
#
# class AgentSharedSAC(AgentSAC):  # Integrated Soft Actor-Critic
#     def __init__(self):
#         super().__init__()
#         self.obj_c = (-np.log(0.5)) ** 0.5  # for reliable_lambda
#         self.optimizer = None
#
#     def init(self, net_dim, state_dim, action_dim, learning_rate=1e-4, if_pre_or_gae=False):
#         self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
#         self.target_entropy *= np.log(action_dim)
#         self.alpha_log = torch.tensor((-np.log(action_dim) * np.e,), dtype=torch.float32,
#                                       requires_grad=True, device=self.device)  # trainable parameter
#
#         self.act = SharedSPG(net_dim, state_dim, action_dim).to(self.device)
#         self.act_target = deepcopy(self.act)
#
#         self.optimizer = torch.optim.Adam(
#             [{'params': self.act.enc_s.parameters(), 'lr': learning_rate * 0.9},  # more stable
#              {'params': self.act.enc_a.parameters(), },
#              {'params': self.act.net.parameters(), 'lr': learning_rate * 0.9},
#              {'params': self.act.dec_a.parameters(), },
#              {'params': self.act.dec_d.parameters(), },
#              {'params': self.act.dec_q1.parameters(), },
#              {'params': self.act.dec_q2.parameters(), },
#              {'params': (self.alpha_log,)}], lr=learning_rate)
#         self.criterion = torch.nn.SmoothL1Loss(reduction='none' if if_pre_or_gae else 'mean')
#         if if_pre_or_gae:
#             self.get_obj_critic = self.get_obj_critic_per
#         else:
#             self.get_obj_critic = self.get_obj_critic_raw
#
#     def select_action(self, state) -> np.ndarray:
#         states = torch.as_tensor((state,), dtype=torch.float32, device=self.device)
#         action = self.act.get_noise_action(states)[0]
#         return action.detach().cpu().numpy()
#
#     def update_net(self, buffer, batch_size, repeat_times, soft_update_tau) -> tuple:  # 1111
#         buffer.update_now_len()
#
#         alpha = self.alpha_log.exp().detach()  # auto temperature parameter
#
#         k = 1.0 + buffer.now_len / buffer.max_len
#         batch_size_ = int(batch_size * k)  # increase batch_size
#
#         update_a = 0
#         for update_c in range(1, int(buffer.now_len / batch_size * repeat_times)):
#             '''objective of critic'''
#             obj_critic, state = self.get_obj_critic(buffer, batch_size_, alpha)
#             self.obj_c = 0.995 * self.obj_c + 0.005 * obj_critic.item() / 2  # soft update, twin critics
#             reliable_lambda = np.exp(-self.obj_c ** 2)
#
#             '''objective of alpha (temperature parameter automatic adjustment)'''
#             action_pg, logprob = self.act.get_a_logprob(state)  # policy gradient
#             obj_alpha = (self.alpha_log * (logprob - self.target_entropy).detach() * reliable_lambda).mean()
#
#             with torch.no_grad():
#                 self.alpha_log[:] = self.alpha_log.clamp(-20, 2)
#                 alpha = self.alpha_log.exp()  # .detach()
#
#             '''objective of actor using reliable_lambda and TTUR (Two Time-scales Update Rule)'''
#             if update_a / update_c < 1 / (2 - reliable_lambda):  # auto TTUR
#                 update_a += 1
#                 q_value_pg = torch.min(*self.act_target.get_q1_q2(state, action_pg)).mean()  # twin critics
#                 obj_actor = -(q_value_pg + logprob * alpha.detach()).mean()  # policy gradient
#
#                 obj_united = obj_critic + obj_alpha + obj_actor * reliable_lambda
#             else:
#                 obj_united = obj_critic + obj_alpha
#
#             self.optimizer.zero_grad()
#             obj_united.backward()
#             self.optimizer.step()
#
#             self.soft_update(self.act_target, self.act, soft_update_tau)
#
#         return alpha.item(), self.obj_c
#
#
# class AgentSharedPPO(AgentPPO):
#     def __init__(self):
#         super().__init__()
#         self.clip = 0.25  # ratio.clamp(1 - clip, 1 + clip)
#         self.lambda_entropy = 0.01  # could be 0.02
#         self.lambda_gae_adv = 0.98  # could be 0.95~0.99, GAE (Generalized Advantage Estimation. ICLR.2016.)
#         self.obj_c = (-np.log(0.5)) ** 0.5  # for reliable_lambda
#
#     def init(self, net_dim, state_dim, action_dim, learning_rate=1e-4, if_pre_or_gae=False):
#         self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
#         self.compute_reward = self.compute_reward_gae if if_pre_or_gae else self.compute_reward_adv
#
#         self.act = SharedPPO(state_dim, action_dim, net_dim).to(self.device)
#
#         self.optimizer = torch.optim.Adam([
#             {'params': self.act.enc_s.parameters(), 'lr': learning_rate * 0.9},
#             {'params': self.act.dec_a.parameters(), },
#             {'params': self.act.a_std_log, },
#             {'params': self.act.dec_q1.parameters(), },
#             {'params': self.act.dec_q2.parameters(), },
#         ], lr=learning_rate)
#         self.criterion = torch.nn.SmoothL1Loss()
#
#     def update_net(self, buffer, batch_size, repeat_times=4, soft_update_tau=None) -> (float, float):  # old version
#         buffer.update_now_len()
#         buf_len = buffer.now_len  # assert buf_len >= _target_step
#
#         '''Trajectory using reverse reward'''
#         with torch.no_grad():
#             buf_reward, buf_mask, buf_action, buf_noise, buf_state = buffer.sample_all()
#
#             bs = 2 ** 10  # set a smaller 'bs: batch size' when out of GPU memory.
#             buf_value = torch.cat([self.cri(buf_state[i:i + bs]) for i in range(0, buf_state.size(0), bs)], dim=0)
#             buf_logprob = -(buf_noise.pow(2).__mul__(0.5) + self.act.a_std_log + self.act.sqrt_2pi_log).sum(1)
#
#             buf_r_sum, buf_advantage = self.compute_reward(self, buf_len, buf_reward, buf_mask, buf_value)
#             del buf_reward, buf_mask, buf_noise
#
#         '''PPO: Clipped Surrogate objective of Trust Region'''
#         obj_critic = obj_actor = None
#         for _ in range(int(buffer.now_len / batch_size * repeat_times)):
#             indices = torch.randint(buf_len, size=(batch_size,), device=self.device)
#
#             state = buf_state[indices]
#             action = buf_action[indices]
#             advantage = buf_advantage[indices]
#             old_value = buf_r_sum[indices]
#             old_logprob = buf_logprob[indices]
#
#             new_logprob = self.act.compute_logprob(state, action)  # it is obj_actor
#             ratio = (new_logprob - old_logprob).exp()
#             obj_surrogate1 = advantage * ratio
#             obj_surrogate2 = advantage * ratio.clamp(1 - self.clip, 1 + self.clip)
#             obj_surrogate = -torch.min(obj_surrogate1, obj_surrogate2).mean()
#             obj_entropy = (new_logprob.exp() * new_logprob).mean()  # policy entropy
#             obj_actor = obj_surrogate + obj_entropy * self.lambda_entropy
#
#             new_value = self.cri(state).squeeze(1)
#             obj_critic = self.criterion(new_value, old_value)
#             self.obj_c = 0.995 * self.obj_c + 0.005 * obj_critic.item()  # for reliable_lambda
#             reliable_lambda = np.exp(-self.obj_c ** 2)  # for reliable_lambda
#
#             obj_united = obj_actor * reliable_lambda + obj_critic / (old_value.std() + 1e-5)
#             self.optimizer.zero_grad()
#             obj_united.backward()
#             self.optimizer.step()
#
#         return obj_critic.item(), obj_actor.item(), self.act.a_std_log.mean().item(),


'''Utils'''


class OrnsteinUhlenbeckNoise:
    def __init__(self, size, theta=0.15, sigma=0.3, ou_noise=0.0, dt=1e-2):
        """The noise of Ornstein-Uhlenbeck Process

        Source: https://github.com/slowbull/DDPG/blob/master/src/explorationnoise.py
        It makes Zero-mean Gaussian Noise more stable.
        It helps agent explore better in a inertial system.
        Don't abuse OU Process. OU process has too much hyper-parameters and over fine-tuning make no sense.

        :int size: the size of noise, noise.shape==(-1, action_dim)
        :float theta: related to the not independent of OU-noise
        :float sigma: related to action noise std
        :float ou_noise: initialize OU-noise
        :float dt: derivative
        """
        self.theta = theta
        self.sigma = sigma
        self.ou_noise = ou_noise
        self.dt = dt
        self.size = size

    def __call__(self) -> float:
        """output a OU-noise

        :return array ou_noise: a noise generated by Ornstein-Uhlenbeck Process
        """
        noise = self.sigma * np.sqrt(self.dt) * rd.normal(size=self.size)
        self.ou_noise -= self.theta * self.ou_noise * self.dt + noise
        return self.ou_noise