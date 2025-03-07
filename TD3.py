import copy
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from memory import BasicBuffer
import os
from torch.utils.tensorboard import SummaryWriter
from setup import powerGrid_ieee2
from torch.autograd import Variable
import statistics as stat
import matplotlib.pyplot as plt
import math
import pickle




class Actor(nn.Module):
    def __init__(self, state_dim, action_dim,p=0.3):
        super(Actor, self).__init__()

        self.l1 = nn.Linear(state_dim, 256)
        self.l2 = nn.Linear(256, 256)
        self.l3 = nn.Linear(256, action_dim)
        self.drop_layer = nn.Dropout(p=p)

    def forward(self, state):
        a = F.relu(self.l1(state))
        a = F.relu(self.l2(a))
        a = self.drop_layer(a);
        return torch.sigmoid(self.l3(a))

class Critic(nn.Module):
    def __init__(self, state_dim, action_dim,p=0.3):
        super(Critic, self).__init__()

        # Q1 architecture
        self.l1 = nn.Linear(state_dim + action_dim, (state_dim + action_dim)*2)
        self.l2 = nn.Linear((state_dim + action_dim)*2, (state_dim + action_dim)*4)
        self.l3 = nn.Linear((state_dim + action_dim)*4, 1)
        self.drop_layer1 = nn.Dropout(p=p)
        self.drop_layer2 = nn.Dropout(p=p)
        # Q2 architecture
        self.l4 = nn.Linear(state_dim + action_dim, (state_dim + action_dim)*2)
        self.l5 = nn.Linear((state_dim + action_dim)*2,(state_dim + action_dim)*4)
        self.l6 = nn.Linear((state_dim + action_dim)*4, 1)
        self.drop_layer3 = nn.Dropout(p=p)
        self.drop_layer4 = nn.Dropout(p=p)

    # def __init__(self, state_dim, action_dim, p=0.3):
    #     super(Critic, self).__init__()
    #
    #     # Q1 architecture
    #     self.l1 = nn.Linear(state_dim + action_dim, 256)
    #     self.l2 = nn.Linear(256, 256)
    #     self.l3 = nn.Linear(256, 1)
    #     self.drop_layer = nn.Dropout(p=p)
    #     # Q2 architecture
    #     self.l4 = nn.Linear(state_dim + action_dim, 256)
    #     self.l5 = nn.Linear(256, 256)
    #     self.l6 = nn.Linear(256, 1)

    def forward(self, state, action):
        sa = torch.cat([state, action], 1)

        q1 = F.relu(self.l1(sa))
        q1 = self.drop_layer1(q1);
        q1 = F.relu(self.l2(q1))
        q1 = self.drop_layer2(q1);
        q1 = self.l3(q1)

        q2 = F.relu(self.l4(sa))
        q2 = self.drop_layer3(q2);
        q2 = F.relu(self.l5(q2))
        q2 = self.drop_layer4(q2);
        q2 = self.l6(q2)
        return q1, q2

    def Q1(self, state, action):
        sa = torch.cat([state, action], 1)

        q1 = F.relu(self.l1(sa))
        q1 = self.drop_layer1(q1);
        q1 = F.relu(self.l2(q1))
        q1 = self.drop_layer2(q1);
        q1 = self.l3(q1)
        return q1

    # def Q1(self, state, action):
    #     sa = torch.cat([state, action], 1)
    #
    #     q1 = F.relu(self.l1(sa))
    #     q1 = self.drop_layer(q1);
    #     q1 = F.relu(self.l2(q1))
    #     q1 = self.drop_layer(q1);
    #     q1 = self.l3(q1)
    #     return q1

