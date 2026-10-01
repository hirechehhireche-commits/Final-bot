"""
Genetic Algorithm V130 Continuous - من 70020 إلى 80000
يعمل في الخلفية
"""
import pickle, sys, random, time, copy
sys.path.insert(0, '/home/user/clean_titan_bot')
import titan_juggernaut_bot as TJB
import numpy as np
from pathlib import Path

print("📦 تحميل بيانات...")
with open('/home/user/clean_titan_bot/titans_4h_5y_cache.pkl', 'rb') as f:
    store = pickle.load(f)

print(f"✅ {len(store)} عملة")

# تحميل أفضل genome حالي
try:
    with open('/tmp/v130_ga_best.pkl','rb') as f:
        base_genome = pickle.load(f)
    print(f"🏆 Base: Gen{base_genome['generation']} {base_genome['metrics']['final_nav']:.2f}$")
    start_gen = base_genome['generation']
except:
    with open('/home/user/clean_titan_bot/gen70000_supreme_dual_apex.pkl','rb') as f:
        base_genome = pickle.load(f)
    base_genome = {
        "strategy1_capital": base_genome["strategy1_capital"],
        "strategy2_capital": base_genome["strategy2_capital"],
        "pool_budgets": base_genome["pool_budgets"],
        "pool1_params": base_genome["pool1_params"],
        "pool2_params": base_genome["pool2_params"],
        "pool3_params": base_genome["pool3_params"],
        "strategy2_params": base_genome["strategy2_params"],
        "v130": {"t3_mult": 1.6, "score_thresh": 70},
        "metrics": base_genome["metrics"],
        "generation": 70000
    }
    start_gen = 70000
    print(f"🏆 Base: Gen70000 {base_genome['metrics']['final_nav']:.2f}$")

def create_genome(base):
    return {
        "strategy1_capital": base["strategy1_capital"],
        "strategy2_capital": base["strategy2_capital"],
        "pool_budgets": base["pool_budgets"][:],
        "pool1_params": copy.deepcopy(base["pool1_params"]),
        "pool2_params": copy.deepcopy(base["pool2_params"]),
        "pool3_params": copy.deepcopy(base["pool3_params"]),
        "strategy2_params": copy.deepcopy(base["strategy2_params"]),
        "v130": copy.deepcopy(base.get("v130", {"t3_mult": 1.6, "score_thresh": 70}))
    }

def mutate(genome, rate=0.18):
    g = copy.deepcopy(genome)
    if random.random() < rate:
        g["strategy1_capital"] = max(300, min(395, g["strategy1_capital"] + random.uniform(-4, 4)))
        g["strategy2_capital"] = 400 - g["strategy1_capital"]
    if random.random() < rate:
        b = [max(0.5, x + random.uniform(-1.5, 1.5)) for x in g["pool_budgets"]]
        s = sum(b)
        g["pool_budgets"] = [x/s*100 for x in b]
    for pk in ["pool1_params", "pool2_params", "pool3_params", "strategy2_params"]:
        p = g[pk]
        if random.random() < rate:
            if "sl_atr_mult" in p:
                p["sl_atr_mult"] = max(1.2, min(2.8, p["sl_atr_mult"] * random.uniform(0.93, 1.07)))
            if "t1_atr_mult" in p:
                p["t1_atr_mult"] = max(3.0, min(7.0, p["t1_atr_mult"] * random.uniform(0.93, 1.07)))
            if "t2_atr_mult" in p:
                p["t2_atr_mult"] = max(7.0, min(12.0, p["t2_atr_mult"] * random.uniform(0.93, 1.07)))
            if "rsi_lo" in p:
                p["rsi_lo"] = max(35, min(50, p["rsi_lo"] + random.uniform(-1.2, 1.2)))
            if "rsi_hi" in p:
                p["rsi_hi"] = max(52, min(70, p["rsi_hi"] + random.uniform(-1.2, 1.2)))
            if "t1_frac" in p and random.random() < 0.4:
                p["t1_frac"] = max(0.05, min(0.5, p["t1_frac"] + random.uniform(-0.04, 0.04)))
            if "t2_frac_of_rest" in p and random.random() < 0.4:
                p["t2_frac_of_rest"] = max(0.0, min(0.7, p["t2_frac_of_rest"] + random.uniform(-0.08, 0.08)))
    if random.random() < rate:
        g["v130"]["t3_mult"] = max(1.2, min(2.5, g["v130"]["t3_mult"] + random.uniform(-0.06, 0.06)))
    return g

