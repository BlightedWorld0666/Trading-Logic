"""CPU-only joint-action tabular Q-learning for a small virtual stock/crypto portfolio."""
import copy
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
import random
from statistics import mean
from .core import Settings, simulate
from .research import brief

FEATURE_VERSION = 'ready-trend-momentum-position-cash-drawdown-v1'

@dataclass(frozen=True)
class LearningConfig:
    episodes: int = 200
    seed: int = 666
    alpha: float = .15
    gamma: float = .95
    epsilon_start: float = .8
    epsilon_end: float = .05
    drawdown_penalty: float = 2.0
    turnover_penalty: float = .0005

    def validate(self):
        if type(self.episodes) is not int or not 2 <= self.episodes <= 2000 or type(self.seed) is not int:
            raise ValueError('Use 2–2,000 episodes and an integer seed.')
        values=(self.alpha,self.gamma,self.epsilon_start,self.epsilon_end,self.drawdown_penalty,self.turnover_penalty)
        if not all(type(v) in (int,float) and math.isfinite(v) for v in values):
            raise ValueError('Learning parameters must be finite numbers.')
        if not 0 < self.alpha <= 1 or not 0 <= self.gamma < 1 or not 0 <= self.epsilon_end <= self.epsilon_start <= 1:
            raise ValueError('Invalid learning rate, discount or exploration settings.')
        if not 0 <= self.drawdown_penalty <= 100 or not 0 <= self.turnover_penalty <= 1:
            raise ValueError('Invalid reward penalties.')
        return self


def bucket(value, tolerance):
    return -1 if value < -tolerance else 1 if value > tolerance else 0


def state_key(evidence, symbols):
    """Fixed bins, no fitted scaler or future observations."""
    state=[]
    for symbol in symbols:
        closes=[b['close'] for b in evidence['bars'].get(symbol, [])]
        if len(closes)<30:
            trend=momentum=0
        else:
            trend=bucket(mean(closes[-10:])/mean(closes[-30:])-1,.003)
            momentum=bucket(closes[-1]/closes[-6]-1,.01)
        state.extend((int(len(closes)>=30),trend,momentum,int(evidence['positions'].get(symbol,0)>0)))
    equity=max(evidence['equity'],1e-12)
    state.extend((min(3,int(max(0,evidence['cash']/equity)*4)),
                  min(3,int(max(0,evidence['drawdown'])*40))))
    return ','.join(map(str,state))


def actions_from_mask(mask,symbols):
    # A target exposure is either long (buy/keep) or flat (sell/stay cash).
    return {s:'buy' if mask & (1<<i) else 'sell' for i,s in enumerate(symbols)}


def greedy(table,key,count):
    values=table.get(key)
    if values is None:
        return 0  # Unseen states default to cash, not exploratory orders.
    return max(range(count),key=lambda action:(values[action],-action))


class Policy:
    def __init__(self,symbols,table=None,mode='q_learning'):
        self.symbols=tuple(symbols);self.table=copy.deepcopy(table or {});self.mode=mode
        self.seen=0;self.unseen=0
    def __call__(self,evidence,symbols):
        if tuple(symbols)!=self.symbols:
            raise ValueError('Policy symbols differ from this portfolio.')
        key=state_key(evidence,self.symbols)
        if self.mode!='cash':
            if key in self.table:self.seen+=1
            else:self.unseen+=1
        mask=0 if self.mode=='cash' else greedy(self.table,key,2**len(self.symbols))
        return {'actions':actions_from_mask(mask,self.symbols),'reason':'Frozen policy; unseen states fall back to cash.',
                'policy_state':key,'policy_action':mask}
    def artifact(self,kinds,settings):
        return {'schema_version':1,'algorithm':self.mode,'features':FEATURE_VERSION,
                'symbols':list(self.symbols),'asset_classes':kinds,'settings':asdict(settings),'q_table':self.table}