class TD3:
    def __init__(self, ieeeBusSystem, lr, memorySize, batchSize,  decayRate, numOfEpisodes, stepsPerEpisode,tau,policy_freq,updateAfter):
        prefix='td3'

        self.env_2bus = powerGrid_ieee2('td3');
        self.max_actions=[150,1.1]
        self.actor = Actor(24, 2)
        self.actor_target = copy.deepcopy(self.actor)
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(), lr=lr)
        self.UpdateAfter=updateAfter
        self.critic = Critic(24, 2)
        self.critic_target = copy.deepcopy(self.critic)
        self.critic_optimizer = torch.optim.Adam(self.critic.parameters(), lr=lr)

        USE_CUDA = torch.cuda.is_available();
        self.learn_step_counter = 0  # for target updating
        self.memory_counter = 0  # for storing memory
        self.memory_capacity = memorySize;
        self.memory = BasicBuffer(self.memory_capacity);
        self.learningRate = lr
        self.batch_size = batchSize
        self.numOfEpisodes = numOfEpisodes
        self.numOfSteps = stepsPerEpisode
        self.decayRate = decayRate
        self.allRewards = [];
        self.fileName = prefix + '_lr' + str(lr) +  'bs' + str(batchSize) + 'ms' + str(
            memorySize) + 'dr' + str(decayRate) + 'noe' + str(
            numOfEpisodes) + 'spe' + str(stepsPerEpisode)+'pf'+str(policy_freq)+'tau'+str(tau)+'ua'+str(self.UpdateAfter);
        self.checkPoint = 'TD3_Checkpoints/' + self.fileName + '.tar';
        print(self.checkPoint)
        if os.path.isfile(self.checkPoint):
            print('loading state values from last saved checkpoint');
            checkpoint = torch.load(self.checkPoint);
            self.actor.load_state_dict(checkpoint['actor_state_dict'])
            self.actor_target.load_state_dict(checkpoint['actorTarget_state_dict'])
            self.critic.load_state_dict(checkpoint['critic_state_dict'])
            self.critic_target.load_state_dict(checkpoint['criticTarget_state_dict'])
            self.actor_optimizer.load_state_dict(checkpoint['actorOptimizer_state_dict'])
            self.critic_optimizer.load_state_dict(checkpoint['criticOptimizer_state_dict'])
            self.allRewards = checkpoint['allRewards']
            self.learn_step_counter = checkpoint['learn_step_counter']
            self.memory = checkpoint['memory']
            self.memory_counter = checkpoint['memory_counter']

        if USE_CUDA:
            print('GPU Exists')
            self.actor.cuda()
            self.actor_target.cuda()
            self.critic.cuda()
            self.critic_target.cuda()
            for state in self.actor_optimizer.state.values():
                for k, v in state.items():
                    if isinstance(v, torch.Tensor):
                        state[k] = v.cuda()
            for state in self.critic_optimizer.state.values():
                for k, v in state.items():
                    if isinstance(v, torch.Tensor):
                        state[k] = v.cuda()



        self.tau = tau
        self.policy_noise = 0.05
        self.policy_freq = policy_freq
        self.total_it = 0
        #self.writer = SummaryWriter(
        #    'runs/' + self.fileName);
        #dummystate, dummyaction, _, _, _ = self.memory.sample(1);
        #self.writer.add_graph(self.actor,torch.FloatTensor(dummystate).cuda())
        #print(dummystate)
        #self.writer.add_graph(self.critic,
        #                      [torch.FloatTensor(dummystate).cuda(),torch.FloatTensor(dummyaction).cuda()])
        #self.writer.close()


    def select_action(self, state):
        state = torch.FloatTensor(state.reshape(1, -1)).cuda()
        return self.actor(state).cpu().data.numpy().flatten()

    def store_transition(self, s, a, r, done,s_):
        self.memory.push(s, a, r, s_, done)
        self.memory_counter += 1

    def train(self):
        self.writer = SummaryWriter(
            'runs/' + self.fileName);
        print('Has already been  trained for following num of episodes: ' + str(len(self.allRewards)))
        noe = self.numOfEpisodes - len(self.allRewards)
        self.actor.train();
        self.critic.train();
        self.env_2bus.setMode('train')
        self.runningCriticLoss = 0;
        self.runningActorLoss = 0;
        self.runningRewards = 0;
        for i in range(0, noe):
            accumulatedReward = 0;
            self.env_2bus.reset();
            currentState = [];
            for j in range(0, 3):
                m = self.env_2bus.getCurrentStateForDQN();
                m.extend(m)
                currentState.append(m);
                self.env_2bus.stateIndex += 1;
                self.env_2bus.scaleLoadAndPowerValue(self.env_2bus.stateIndex)
                self.env_2bus.runEnv(False);

            currentState.append(self.env_2bus.getCurrentStateForDQN())
            currentState[3].extend(self.env_2bus.getCurrentStateForDQN())
            currentState = np.array(currentState)
            for j in range(0, self.numOfSteps):
                action=self.select_action(currentState)
                noise0 = np.random.normal(0, 0.025*self.max_actions[0],1)
                noise1 = np.random.normal(0, 0.025*self.max_actions[1], 1)
                action[0]=max(0,min(self.max_actions[0],action[0]*self.max_actions[0]+noise0[0]))
                action[1]=max(0,min(self.max_actions[1],action[1]*self.max_actions[1]+noise1[0]))
                currentMeasurements, reward, done, _ = self.env_2bus.takeAction(action[0], action[1]);
                oldState = currentState;
                currentState = np.append(currentState, [currentMeasurements], axis=0)
                currentState = np.delete(currentState, 0, axis=0);
                self.store_transition(oldState, action, reward, 0 if done else 1, currentState)
                accumulatedReward += reward;
                if self.memory_counter > self.memory_capacity:
                    self.learn()
                if done:
                    break;

            self.allRewards.append(accumulatedReward);
            if (i + 1) % 200 == 0:
                print('Episode: ' + str(len(self.allRewards)) + '; reward:' + str(accumulatedReward))
                print('saving checkpoint data')
                torch.save({
                    'allRewards': self.allRewards,
                    'actor_state_dict': self.actor.state_dict(),
                    'actorTarget_state_dict': self.actor_target.state_dict(),
                    'critic_state_dict': self.critic.state_dict(),
                    'criticTarget_state_dict': self.critic_target.state_dict(),
                    'actorOptimizer_state_dict': self.actor_optimizer.state_dict(),
                    'criticOptimizer_state_dict': self.critic_optimizer.state_dict(),
                    'learn_step_counter': self.learn_step_counter,
                    'memory': self.memory,
                    'memory_counter': self.memory_counter
                }, self.checkPoint)
        print('training finished')

    def learn(self):
        self.learn_step_counter += 1
        if self.learn_step_counter%self.UpdateAfter == 1:
            state, action, reward,next_state, done = self.memory.sample(self.batch_size)
            state = Variable(torch.FloatTensor(state).cuda())
            action = Variable(torch.FloatTensor(action).cuda())
            done = Variable(torch.FloatTensor(done).cuda())
            next_state = Variable(torch.FloatTensor(next_state).cuda())
            reward=Variable(torch.FloatTensor(reward).cuda())
            with torch.no_grad():
                n0 = torch.distributions.Normal(torch.tensor([0.0]), torch.tensor([self.policy_noise*self.max_actions[0]]))
                n1 = torch.distributions.Normal(torch.tensor([0.0]), torch.tensor([self.policy_noise*self.max_actions[1]]))
                noise0 = n0.sample((self.batch_size,)).clamp(-8, 8).cuda()
                noise1 = n1.sample((self.batch_size,)).clamp(-0.05, 0.05).cuda()
                noise=torch.stack([noise0,noise1],dim=1).squeeze(2)
                next_action = (
                        self.actor_target(next_state)*torch.tensor(self.max_actions).cuda() + noise
                )
                # Compute the target Q value
                target_Q1, target_Q2 = self.critic_target(next_state, next_action)
                target_Q = torch.min(target_Q1, target_Q2)
                target_Q = reward.unsqueeze(1) + self.decayRate * (target_Q * done.unsqueeze(1))

            # Get current Q estimates
            current_Q1, current_Q2 = self.critic(state, action)

            # Compute critic loss
            critic_loss = F.mse_loss(current_Q1, target_Q) + F.mse_loss(current_Q2, target_Q)

            # Optimize the critic
            self.critic_optimizer.zero_grad()
            critic_loss.backward()
            self.critic_optimizer.step()

            self.runningCriticLoss += critic_loss.item()
            self.runningRewards += torch.sum(reward).item() / self.batch_size
            # Delayed policy updates
            if self.learn_step_counter % (self.policy_freq*self.UpdateAfter) == 1:

                # Compute actor loss
                actor_loss = -self.critic.Q1(state, self.actor(next_state)*torch.tensor(self.max_actions).cuda()).mean()

                # Optimize the actor
                self.actor_optimizer.zero_grad()
                actor_loss.backward()
                self.actor_optimizer.step()
                self.runningActorLoss += actor_loss.item()

                # Update the frozen target models
                for param, target_param in zip(self.critic.parameters(), self.critic_target.parameters()):
                    target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)

                for param, target_param in zip(self.actor.parameters(), self.actor_target.parameters()):
                    target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)

            if self.learn_step_counter % (self.UpdateAfter*10) == 1:  # every 200 mini-batches...

                # ...log the running loss
                self.writer.add_scalar('training loss- Critic',
                                  self.runningCriticLoss / 10,
                                  self.learn_step_counter/self.UpdateAfter +1)
                self.writer.add_scalar('training loss- Actor',
                                       self.runningActorLoss / 10,
                                       self.learn_step_counter/self.UpdateAfter +1)
                self.writer.add_scalar('avg Reward',
                                       self.runningRewards/10,
                                       self.learn_step_counter/self.UpdateAfter +1)
                self.runningRewards = 0;
                self.runningCriticLoss=0;
                self.runningActorLoss = 0;

    def lp_ref(self):
        return stat.mean(self.env_2bus.net.res_line.loading_percent)

    def runFACTSnoRL(self, v_ref, lp_ref, bus_index_shunt, bus_index_voltage, line_index, series_comp_enabl):
        # Enable/Disable devices
        self.env_2bus.net.switch.at[1, 'closed'] = False if series_comp_enabl else True
        self.env_2bus.net.switch.at[0, 'closed'] = True
        self.env_2bus.net.controller.in_service[1] = True if series_comp_enabl else False

        # Set reference values
        self.env_2bus.shuntControl.ref = v_ref;
        self.env_2bus.seriesControl.ref = lp_ref;
        self.env_2bus.runEnv(runControl=True)
        busVoltage = self.env_2bus.net.res_bus.vm_pu[bus_index_voltage]
        lp_max = max(self.env_2bus.net.res_line.loading_percent)
        lp_std = np.std(self.env_2bus.net.res_line.loading_percent)
        return busVoltage, lp_max, lp_std

    ## Run the environment controlled by greedy RL
    def runFACTSgreedyRL(self, busVoltageIndex, currentState,takeLastAction):
        action=self.select_action(currentState)
        nextStateMeasurements, reward, done, measAfterAction = self.env_2bus.takeAction(action[0]*self.max_actions[0], action[1]*self.max_actions[1])
        busVoltage = measAfterAction[0]
        lp_max = measAfterAction[1]
        lp_std = measAfterAction[2]
        return nextStateMeasurements, busVoltage, lp_max, lp_std,reward

    ## Run environment and try all actions and choose highest reward
    def runFACTSallActionsRL(self, busVoltageIndex):
        copyNetwork = copy.deepcopy(self)
        reward = 0
        bestAction = []
        rewArr = []

        #Create action space with high resolution:
        copyNetwork.actionSpace = {'v_ref_pu': [i/1000 for i in range(900, 1101)], 'lp_ref': [i for i in range(0, 151)]}
        copyNetwork.actions = ['v_ref:' + str(x) + ';lp_ref:' + str(y) for x in copyNetwork.actionSpace['v_ref_pu']
                        for y in copyNetwork.actionSpace['lp_ref']]

        # Test all actions
        for i in range(0, len(copyNetwork.actions)):
            action = copyNetwork.getActionFromIndex(i)
            nextStateMeas, rew, done, _ = copyNetwork.env_2bus.takeAction(action[0], action[1] )
            copyNetwork.env_2bus.stateIndex -= 1 # increment back as takeAction() increments +1
            rewArr.append(rew)
            if rew > reward:
                bestAction = action   # Save best action
                reward = rew
        # Take best action in actual environment
        currentStateMeasurements, reward, done, measAfterAction = self.env_2bus.takeAction(bestAction[0], bestAction[1])
        busVoltage = measAfterAction[0]
        lp_max = measAfterAction[1]
        lp_std = measAfterAction[2]
        print(' max-min rewArr: ', max(rewArr), min(rewArr))
        return currentStateMeasurements, busVoltage, lp_max, lp_std, reward

    # Compare performance wrt reward and voltage stability between RL agent, benchmark and non-RL cases.
    # Creates selection of graphs and prints other results.
    def comparePerformance(self, steps, oper_upd_interval, bus_index_shunt, bus_index_voltage, line_index,benchmarkFlag):
        v_noFACTS = []
        lp_max_noFACTS = []
        lp_std_noFACTS = []
        v_FACTS = []
        lp_max_FACTS = []
        lp_std_FACTS = []
        v_RLFACTS = []
        lp_max_RLFACTS = []
        lp_std_RLFACTS = []
        v_FACTS_noSeries = []
        lp_max_FACTS_noSeries = []
        lp_std_FACTS_noSeries = []
        v_FACTS_eachTS = []
        lp_max_FACTS_eachTS = []
        lp_std_FACTS_eachTS = []
        rewardNoFacts=[]
        rewardFacts=[]
        rewardFactsEachTS=[]
        rewardFactsNoSeries=[]
        rewardFactsRL=[]
        v_RLFACTS_AfterLoadChange = []
        lp_max_RLFACTS_AfterLoadChange = []
        self.env_2bus.setMode('test')
        self.env_2bus.reset()
        stateIndex = self.env_2bus.stateIndex
        loadProfile = self.env_2bus.loadProfile
        performance=0
        while stateIndex + steps+4 > len(loadProfile):
            self.env_2bus.reset()  # Reset to get sufficient number of steps left in time series
            stateIndex = self.env_2bus.stateIndex
            loadProfile = self.env_2bus.loadProfile

        # Create copy of network for historic measurements
        temp = copy.deepcopy(self)
        #temp.eval_net.eval()

        #Run for history measurements to get full state repr for RL.
        currentState = [];
        for j in range(0, 3):
            m = temp.env_2bus.getCurrentStateForDQN();
            m.extend(m) # creates the 2nd part of the state, "after action" but was no action with RL disabled in this part.
            currentState.append(m);
            temp.env_2bus.stateIndex += 1;
            temp.env_2bus.scaleLoadAndPowerValue(temp.env_2bus.stateIndex)
            temp.env_2bus.runEnv(False);
        currentState.append(temp.env_2bus.getCurrentStateForDQN())
        currentState[3].extend(temp.env_2bus.getCurrentStateForDQN())
        currentState = np.array(currentState) # Only used for RLFACTS case

        # Need seperate copy for each scenario
        stateIndex = temp.env_2bus.stateIndex
        qObj_env_noFACTS = copy.deepcopy(temp)
        qObj_env_FACTS = copy.deepcopy(temp)
        qObj_env_RLFACTS = copy.deepcopy(temp)
        qObj_env_FACTS_noSeries = copy.deepcopy(temp)
        qObj_env_FACTS_eachTS = copy.deepcopy(temp)


        # Make sure FACTS devices disabled for noFACTS case and no Series for that case
        qObj_env_noFACTS.env_2bus.net.switch.at[0, 'closed'] = False
        qObj_env_noFACTS.env_2bus.net.switch.at[1, 'closed'] = True
        qObj_env_FACTS_noSeries.env_2bus.net.switch.at[1, 'closed'] = True

        # To plot horizontal axis in nose-curve
        load_nom_pu = 2 #the nominal IEEE load in pu
        print(stateIndex)
        print(qObj_env_RLFACTS.env_2bus.stateIndex)
        loading_arr = list(load_nom_pu*(loadProfile[stateIndex:stateIndex + steps] / stat.mean(loadProfile)))
        loading_arr_afterLoadChange = list(load_nom_pu * (loadProfile[stateIndex+1:stateIndex + steps+1] / stat.mean(loadProfile))) # to get proper sorting for voltage after load change


        # Loop through each load
        for i in range(0, steps):
            # no FACTS
            qObj_env_noFACTS.env_2bus.runEnv(runControl=False) #No FACTS, no control
            v_noFACTS.append(qObj_env_noFACTS.env_2bus.net.res_bus.vm_pu[bus_index_voltage])
            lp_max_noFACTS.append(max(qObj_env_noFACTS.env_2bus.net.res_line.loading_percent))
            lp_std_noFACTS.append(np.std(qObj_env_noFACTS.env_2bus.net.res_line.loading_percent))
            rewardNoFacts.append((200+(math.exp(abs(1 - qObj_env_noFACTS.env_2bus.net.res_bus.vm_pu[bus_index_voltage]) * 10) * -20) - np.std(qObj_env_noFACTS.env_2bus.net.res_line.loading_percent))/200)

            # FACTS with both series and shunt
            v_ref = 1
            if i % oper_upd_interval == 0:
                lp_reference = qObj_env_FACTS.lp_ref()
                #print('oper', lp_reference)
            voltage, lp_max, lp_std = qObj_env_FACTS.runFACTSnoRL(v_ref, lp_reference, bus_index_shunt, bus_index_voltage,
                                           line_index, True)  # Series compensation enabled
            v_FACTS.append(voltage)
            lp_max_FACTS.append(lp_max)
            lp_std_FACTS.append(lp_std)
            rewFacts=(200+(math.exp(abs(1 - voltage) * 10) * -20) - lp_std)/200;


            # FACTS no Series compensation
            voltage, lp_max, lp_std = qObj_env_FACTS_noSeries.runFACTSnoRL(v_ref, lp_reference, bus_index_shunt, bus_index_voltage,
                                                          line_index, False)  # Series compensation disabled
            v_FACTS_noSeries.append(voltage)
            lp_max_FACTS_noSeries.append(lp_max)
            lp_std_FACTS_noSeries.append(lp_std)
            rewFactsNoSeries=(200+(math.exp(abs(1 - voltage) * 10) * -20) - lp_std)/200 ;

            # FACTS with both series and shunt, with system operator update EACH time step
            lp_reference_eachTS = qObj_env_FACTS_eachTS.lp_ref()
            #print('eachTS', lp_reference_eachTS)
            voltage, lp_max, lp_std = qObj_env_FACTS_eachTS.runFACTSnoRL(v_ref, lp_reference_eachTS, bus_index_shunt, bus_index_voltage,
                                                          line_index, True)  # Series compensation enabled
            v_FACTS_eachTS.append(voltage)
            lp_max_FACTS_eachTS.append(lp_max)
            lp_std_FACTS_eachTS.append(lp_std)
            #rewFactsEachTS=(200+(math.exp(abs(1 - voltage) * 10) * -20) - lp_std)/200 ;

            # RLFACTS
            takeLastAction=False;
            qObj_env_RLFACTS.actor.eval();
            currentMeasurements, voltage, lp_max, lp_std,r = qObj_env_RLFACTS.runFACTSgreedyRL(bus_index_voltage, currentState, takeLastAction)  # runpp is done within this function
            currentState = np.append(currentState, [currentMeasurements], axis=0)
            currentState = np.delete(currentState, 0, axis=0);

            v_RLFACTS.append(voltage)
            lp_max_RLFACTS.append(lp_max)
            lp_std_RLFACTS.append(lp_std)
            rewardFactsRL.append(r)          # FACTS with both series and shunt
            v_RLFACTS_AfterLoadChange.append(qObj_env_RLFACTS.env_2bus.net.res_bus.vm_pu[1])
            lp_max_RLFACTS_AfterLoadChange.append(max(qObj_env_RLFACTS.env_2bus.net.res_line.loading_percent))

            # Increment state
            stateIndex += 1
            qObj_env_noFACTS.env_2bus.scaleLoadAndPowerValue(stateIndex) #Only for these, rest are incremented within their respective functions
            qObj_env_FACTS.env_2bus.scaleLoadAndPowerValue(stateIndex)
            qObj_env_FACTS_noSeries.env_2bus.scaleLoadAndPowerValue(stateIndex)
            qObj_env_FACTS_eachTS.env_2bus.scaleLoadAndPowerValue(stateIndex)
            rewFacts=0.7*rewFacts + 0.3*(200 + (math.exp(abs(1 - qObj_env_FACTS.env_2bus.net.res_bus.vm_pu[1]) * 10) * -20) - np.std(qObj_env_FACTS.env_2bus.net.res_line.loading_percent)) / 200
            rewardFacts.append(rewFacts)
            rewFactsNoSeries=0.7*rewFactsNoSeries + 0.3*(200 + (math.exp(abs(1 - qObj_env_FACTS_noSeries.env_2bus.net.res_bus.vm_pu[1]) * 10) * -20) - np.std(qObj_env_FACTS_noSeries.env_2bus.net.res_line.loading_percent)) / 200
            rewardFactsNoSeries.append(rewFactsNoSeries)
            rewFactsEachTS=0.7*rewFacts + 0.3*(200 + (math.exp(abs(1 - qObj_env_FACTS_eachTS.env_2bus.net.res_bus.vm_pu[1]) * 10) * -20) - np.std(qObj_env_FACTS_eachTS.env_2bus.net.res_line.loading_percent)) / 200
            rewardFactsEachTS.append(rewFactsEachTS)             # FACTS with both series and shunt
            if (rewFacts-r < 0.01) and (rewFactsNoSeries-r < 0.01):
                performance+=1

        print('RL better than no RL in % wrt to reward (Upsilon): ', (performance / steps)*100)
        print('max reward facts:', np.max(rewardFacts))
        print('max reward facts with RL:', np.max(rewardFactsRL))
        print('max reward facts no series:', np.max(rewardFactsNoSeries))
        print('min reward facts:', np.min(rewardFacts))
        print('min reward facts with RL:', np.min(rewardFactsRL))
        print('min reward facts no series:', np.min(rewardFactsNoSeries))
        print('mean reward facts:', np.mean(rewardFacts))
        print('mean reward facts with RL:', np.mean(rewardFactsRL))
        print('mean reward facts no series:', np.mean(rewardFactsNoSeries))
        print('std reward facts:', np.std(rewardFacts))
        print('std reward facts with RL:', np.std(rewardFactsRL))
        print('std reward facts no series:', np.std(rewardFactsNoSeries))

        #remove last element in voltage after load change to get correct dimensions
        v_RLFACTS_AfterLoadChange.pop()

        # Get benchmark from pickle files:
        with open('Data/voltBenchmark.pkl', 'rb') as pickle_file:
            v_RLFACTS_Benchmark = pickle.load(pickle_file)
            v_RLFACTS_Benchmark = v_RLFACTS_Benchmark[0:steps]
        with open('Data/lpmaxBenchmark.pkl', 'rb') as pickle_file:
            lp_max_RLFACTS_Benchmark = pickle.load(pickle_file)
            lp_max_RLFACTS_Benchmark = lp_max_RLFACTS_Benchmark[0:steps]
        with open('Data/lpstdBenchmark.pkl', 'rb') as pickle_file:
            lp_std_RLFACTS_Benchmark = pickle.load(pickle_file)
            #print(lp_std_RLFACTS_Benchmark)
            lp_std_RLFACTS_Benchmark = lp_std_RLFACTS_Benchmark[0:steps]
            #print(lp_std_RLFACTS_Benchmark)
        with open('Data/rewBenchmark.pkl', 'rb') as pickle_file:
            rewardFactsBenchmark = pickle.load(pickle_file)
            rewardFactsBenchmark = rewardFactsBenchmark[0:steps]


        # Make plots
        i_list = list(range(863, 863+steps))
        lw = 1.8
        fig, ax1 = plt.subplots()
        color = 'tab:blue'
        ax1.set_title('Voltage and line loading standard deviation for test set', fontsize=23)
        ax1.set_xlabel('Time step [-]', fontsize=19)
        ax1.set_ylabel('Bus Voltage [pu]', color=color, fontsize=19)
        ax1.plot(i_list, v_noFACTS, color=color)
        ax1.plot(i_list, v_FACTS, color='g')
        ax1.plot(i_list, v_FACTS_noSeries, color='k')
        ax1.plot(i_list, v_RLFACTS, color='r')
        # ax1.plot(i_list, v_FACTS_eachTS, color= 'c')
        if benchmarkFlag:
            ax1.plot(i_list, v_RLFACTS_Benchmark, color='y')

        # ax1.legend(['v no facts', 'v facts' , 'v facts no series comp','v RL facts', 'v RL facts upd each ts', 'v RL benchmark'], loc=2)
        ax1.legend(['v no FACTS', 'v shunt+series', 'v hunt only', 'v TD3', 'v RL benchmark'], loc=2, fontsize=14)
        ax2 = ax1.twinx()

        color = 'tab:blue'
        ax2.set_ylabel('line loading percentage std [% units]', color='m', fontsize=19)
        ax2.plot(i_list, lp_std_noFACTS, color=color, linestyle='dashed')
        ax2.plot(i_list, lp_std_FACTS, color='g', linestyle='dashed')
        ax2.plot(i_list, lp_std_FACTS_noSeries, color='k', linestyle='dashed')
        ax2.plot(i_list, lp_std_RLFACTS, color='r', linestyle='dashed')
        # ax2.plot(i_list, lp_std_FACTS_eachTS, color='c', linestyle = 'dashed')
        if benchmarkFlag:
            ax2.plot(i_list, lp_std_RLFACTS_Benchmark, color='y', linestyle='dashed')
        # ax2.legend(['std lp no facts', 'std lp facts', 'std lp facts no series comp', 'std lp RL facts', 'std lp facts each ts', 'std lp RL benchmark' ], loc=1)
        ax2.legend(['std lp no FACTS', 'std lp shunt+series', 'std lp shunt only', 'std lp TD3',
                    'std lp RL benchmark'], loc=1, fontsize=14)
        plt.grid()
        plt.show()

        # Plot Rewards
        fig2, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True, sharey=True)
        fig2.suptitle('Rewards along the test set', fontsize=24)
        plt.xlabel('Time step [-]', Figure=fig2, fontsize=20)
        ax1.set_ylabel('Reward [-]', Figure=fig2, fontsize=20)
        ax2.set_ylabel('Reward [-]', Figure=fig2, fontsize=20)
        ax3.set_ylabel('Reward [-]', Figure=fig2, fontsize=20)
        plt.xticks(fontsize=16)
        plt.yticks(fontsize=16)
        xtickers = [800, 900, 1000, 1100, 1200, 1300, 1400]
        ytickers = [0.5, 0.6, 0.7, 0.8, 0.9]
        ax1.set_xticklabels(xtickers, fontsize=16)
        ax1.set_yticklabels(ytickers, fontsize=16)
        ax2.set_xticklabels(xtickers, fontsize=16)
        ax2.set_yticklabels(ytickers, fontsize=16)
        ax3.set_xticklabels(xtickers, fontsize=16)
        ax3.set_yticklabels(ytickers, fontsize=16)
        ax1.plot(i_list, rewardFactsRL, Figure=fig2, color='tab:red')
        if benchmarkFlag:
            ax1.plot(i_list, rewardFactsBenchmark, Figure=fig2, color='tab:olive')
        ax2.plot(i_list, rewardFacts, Figure=fig2, color='tab:green')
        ax2.plot(i_list, rewardFactsNoSeries, Figure=fig2, color='k')
        ax3.plot(i_list, rewardNoFacts, Figure=fig2, color='tab:brown')
        # plt.title('Rewards along the test set', fontsize=24)
        ax1.legend(['TD3', 'RL benchmark'],
                   loc=3, fontsize=14)
        ax2.legend(['shunt+series', 'shunt only'],
                   loc=3, fontsize=14)
        ax3.legend(['no FACTS'],
                   loc=3, fontsize=14)
        ax1.grid()
        ax1.minorticks_on()
        ax1.grid(b=True, which='minor', color='#999999', linestyle='-', alpha=0.2)
        ax2.grid()
        ax2.minorticks_on()
        ax2.grid(b=True, which='minor', color='#999999', linestyle='-', alpha=0.2)
        ax3.grid()
        ax3.minorticks_on()
        ax3.grid(b=True, which='minor', color='#999999', linestyle='-', alpha=0.2)
        plt.show()

        ## Calculate measure for comparing RL and Benchmark wrt reward.
        performanceFactsRL = 0
        performanceFacts = 0
        performanceFactsnoSeries = 0
        PerformanceNoFacts = 0
        for i in range(0, steps):
            performanceFactsRL += math.sqrt((rewardFactsRL[i] - rewardFactsBenchmark[i]) ** 2)
            performanceFacts += math.sqrt((rewardFacts[i] - rewardFactsBenchmark[i]) ** 2)
            performanceFactsnoSeries += math.sqrt((rewardFactsNoSeries[i] - rewardFactsBenchmark[i]) ** 2)
            PerformanceNoFacts += math.sqrt((rewardNoFacts[i] - rewardFactsBenchmark[i]) ** 2)

        print('')
        print('performance FACTS RL (Psi_rootsquare): ', performanceFactsRL)
        print('performance FACTS shunt+series (Psi_rootsquare): ', performanceFacts)
        print('performance FACTS shunt only (Psi_rootsquare): ', performanceFactsnoSeries)
        print('performance no FACTS (Psi_rootsquare): ', PerformanceNoFacts)

        # Nosecurve:
        loading_arr_sorted = sorted(loading_arr)
        loading_arr_afterLoadChange_sorted = sorted(loading_arr_afterLoadChange)

        # Sort the measurements
        v_noFACTS_sorted = [x for _, x in sorted(zip(loading_arr, v_noFACTS))]
        lp_max_noFACTS_sorted = [x for _, x in sorted(zip(loading_arr, lp_max_noFACTS))]
        v_FACTS_sorted = [x for _, x in sorted(zip(loading_arr, v_FACTS))]
        lp_max_FACTS_sorted = [x for _, x in sorted(zip(loading_arr, lp_max_FACTS))]
        v_RLFACTS_sorted = [x for _, x in sorted(zip(loading_arr, v_RLFACTS))]
        lp_max_RLFACTS_sorted = [x for _, x in sorted(zip(loading_arr, lp_max_RLFACTS))]
        v_FACTS_noSeries_sorted = [x for _, x in sorted(zip(loading_arr, v_FACTS_noSeries))]
        lp_max_FACTS_noSeries_sorted = [x for _, x in sorted(zip(loading_arr, lp_max_FACTS_noSeries))]
        v_FACTS_eachTS_sorted = [x for _, x in sorted(zip(loading_arr, v_FACTS_eachTS))]
        lp_max_FACTS_eachTS_sorted = [x for _, x in sorted(zip(loading_arr, lp_max_FACTS_eachTS))]
        if benchmarkFlag:
            v_RLFACTS_Benchmark_sorted = [x for _, x in sorted(zip(loading_arr, v_RLFACTS_Benchmark))]
            lp_max_RLFACTS_Benchmark_sorted = [x for _, x in sorted(zip(loading_arr, lp_max_RLFACTS_Benchmark))]
        v_RLFACTS_AfterLoadChange_sorted = [x for _, x in sorted(zip(loading_arr_afterLoadChange, v_RLFACTS_AfterLoadChange))]
        lp_max_RLFACTS_AfterLoadChange_sorted = [x for _, x in
                                                 sorted(zip(loading_arr_afterLoadChange, lp_max_RLFACTS_AfterLoadChange))]
        print('')
        print('maximum loading percentage noFACTS  ', max(lp_max_noFACTS))
        print('maximum loading percentage Shunt+Series  ', max(lp_max_FACTS))
        print('maximum loading percentage shunt only  ', max(lp_max_FACTS_noSeries))
        print('maximum loading percentage after action RL: ', max(lp_max_RLFACTS_Benchmark))
        print('maximum loading percentage after load change RL: ', max(lp_max_RLFACTS_AfterLoadChange))

        # Trim arrays to only include values <= X % loading percentage
        lp_limit_for_noseCurve = 100
        lp_max_noFACTS_sorted_trim = [x for x in lp_max_noFACTS_sorted if x <= lp_limit_for_noseCurve]
        lp_max_FACTS_sorted_trim = [x for x in lp_max_FACTS_sorted if x <= lp_limit_for_noseCurve]
        lp_max_RLFACTS_sorted_trim = [x for x in lp_max_RLFACTS_sorted if x <= lp_limit_for_noseCurve]
        lp_max_FACTS_noSeries_sorted_trim = [x for x in lp_max_FACTS_noSeries_sorted if x <= lp_limit_for_noseCurve]
        lp_max_FACTS_eachTS_sorted_trim = [x for x in lp_max_FACTS_eachTS_sorted if x <= lp_limit_for_noseCurve]
        if benchmarkFlag:
            lp_max_RLFACTS_Benchmark_sorted_trim = [x for x in lp_max_RLFACTS_Benchmark_sorted if
                                                    x <= lp_limit_for_noseCurve]
        lp_max_RLFACTS_AfterLoadChange_sorted_trim = [x for x in lp_max_RLFACTS_AfterLoadChange_sorted if
                                                      x <= lp_limit_for_noseCurve]

        v_noFACTS_sorted_trim = v_noFACTS_sorted[0:len(lp_max_noFACTS_sorted_trim)]
        v_FACTS_sorted_trim = v_FACTS_sorted[0:len(lp_max_FACTS_sorted_trim)]
        v_RLFACTS_sorted_trim = v_RLFACTS_sorted[0:len(lp_max_RLFACTS_sorted_trim)]
        v_FACTS_noSeries_sorted_trim = v_FACTS_noSeries_sorted[0:len(lp_max_FACTS_noSeries_sorted_trim)]
        v_FACTS_eachTS_sorted_trim = v_FACTS_eachTS_sorted[0:len(lp_max_FACTS_eachTS_sorted_trim)]
        if benchmarkFlag:
            v_RLFACTS_Benchmark_sorted_trim = v_RLFACTS_Benchmark_sorted[0:len(lp_max_RLFACTS_Benchmark_sorted_trim)]
        v_RLFACTS_AfterLoadChange_sorted_trim = v_RLFACTS_AfterLoadChange_sorted[
                                                0:len(lp_max_RLFACTS_AfterLoadChange_sorted_trim)]

        loading_arr_plot_noFACTS = loading_arr_sorted[0:len(lp_max_noFACTS_sorted_trim)]
        loading_arr_plot_FACTS = loading_arr_sorted[0:len(lp_max_FACTS_sorted_trim)]
        loading_arr_plot_RLFACTS = loading_arr_sorted[0:len(lp_max_RLFACTS_sorted_trim)]
        loading_arr_plot_FACTS_noSeries = loading_arr_sorted[0:len(lp_max_FACTS_noSeries_sorted_trim)]
        loading_arr_plot_FACTS_eachTS = loading_arr_sorted[0:len(lp_max_FACTS_eachTS_sorted_trim)]
        if benchmarkFlag:
            loading_arr_plot_RLFACTS_Benchmark = loading_arr_sorted[0:len(lp_max_RLFACTS_Benchmark_sorted_trim)]
        loading_arr_plot_RLFACTS_AfterLoadChange = loading_arr_afterLoadChange_sorted[
                                                   0:len(lp_max_RLFACTS_AfterLoadChange_sorted_trim) + 0]

        # Print result wrt trimmed voltage
        print('')
        print('max voltage facts (v1):', np.max(v_FACTS_sorted_trim))
        print('max voltage facts with RL (v1):', np.max(v_RLFACTS_sorted_trim))
        print('max voltage facts no series (v1):', np.max(v_FACTS_noSeries_sorted_trim))
        print('min voltage facts (v1):', np.min(v_FACTS_sorted_trim))
        print('min voltage facts with RL (v1):', np.min(v_RLFACTS_sorted_trim))
        print('min voltage facts no series (v1):', np.min(v_FACTS_noSeries_sorted_trim))
        print('mean voltage facts (v1):', np.mean(v_FACTS_sorted_trim))
        print('mean voltage facts with RL (v1):', np.mean(v_RLFACTS_sorted_trim))
        print('mean voltage facts no series (v1):', np.mean(v_FACTS_noSeries_sorted_trim))
        print('std voltage facts (v1):', np.std(v_FACTS_sorted_trim))
        print('std voltage facts with RL (v1):', np.std(v_RLFACTS_sorted_trim))
        print('std voltage facts no series (v1):', np.std(v_FACTS_noSeries_sorted_trim))
        print('')
        print('max voltage RL after load change (v2): ', np.max(v_RLFACTS_AfterLoadChange))
        print('min voltage RL after load change (v2): ', np.min(v_RLFACTS_AfterLoadChange))
        print('mean voltage RL after load change (v2): ', np.mean(v_RLFACTS_AfterLoadChange))
        print('std voltage RL after load change (v2): ', np.std(v_RLFACTS_AfterLoadChange))

        # Plot Nose Curve
        fig3 = plt.figure()
        markersize =44
        plt.scatter(loading_arr_plot_noFACTS, v_noFACTS_sorted_trim, marker='x', Figure=fig3, color='tab:brown', s=markersize)
        plt.scatter(loading_arr_plot_FACTS, v_FACTS_sorted_trim, marker='v', Figure=fig3, color='tab:green', s=markersize)
        plt.scatter(loading_arr_plot_FACTS_noSeries, v_FACTS_noSeries_sorted_trim, marker='^', Figure=fig3, color='k',
                    s=markersize)
        plt.scatter(loading_arr_plot_RLFACTS, v_RLFACTS_sorted_trim, marker='D', Figure=fig3, color='tab:red', s=markersize*1.6)
        plt.scatter(loading_arr_plot_RLFACTS_AfterLoadChange, v_RLFACTS_AfterLoadChange_sorted_trim, marker='d', Figure=fig3,
                    color='tab:blue', s=markersize)
        if benchmarkFlag:
            plt.plot(loading_arr_plot_RLFACTS_Benchmark, v_RLFACTS_Benchmark_sorted_trim, Figure=fig3, color='tab:olive', linewidth=lw*1.5)#, s=markersize, marker='*')
        plt.title('Nose-curve from test set with sorted voltage levels', fontsize=24)
        plt.xlabel('Loading [pu]', Figure=fig3, fontsize=20)
        plt.ylabel('Bus Voltage [pu]', Figure=fig3, fontsize=20)
        plt.xticks(fontsize=16)
        plt.yticks(fontsize=16)
        plt.legend(['RL benchmark', 'no FACTS', 'shunt+series', 'shunt only', 'TD3 $v_1$', 'TD3 $v_2$'], loc=3, fontsize=16)
        plt.grid()
        plt.show()