def crossover(g1,g2):
    g = copy.deepcopy(g1)
    if random.random()<0.5:
        g["pool_budgets"]=g2["pool_budgets"][:]
    if random.random()<0.5:
        g["pool1_params"]=copy.deepcopy(g2["pool1_params"])
    if random.random()<0.5:
        g["pool2_params"]=copy.deepcopy(g2["pool2_params"])
    if random.random()<0.5:
        g["pool3_params"]=copy.deepcopy(g2["pool3_params"])
    if random.random()<0.5:
        g["strategy2_params"]=copy.deepcopy(g2["strategy2_params"])
    g["strategy1_capital"]=(g1["strategy1_capital"]+g2["strategy1_capital"])/2
    g["strategy2_capital"]=400-g["strategy1_capital"]
    return g

def evaluate(genome):
    try:
        orig = {
            "budgets": TJB.POOL_BUDGETS[:],
            "s1": TJB.STRATEGY1_CAPITAL,
            "s2": TJB.STRATEGY2_CAPITAL,
            "p1": copy.deepcopy(TJB.POOL1_PARAMS),
            "p2": copy.deepcopy(TJB.POOL2_PARAMS),
            "p3": copy.deepcopy(TJB.POOL3_PARAMS),
            "ps2": copy.deepcopy(TJB.STRATEGY2_PARAMS),
            "total": TJB.TOTAL_CAPITAL
        }
        TJB.POOL_BUDGETS = genome["pool_budgets"]
        TJB.STRATEGY1_CAPITAL = genome["strategy1_capital"]
        TJB.STRATEGY2_CAPITAL = genome["strategy2_capital"]
        TJB.TOTAL_CAPITAL = 400.0
        TJB.POOL1_PARAMS = genome["pool1_params"]
        TJB.POOL2_PARAMS = genome["pool2_params"]
        TJB.POOL3_PARAMS = genome["pool3_params"]
        TJB.STRATEGY2_PARAMS = genome["strategy2_params"]
        
        res = TJB.run_dual_strategies(store, micro=False, gate5m=None)
        m = res['metrics']
        final_nav = m['final_nav']
        max_dd = m['max_dd']
        pf = m['pf']
        wr = m['win_rate']
        
        dd_pen = 1.0
        if max_dd > 23:
            dd_pen = max(0.5, 0.9 - (max_dd-23)*0.02)
        pf_bonus = 1.0 + max(0, pf-3.0)*0.1 if pf>3 else 1.0
        wr_bonus = 1.0 + max(0, wr-55)*0.005 if wr>55 else 1.0
        fitness = final_nav * dd_pen * pf_bonus * wr_bonus
        
        metrics = {"final_nav": final_nav, "max_dd": max_dd, "pf": pf, "win_rate": wr, "n_trades": m['n_trades'], "fitness": fitness}
        return metrics, res
    except Exception as e:
        return {"final_nav": 400, "max_dd": 100, "pf": 0, "win_rate": 0, "n_trades": 0, "fitness": 0}, None
    finally:
        TJB.POOL_BUDGETS = orig["budgets"]
        TJB.STRATEGY1_CAPITAL = orig["s1"]
        TJB.STRATEGY2_CAPITAL = orig["s2"]
        TJB.POOL1_PARAMS = orig["p1"]
        TJB.POOL2_PARAMS = orig["p2"]
        TJB.POOL3_PARAMS = orig["p3"]
        TJB.STRATEGY2_PARAMS = orig["ps2"]
        TJB.TOTAL_CAPITAL = orig["total"]

POP_SIZE = 15
GENERATIONS = 10000  # من 70020 إلى 80000 = 9980 جيل
MUTATION_RATE = 0.18
ELITE = 3

print(f"\n🧬 GA V130 Continuous: Pop {POP_SIZE} Target 80000 (from {start_gen})")