class Learner(Policy):
    def __init__(self,symbols,table,config,rng,epsilon,capital,end):
        # Deliberately shares only the training Q table.
        self.symbols=tuple(symbols);self.table=table;self.mode='q_learning'
        self.config=config;self.rng=rng;self.epsilon=epsilon;self.capital=capital;self.end=end
        self.previous=None;self.experiences=[];self.total_reward=0
    def update(self,evidence,key,terminal):
        if self.previous is None:return
        prior,old_key,action=self.previous
        reward=(math.log(max(evidence['net_equity'],1e-12)/max(prior['net_equity'],1e-12))
                -self.config.drawdown_penalty*max(0,evidence['max_drawdown']-prior['max_drawdown'])
                -self.config.turnover_penalty*max(0,evidence['turnover']-prior['turnover'])/self.capital)
        row=self.table.setdefault(old_key,[0.0]*(2**len(self.symbols)))
        future=0 if terminal else max(self.table.get(key,[0.0]*(2**len(self.symbols))))
        target=reward+self.config.gamma*future
        row[action]+=self.config.alpha*(target-row[action])
        self.total_reward+=reward
        self.experiences.append({'state':old_key,'action':action,'reward':reward,'next_state':key,
                                 'terminal':terminal,'decision_at':prior['timestamp'],
                                 'outcome_at':evidence['timestamp'],'net_equity':evidence['net_equity']})
        self.previous=None
    def __call__(self,evidence,symbols):
        if tuple(symbols)!=self.symbols:raise ValueError('Training symbols changed.')
        key=state_key(evidence,self.symbols);terminal=evidence['timestamp']==self.end
        self.update(evidence,key,terminal)
        if terminal:return {'actions':{s:'hold' for s in symbols},'reason':'Training episode complete.'}
        action=self.rng.randrange(2**len(symbols)) if self.rng.random()<self.epsilon else greedy(self.table,key,2**len(symbols))
        self.previous=(copy.deepcopy(evidence),key,action)
        return {'actions':actions_from_mask(action,symbols),'reason':'Training exploration with virtual cash.'}
    def finish(self,result,end):
        # A halt suppresses further decisions. Attribute delayed exits and costs to the last action.
        if self.previous is not None:
            self.update({'timestamp':end,'net_equity':result['final_equity'],
                         'max_drawdown':result['max_drawdown_pct']/100,'turnover':result['turnover']},None,True)