population = [create_genome(base_genome) for _ in range(POP_SIZE)]
population[0] = create_genome(base_genome)

# Load best
try:
    with open('/tmp/v130_ga_best.pkl','rb') as f:
        best_data = pickle.load(f)
    best_fitness = best_data['metrics']['fitness']
    best_genome = create_genome(best_data)
    best_metrics = best_data['metrics']
    print(f"Loaded best: {best_metrics['final_nav']:.2f}$")
except:
    best_fitness = 0
    best_genome = None
    best_metrics = None

history = []
try:
    with open('/tmp/v130_ga_history.pkl','rb') as f:
        history = pickle.load(f)
except:
    pass

start = time.time()

for gen in range(start_gen, 80000):
    gen_idx = gen - start_gen
    if gen_idx >= GENERATIONS:
        break
        
    gen_start = time.time()
    results = []
    for i, g in enumerate(population):
        metrics, res = evaluate(g)
        results.append((metrics["fitness"], metrics, g, res))
    
    results.sort(key=lambda x: x[0], reverse=True)
    cur_fit, cur_met, cur_gen, cur_res = results[0]
    
    if cur_fit > best_fitness:
        best_fitness = cur_fit
        best_genome = copy.deepcopy(cur_gen)
        best_metrics = cur_met
        save_data = {
            "generation": gen+1,
            "tag": f"GEN {gen+1} V130 (Profit {best_metrics['final_nav']:.2f}$ / DD {best_metrics['max_dd']:.1f}% / PF {best_metrics['pf']:.2f})",
            "strategy1_capital": best_genome["strategy1_capital"],
            "strategy2_capital": best_genome["strategy2_capital"],
            "pool_budgets": best_genome["pool_budgets"],
            "pool1_params": best_genome["pool1_params"],
            "pool2_params": best_genome["pool2_params"],
            "pool3_params": best_genome["pool3_params"],
            "strategy2_params": best_genome["strategy2_params"],
            "v130": best_genome["v130"],
            "metrics": best_metrics
        }
        with open(f'/tmp/gen{gen+1}_v130_best.pkl','wb') as f:
            pickle.dump(save_data,f)
        with open('/tmp/v130_ga_best.pkl','wb') as f:
            pickle.dump(save_data,f)
        with open('/home/user/clean_titan_bot/gen80000_v130_evolved.pkl','wb') as f:
            pickle.dump(save_data,f)
        with open('/home/user/TITAN_19_ONLY_FINAL/bot_cache/gen80000_v130_evolved.pkl','wb') as f:
            pickle.dump(save_data,f)
        print(f"  🏆 New Best Gen {gen+1}: {best_metrics['final_nav']:.2f}$ DD{best_metrics['max_dd']:.1f}% PF{best_metrics['pf']:.2f}")
    
    history.append((gen+1, cur_met['final_nav'], cur_met['max_dd'], cur_met['pf'], cur_met['win_rate']))
    
    elapsed = time.time()-gen_start
    total_elapsed = time.time()-start
    remaining = (80000 - gen - 1) * elapsed
    print(f"Gen {gen+1} | Best: {cur_met['final_nav']:.2f}$ fit {cur_fit:.1f} DD{cur_met['max_dd']:.1f}% PF{cur_met['pf']:.2f} WR{cur_met['win_rate']:.1f}% | Global: {best_metrics['final_nav']:.2f}$ | Time {elapsed:.1f}s Total {total_elapsed/3600:.1f}h Rem {remaining/3600:.1f}h")
    
    next_pop = []
    for i in range(ELITE):
        next_pop.append(copy.deepcopy(results[i][2]))
    while len(next_pop) < POP_SIZE:
        p1 = random.choice(results[:7])[2]
        p2 = random.choice(results[:7])[2]
        child = crossover(p1,p2)
        child = mutate(child, MUTATION_RATE)
        next_pop.append(child)
    population = next_pop
    
    if (gen+1) % 10 == 0:
        with open('/tmp/v130_ga_history.pkl','wb') as f:
            pickle.dump(history,f)

print(f"\n🏆 GA Completed to 80000 - Best: {best_metrics['final_nav']:.2f}$")