def dataset_hash(bars):
    rows=[[b.timestamp.isoformat(),b.symbol,b.asset_class,b.open,b.high,b.low,b.close,b.volume] for b in sorted(bars,key=lambda b:(b.timestamp,b.symbol))]
    return hashlib.sha256(json.dumps(rows,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def partition(bars):
    times=sorted({b.timestamp for b in bars})
    symbols=sorted({b.symbol for b in bars})
    if not 1 <= len(symbols) <= 4:raise ValueError('This joint-action alpha supports 1–4 symbols.')
    if len(times)<150:raise ValueError('Training requires at least 150 distinct timestamps.')
    validation=times[int(len(times)*.6)];test=times[int(len(times)*.8)]
    kinds={s:next(b.asset_class for b in bars if b.symbol==s) for s in symbols}
    for symbol in symbols:
        counts=[sum(b.symbol==symbol and predicate(b.timestamp) for b in bars) for predicate in
                (lambda t:t<validation,lambda t:validation<=t<test,lambda t:t>=test)]
        if counts[0]<40 or min(counts[1:])<20:
            raise ValueError(f'{symbol} needs 40 training and 20 validation/test bars per period.')
    return symbols,kinds,validation,test


def evaluate(bars,policy,settings,start):
    frozen=Policy(policy.symbols,policy.table,policy.mode)
    result=simulate(bars,{s:'cash' for s in policy.symbols},settings,start,frozen)
    if any('error_type' in d for d in result['decisions']):raise ValueError('Policy evaluation encountered an invalid decision.')
    result['policy_coverage']={'seen_decisions':frozen.seen,'unseen_decisions':frozen.unseen}
    return result


def train(bars,settings=None,config=None,source='synthetic_demo',progress=None):
    settings=(settings or Settings()).validate();config=(config or LearningConfig()).validate()
    symbols,kinds,val_start,test_start=partition(bars)
    training=sorted([b for b in bars if b.timestamp<val_start],key=lambda b:(b.timestamp,b.symbol))
    validation=sorted([b for b in bars if b.timestamp<test_start],key=lambda b:(b.timestamp,b.symbol))
    times=sorted({b.timestamp for b in training});warmup=times[30]
    table={};rng=random.Random(config.seed);episodes=[];checkpoints=[]
    candidate_episodes=sorted({max(1,int(config.episodes*f)) for f in (.25,.5,.75,1)})
    for episode in range(1,config.episodes+1):
        fraction=(episode-1)/(config.episodes-1)
        epsilon=config.epsilon_start+(config.epsilon_end-config.epsilon_start)*fraction
        learner=Learner(symbols,table,config,rng,epsilon,settings.capital,times[-1].isoformat())
        result=simulate(training,{s:'cash' for s in symbols},settings,warmup,learner)
        if any('error_type' in d for d in result['decisions']):raise ValueError('Training decision failed; refusing a corrupted model.')
        learner.finish(result,times[-1].isoformat())
        episodes.append({'episode':episode,'epsilon':epsilon,'reward':learner.total_reward,
                         'net_return_pct':result['net_return_pct'],'drawdown_pct':result['max_drawdown_pct'],
                         'fills':result['fill_count'],'states':len(table)})
        if episode in candidate_episodes:
            policy=Policy(symbols,table)
            score=evaluate(validation,policy,settings,val_start)
            checkpoints.append({'episode':episode,'policy':policy,'validation':brief(score)})
        if progress and (episode in candidate_episodes or episode==1):progress(episodes[-1])
    cash=Policy(symbols,mode='cash')
    cash_score=evaluate(validation,cash,settings,val_start)
    options=[{'episode':0,'policy':cash,'validation':brief(cash_score)},*checkpoints]
    winner=max(options,key=lambda c:(c['validation']['score'],c['episode']==0,-c['episode']))
    chosen=winner['policy']
    # Test is touched only after selection, using the frozen winning policy.
    test_result=evaluate(bars,chosen,settings,test_start)
    baselines={name:brief(simulate(bars,{s:rule for s in symbols},settings,test_start))
               for name,rule in [('cash','cash'),('fixed_trend','trend'),('buy_and_hold','hold')]}
    notices=['Repeated episodes replay the same training prices; they are not additional independent evidence.',
             'Validation selects from four prespecified checkpoints and cash; test data never update the Q table.',
             'Reusing this dataset after looking at the test result makes that test no longer untouched.',
             'Fixed coarse state bins omit much market information. This is a tabular alpha, not a complete market model.',
             'Unseen states target cash. Exposure caps and the shared halt remain controlled by the simulator.',
             'Rewards include net estimated-liquidation equity, increasing maximum drawdown and turnover penalties.',
             'Ollama weights are unchanged. This Q table is a separate learned policy, not LLM fine-tuning.',
             'Imported data need verified provenance and adjustments; synthetic data cannot establish an edge.']
    if chosen.mode=='cash':status='validation_selected_cash'
    elif source=='synthetic_demo':status='demo_only_not_eligible_for_live_trading'
    else:status='requires_new_forward_paper_evaluation'
    report={'version':'0.2.0','source':source,'dataset_sha256':dataset_hash(bars),'settings':asdict(settings),
            'learning':asdict(config),'split':{'training_end_exclusive':val_start.isoformat(),
                                             'validation_end_exclusive':test_start.isoformat(),
                                             'test_end':max(b.timestamp for b in bars).isoformat()},
            'reward':'log(net liquidation equity ratio) - drawdown_penalty * increase in maximum drawdown - turnover_penalty * turnover / initial capital',
            'selection':'Maximum validation net return % minus 1.5 × validation drawdown %; cash wins ties.',
            'selected_episode':winner['episode'],'status':status,'episodes':episodes,
            'validation_candidates':[{'episode':c['episode'],'algorithm':c['policy'].mode,'metrics':c['validation']} for c in options],
            'test':test_result,'test_baselines':baselines,'limitations':notices}
    artifact=chosen.artifact(kinds,settings)
    artifact.update({'dataset_sha256':report['dataset_sha256'],'training_end_exclusive':val_start.isoformat(),
                     'test_start':test_start.isoformat(),'selected_episode':winner['episode']})
    candidate=max(checkpoints,key=lambda c:(c['validation']['score'],-c['episode']))
    candidate_artifact=candidate['policy'].artifact(kinds,settings)
    candidate_artifact.update({'dataset_sha256':report['dataset_sha256'],
                              'training_end_exclusive':val_start.isoformat(),'test_start':test_start.isoformat(),
                              'selected_episode':candidate['episode'],'role':'research_candidate_not_selected_unless_it_beats_cash'})
    report['research_candidate_episode']=candidate['episode']
    return artifact,report,learner.experiences,candidate_artifact


def load_policy(value,symbols,kinds,settings):
    if not 1 <= len(symbols) <= 4:raise ValueError('Policies support 1–4 symbols.')
    if not isinstance(value,dict) or value.get('schema_version')!=1 or value.get('features')!=FEATURE_VERSION or value.get('algorithm') not in ('cash','q_learning'):
        raise ValueError('Unsupported policy format.')
    if value.get('symbols')!=sorted(symbols) or value.get('asset_classes')!=kinds or value.get('settings')!=asdict(settings):
        raise ValueError('Policy symbols, asset classes and risk/cost settings must match the paper run.')
    table=value.get('q_table')
    if not isinstance(table,dict) or len(table)>200000:
        raise ValueError('Invalid or oversized Q table.')
    for key,row in table.items():
        if not isinstance(key,str) or len(key)>200 or not isinstance(row,list) or len(row)!=2**len(symbols) or not all(type(v) in (int,float) and math.isfinite(v) for v in row):
            raise ValueError('Invalid policy state/action values.')
    return Policy(sorted(symbols),table,value['algorithm'])
