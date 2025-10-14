# app.py — Golf Darts (Streamlit) with safe fallback player names
# - Works even when dgplayers.txt is missing or invalid
# - Keeps your “Load players → Start game → Leaderboard” flow
# - Mobile friendly

import os, io, json, time, random, sys, traceback
import pandas as pd
import streamlit as st

# ---------- Crash safety: show pre-render exceptions ----------
def _report_uncaught(exc_type, exc, tb):
    try:
        st.set_page_config(page_title="Golf Darts", page_icon="⛳", layout="wide")
        st.title("⛳ Golf Darts")
        st.error("💥 App crashed before rendering the UI.")
        st.code("".join(traceback.format_exception(exc_type, exc, tb)))
    except Exception:
        pass
sys.excepthook = _report_uncaught

# ---------- Compat ----------
def RERUN():
    if hasattr(st, "rerun"): st.rerun()
    elif hasattr(st, "experimental_rerun"): st.experimental_rerun()

# ---------- Config ----------
TXT_FILENAME = "dgplayers.txt"  # optional; we fall back if missing
NUM_ROUNDS = 4                  # keep as-is; adjust if you like
HOLES_PER_ROUND = 18
PAR_DISTRIBUTION = ['par4'] * 12 + ['par3'] * 3 + ['par5'] * 3
MAX_DARTS = 9
PAR_MAP = {'par3': 3, 'par4': 4, 'par5': 5}
PAR_TIME_FACTOR = {'par3': 0.8, 'par4': 1.0, 'par5': 1.2}

# ---------- Built-in SAFE fake names (no licensing issues) ----------
FAKE_BOT_NAMES = [
    "Alfie Johnson","Barry Latham","Cal Doyle","Darren Smales","Eddie Cooper",
    "Frankie Marshall","Gavin Pike","Harry Bolton","Ian Cutler","Jamie Rowntree",
    "Kyle Hargreaves","Lewis Danton","Mason Ridley","Nate Colburn","Owen Tranter",
    "Pete Holloway","Quinn Harker","Ricky Dawes","Sam Pritchard","Toby Wilcox",
    "Vince Archer","Will Keating","Xander Brooke","Yuri Koval","Zack Morton",
    "Shane O'Rourke","Paddy Molloy","Liam Burke","Connor Flynn","Declan Reddin",
    "Aiden McCaffrey","Sean Donnelly","Rory Hanlon","Brendan Kelleher","Noel Tiernan",
    "Gregor Van Drunen","Jan Kromhout","Sjoerd Verbeek","Hugo Schenk","Sven Arvidsson",
    "Karl Drexler","Lukas Steiner","Marek Novak","Tomasz Zielak","Niko Saarinen",
    "Matteo Ruggieri","Alvaro Ceballos","Diego Lamela","Rafael Domingues","Luis Arevalo",
    "Andy Buckfield","Colin Sparks","Mick Daniels","Nicky Pratt","Jason Craddock",
    "Dylan Cartwright","Stuart Kettering","Glen Everly","Martin Browning","Howard Clegg",
    "Ray Kendall","Billy Squires","Tony Mather","Steve Riddick","Terry McBain",
    "Gareth Plummer","Ben Jarrett","Callum Haines","Reece Mallory","Joel Partridge",
    "Ollie Bannister","Spencer Crowe","Morgan Tate","Felix Wainwright","Harvey North",
    "Miles Whitcombe","Ewan Carver","Kieron Ashdown","Leon Sayer","Rhys Penbury",
    "Jasper Longden","Trent Maybury","Wes Crampton","Dale Henshaw","Byron Loxley"
]
def default_bots_df(level:int=10) -> pd.DataFrame:
    return pd.DataFrame({"Name": FAKE_BOT_NAMES, "Level": [level]*len(FAKE_BOT_NAMES)})

# ---------- Helpers ----------
def here(*parts): return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)

def read_text_like(file_or_path):
    encs = ("utf-16", "utf-8-sig", "utf-8")
    if isinstance(file_or_path, str):
        last=None
        for e in encs:
            try:
                with open(file_or_path, "r", encoding=e) as f:
                    return [ln.strip().strip('"') for ln in f if ln.strip()]
            except Exception as ex: last=ex
        raise RuntimeError(f"Could not read {file_or_path}: {last}")
    else:
        raw=file_or_path.read()
        for e in encs:
            try:
                text=raw.decode(e)
                return [ln.strip().strip('"') for ln in text.splitlines() if ln.strip()]
            except Exception: pass
        raise RuntimeError("Could not decode uploaded file (utf-16/utf-8-sig/utf-8).")

def load_bots_from_txt(source) -> pd.DataFrame:
    lines = read_text_like(source)
    if lines and lines[0].lower().startswith("name"): lines = lines[1:]
    recs=[]
    for ln in lines:
        parts=[p.strip() for p in ln.split(",")]
        if len(parts)<2: continue
        name=",".join(parts[:-1]).strip()
        try: lvl=int(parts[-1])
        except: continue
        if name: recs.append((name,lvl))
    if not recs: raise ValueError("Parsed zero bots from the player file.")
    df=pd.DataFrame(recs, columns=["Name","Level"])
    df=df.sort_values(["Name","Level"], ascending=[True,False]).drop_duplicates("Name", keep="first").reset_index(drop=True)
    return df

def generate_finish(par_type:str)->int:
    if par_type=='par3': return random.randint(2,40)
    if par_type=='par4': return random.randint(41,80)
    if par_type=='par5': return random.randint(81,120)
    return random.randint(2,120)

def simulate_bot_score(level:int, par_type:str)->int:
    par=PAR_MAP[par_type]; chance=level/20.0
    if par_type=='par3' and random.random()<0.01*chance: return 1
    if par_type in('par4','par5') and random.random()<0.02*chance: return max(1, par-2)
    if random.random()<chance: return par
    if random.random()<chance*0.5: return par+1
    return min(par+random.randint(2,5), MAX_DARTS)

def hole_par_type(round_pars, hole_index:int)->str: return round_pars[hole_index%18]
def base_time_for(par_type:str, pace_seconds:float)->float: return float(pace_seconds)*PAR_TIME_FACTOR.get(par_type,1.0)

# ---------- Leaderboard ----------
def leaderboard_dataframe(players):
    rows=[{
        "Name":p["Name"],
        "Total Darts":sum(p["Scores"]),
        "Score vs Par":sum(p["ParScores"]),
        "Thru":p["hole_in_round"],
        "Round":p["round_num"],
    } for p in players]
    df=pd.DataFrame(rows)
    df=df.sort_values(by=["Score vs Par","Thru","Total Darts","Name"],
                      ascending=[True,False,True,True]).reset_index(drop=True)
    df.insert(0,"Rank",range(1,len(df)+1))
    return df

# ---------- Course / Pairings ----------
def build_pairings(players, group_size:int):
    idxs=list(range(len(players))); random.shuffle(idxs)
    return [idxs[i:i+group_size] for i in range(0,len(idxs),group_size)]

def user_in_pairing(state, pairing):
    ui = state.get("user_index")
    if ui is not None:
        return ui in pairing
    return any(state["players"][i]["Name"] == state["user_name"] for i in pairing)

def all_finished_round(players): return all(p["hole_in_round"]>=HOLES_PER_ROUND for p in players)

# ---------- Round runtime ----------
def init_round_runtime(state):
    state["round_pars"]=PAR_DISTRIBUTION[:]; random.shuffle(state["round_pars"])
    state["holes_occupancy"]=[None]*HOLES_PER_ROUND
    state["pairings"]=build_pairings(state["players"], state["pairing_size"])
    state["pairing_states"]=[]
    t0=state["sim_time"]
    for i in range(len(state["pairings"])):
        state["pairing_states"].append({
            "status":"pre_tee","next_hole":0,"timer":0.0,
            "queued_since":None,"current_par_type":None,"current_par":None,
            "current_finish":None,"tee_time":t0 + i*state["tee_interval"],
            "await_meta": None,
        })

def try_queue_pairing(state,i):
    ps=state["pairing_states"][i]
    if ps["status"]=="pre_tee" and state["sim_time"]>=ps["tee_time"]:
        ps["status"]="queued"; ps["queued_since"]=state["sim_time"]

def _apply_scores_for_pairing_on_hole(state, pairing_index, par_type, par, user_score_if_needed=None):
    pairing=state["pairings"][pairing_index]
    for i in pairing:
        p=state["players"][i]
        score = int(user_score_if_needed) if (p["Name"]==state["user_name"] and not state["auto_mode"] and user_score_if_needed is not None) \
                else simulate_bot_score(p["Level"], par_type)
        p["Scores"].append(score); p["ParScores"].append(score-par); p["hole_in_round"]+=1

def complete_current_hole(state, pairing_index, user_score_if_needed=None):
    ps=state["pairing_states"][pairing_index]
    hole=ps["next_hole"]
    par_type=ps["current_par_type"]; par=ps["current_par"]; finish=ps["current_finish"]
    pairing=state["pairings"][pairing_index]
    state["holes_occupancy"][hole]=None
    if not state["auto_mode"] and user_in_pairing(state, pairing) and user_score_if_needed is None:
        ps["status"]="await_user"; ps["timer"]=0.0
        ps["await_meta"]={"hole":hole,"par_type":par_type,"par":par,"finish":finish}
        state["pending_turn"]={
            "pairing_index":pairing_index,"hole_num_in_round":hole+1,
            "par_type":par_type,"par":par,"finish":finish,
        }
        return "await_user"
    _apply_scores_for_pairing_on_hole(state, pairing_index, par_type, par, user_score_if_needed)
    state["last_action"]={
        "pairing_index":pairing_index,"hole_in_round_after":hole+1,
        "par_type":par_type,"par":par,"finish":finish,
        "players":[state["players"][i]["Name"] for i in pairing],
    }
    state["pending_turn"]=None
    state["board_df"]=leaderboard_dataframe(state["players"])
    ps["next_hole"]+=1
    if ps["next_hole"]>=HOLES_PER_ROUND: ps["status"]="finished"; ps["timer"]=float("inf")
    else:
        ps["status"]="queued"; ps["queued_since"]=state["sim_time"]; ps["timer"]=0.0
        nxt=hole_par_type(state["round_pars"], ps["next_hole"])
        ps["current_par_type"]=nxt; ps["current_par"]=PAR_MAP[nxt]; ps["current_finish"]=generate_finish(nxt)
    return "ok"

def submit_user_score_and_queue_next(state, pairing_index, user_score:int):
    ps=state["pairing_states"][pairing_index]; meta=ps.get("await_meta")
    if not meta: return
    _apply_scores_for_pairing_on_hole(state, pairing_index, meta["par_type"], meta["par"], user_score)
    state["last_action"]={
        "pairing_index":pairing_index,"hole_in_round_after": meta["hole"]+1,
        "par_type": meta["par_type"], "par": meta["par"], "finish": meta["finish"],
        "players":[state["players"][i]["Name"] for i in state["pairings"][pairing_index]],
    }
    state["board_df"]=leaderboard_dataframe(state["players"])
    state["pending_turn"]=None; ps["await_meta"]=None
    ps["next_hole"] += 1
    if ps["next_hole"]>=HOLES_PER_ROUND: ps["status"]="finished"; ps["timer"]=float("inf")
    else:
        ps["status"]="queued"; ps["queued_since"]=state["sim_time"]; ps["timer"]=0.0
        nxt=hole_par_type(state["round_pars"], ps["next_hole"])
        ps["current_par_type"]=nxt; ps["current_par"]=PAR_MAP[nxt]; ps["current_finish"]=generate_finish(nxt)

def assign_holes(state):
    want={}
    for i,ps in enumerate(state["pairing_states"]):
        if ps["status"]=="queued" and ps["next_hole"]<HOLES_PER_ROUND:
            want.setdefault(ps["next_hole"], []).append((ps["queued_since"], i))
    for hole in range(HOLES_PER_ROUND):
        if state["holes_occupancy"][hole] is not None: continue
        if hole not in want or not want[hole]: continue
        want[hole].sort(key=lambda x:x[0]); _, idx=want[hole].pop(0)
        ps=state["pairing_states"][idx]; par_type=hole_par_type(state["round_pars"], hole)
        ps["status"]="on_hole"; ps["timer"]=base_time_for(par_type, state["pace_seconds"])
        ps["queued_since"]=None; state["holes_occupancy"][hole]=idx
        ps["current_par_type"]=par_type; ps["current_par"]=PAR_MAP[par_type]; ps["current_finish"]=generate_finish(par_type)

def end_round_if_ready(state):
    if not all_finished_round(state["players"]): return False
    # Optional cut after round 2 (keep top 50)
    if state["round_num"] == 2:
        top = set(state["board_df"].head(50)["Name"])
        state["players"] = [p for p in state["players"] if p["Name"] in top]
        state["board_df"] = leaderboard_dataframe(state["players"])
        if state["user_name"] not in top:
            state["eliminated"] = True
    state["round_num"] += 1
    if state["round_num"] > NUM_ROUNDS: return True
    for p in state["players"]:
        p["hole_in_round"] = 0
        p["round_num"] = state["round_num"]
    state["prev_auto_running"] = bool(state.get("auto_running", False))
    state["just_started_round"] = True
    state["round_started_at_sim"] = state["sim_time"]
    return True

def tick_clock(state, dt):
    if dt<=0: return
    state["sim_time"] += dt
    for i in range(len(state["pairings"])): try_queue_pairing(state,i)
    for hole, idx in enumerate(state["holes_occupancy"]):
        if idx is None: continue
        ps=state["pairing_states"][idx]
        if ps["status"]=="on_hole" and ps["timer"]!=float("inf"): ps["timer"]-=dt
    MAX_COMPLETIONS=24; ready=[]
    for hole, idx in enumerate(state["holes_occupancy"]):
        if idx is None: continue
        ps=state["pairing_states"][idx]
        if ps["status"]=="on_hole" and ps["timer"]<=0: ready.append((ps["timer"], hole, idx))
    ready.sort(key=lambda x:x[0])
    for _, hole, idx in ready[:MAX_COMPLETIONS]:
        complete_current_hole(state, idx, None)
    assign_holes(state)
    finished = end_round_if_ready(state)
    if finished and state["round_num"] <= NUM_ROUNDS:
        init_round_runtime(state)
        state["last_wall"] = time.time()

# ---------- Recovery helper ----------
def recover_pending_turn_from_await():
    s=st.session_state
    if not s.get("pairing_states"): return False
    for idx, ps in enumerate(s.pairing_states):
        if ps.get("status")=="await_user":
            pairing=s.pairings[idx]
            if user_in_pairing(s, pairing):
                meta=ps.get("await_meta")
                if not meta: continue
                s.pending_turn={"pairing_index":idx,"hole_num_in_round":meta["hole"]+1,
                                "par_type":meta["par_type"],"par":meta["par"],"finish":meta["finish"]}
                return True
    return False

# ---------- Save / Load ----------
def export_state_json():
    s=st.session_state
    data={"round_num":s.round_num,"players":s.players,"user_name":s.user_name,
          "user_level":int(s.user_level),"auto_mode":bool(s.auto_mode),
          "pace_seconds":s.pace_seconds,"tee_interval":s.tee_interval,
          "pairing_size":s.pairing_size,"pairings":s.pairings,
          "pairing_states":s.pairing_states,"round_pars":s.round_pars,
          "holes_occupancy":s.holes_occupancy,"board":s.board_df.to_dict(orient="list"),
          "eliminated":s.eliminated,"auto_running":s.auto_running,
          "last_wall":s.last_wall,"pending_turn":s.pending_turn,
          "last_action":s.last_action,"sim_time":s.sim_time,"user_index": s.user_index,
          "resume_auto_after_turn": s.resume_auto_after_turn,
          "prev_auto_running": s.prev_auto_running,
          "just_started_round": s.just_started_round,
          "round_started_at_sim": s.round_started_at_sim}
    return json.dumps(data, indent=2)

def import_state_json(txt:str):
    data=json.loads(txt); s=st.session_state
    s.round_num=data["round_num"]; s.players=data["players"]; s.user_name=data["user_name"]
    s.user_level=int(data.get("user_level",20)); s.auto_mode=bool(data.get("auto_mode",True))
    s.pace_seconds=float(data.get("pace_seconds",3.0)); s.tee_interval=float(data.get("tee_interval",5.0))
    s.pairing_size=int(data.get("pairing_size",3)); s.pairings=data.get("pairings",[])
    s.pairing_states=data.get("pairing_states",None); s.round_pars=data.get("round_pars",PAR_DISTRIBUTION[:])
    s.holes_occupancy=data.get("holes_occupancy",[None]*HOLES_PER_ROUND)
    s.board_df=pd.DataFrame(data.get("board",{}))
    if s.board_df.empty and s.players: s.board_df=leaderboard_dataframe(s.players)
    s.eliminated=bool(data.get("eliminated",False)); s.auto_running=bool(data.get("auto_running",False))
    s.last_wall=float(data.get("last_wall",time.time())); s.pending_turn=data.get("pending_turn",None)
    s.last_action=data.get("last_action",None); s.sim_time=float(data.get("sim_time",0.0))
    s.user_index=data.get("user_index", None); s.resume_auto_after_turn=data.get("resume_auto_after_turn", False)
    s.prev_auto_running = data.get("prev_auto_running", False)
    s.just_started_round = data.get("just_started_round", False)
    s.round_started_at_sim = float(data.get("round_started_at_sim", s.sim_time))
    if s.user_index is None: s.user_index=next((i for i,p in enumerate(s.players) if p["Name"]==s.user_name), None)
    s.start_ready=True

# ---------- App State ----------
def init_state():
    s=st.session_state
    if s.get("initialized"): return
    s.initialized=True
    s.players=[]; s.user_name="You"; s.user_level=20; s.auto_mode=True
    s.user_index=None; s.resume_auto_after_turn=False
    s.round_num=1; s.round_pars=PAR_DISTRIBUTION[:]
    s.board_df=pd.DataFrame(columns=["Rank","Name","Total Darts","Score vs Par","Thru","Round"])
    s.eliminated=False; s.player_file_loaded=False; s.bots_df=None; s.start_ready=False
    s.pairing_size=3; s.pairings=[]; s.pairing_states=None; s.holes_occupancy=[None]*HOLES_PER_ROUND
    s.pace_seconds=3.0; s.tee_interval=5.0
    s.auto_running=False; s.last_wall=time.time()
    s.pending_turn=None; s.last_action=None; s.sim_time=0.0
    s.prev_auto_running=False; s.just_started_round=False; s.round_started_at_sim=0.0

def start_new_game(bots_df:pd.DataFrame):
    s=st.session_state
    s.round_num=1
    s.players=[{"Name":(s.user_name or "You").strip(),"Level":int(s.user_level),
                "Scores":[], "ParScores":[], "hole_in_round":0, "round_num":s.round_num}]
    s.user_index = 0
    for _,row in bots_df.iterrows():
        s.players.append({"Name":str(row["Name"]),"Level":int(row["Level"]),
                          "Scores":[], "ParScores":[], "hole_in_round":0, "round_num":s.round_num})
    s.board_df=leaderboard_dataframe(s.players)
    s.pending_turn=None; s.eliminated=False; s.start_ready=True
    s.sim_time=0.0; init_round_runtime(s); s.last_wall=time.time(); s.last_action=None
    s.prev_auto_running=False; s.just_started_round=False; s.round_started_at_sim=s.sim_time

# ---------- UI ----------
st.set_page_config(page_title="Golf Darts", page_icon="⛳", layout="wide")
init_state()
if "last_action" not in st.session_state: st.session_state.last_action=None

# Sidebar
st.sidebar.header("⛳ Setup")
local_path=here(TXT_FILENAME); bots_source=local_path if os.path.exists(local_path) else None
if not bots_source:
    upl=st.sidebar.file_uploader("Upload dgplayers.txt (optional)", type=["txt"])
    if upl is not None: bots_source=io.BytesIO(upl.getvalue())

st.sidebar.text_input("Your name", value=st.session_state.user_name, key="user_name")
st.sidebar.write("Your level"); st.sidebar.slider("", 1, 20, value=st.session_state.user_level, key="user_level")
st.sidebar.checkbox("Auto-play my shots", value=st.session_state.auto_mode, key="auto_mode")
st.sidebar.slider("Pairing size", 2, 4, value=st.session_state.pairing_size, key="pairing_size")
st.sidebar.slider("Pace — seconds per hole (baseline)", 1.0, 15.0, value=st.session_state.pace_seconds, step=0.5, key="pace_seconds")
st.sidebar.slider("Tee interval (seconds)", 0.0, 20.0, value=st.session_state.tee_interval, step=0.5, key="tee_interval")

# Pause auto on your turn
st.sidebar.checkbox("Pause auto when it's my turn", value=True, key="pause_on_turn")

# ---- Load players with SAFE fallback ----
c1,c2=st.sidebar.columns(2)
with c1:
    if st.button("Load players"):
        try:
            if bots_source:
                st.session_state.bots_df=load_bots_from_txt(bots_source)
                st.session_state.player_file_loaded=True
                st.success(f"Loaded {len(st.session_state.bots_df)} players from file.")
            else:
                raise RuntimeError("No file; will use built-ins.")
        except Exception:
            # fallback to safe fake names at chosen level (default 10)
            lvl = int(st.session_state.get("user_level", 10))
            st.session_state.bots_df = default_bots_df(level=max(1, min(20, lvl)))
            st.session_state.player_file_loaded=True
            st.info(f"No valid dgplayers.txt — loaded {len(st.session_state.bots_df)} built-in bots.")
with c2:
    if st.button("Start game"):
        if not st.session_state.player_file_loaded:
            # if user forgot to press "Load players", silently provide defaults
            lvl = int(st.session_state.get("user_level", 10))
            st.session_state.bots_df = default_bots_df(level=max(1, min(20, lvl)))
            st.session_state.player_file_loaded=True
            st.info(f"Auto-loaded {len(st.session_state.bots_df)} built-in bots.")
        start_new_game(st.session_state.bots_df)

st.sidebar.subheader("💾 Save / Load")
save_json=export_state_json()
st.sidebar.download_button("Download save (JSON)", data=save_json, file_name="golf_darts_save.json", mime="application/json")
save_up=st.sidebar.file_uploader("Load save (JSON)", type=["json"], key="save_loader")
if save_up is not None:
    try: import_state_json(save_up.getvalue().decode("utf-8")); st.sidebar.success("Save loaded.")
    except Exception as e: st.sidebar.error(f"Load failed: {e}")

# Main
st.title("⛳ Golf Darts — Course Mode")
st.caption("Manual mode never blocks a hole: your group waits **between holes** for your score. "
           "Free holes are filled immediately. Leaderboard sorts by Score vs Par → Thru → Total Darts.")

top=st.columns(6)
top[0].metric("Round", st.session_state.round_num)
top[1].metric("Players", len(st.session_state.players))
top[2].metric("Pairings", len(st.session_state.pairings) if st.session_state.pairings else 0)
top[3].metric("Auto", "On" if st.session_state.auto_mode else "Off")
top[4].metric("Pace base (s)", int(st.session_state.pace_seconds))
top[5].metric("Tee gap (s)", int(st.session_state.tee_interval))
st.divider()

if not st.session_state.start_ready:
    st.info("Load players and press **Start game**.")
    st.stop()

left,right=st.columns([1.25,1])

with left:
    st.subheader("Controller")

    if st.session_state.get("just_started_round"):
        st.success(f"⛳ Round {st.session_state.round_num} is ready.")
        if st.session_state.prev_auto_running and st.session_state.get("pending_turn") is None:
            st.session_state.auto_running = True
        st.session_state.just_started_round = False

    if st.session_state.get("pending_turn") is None:
        if recover_pending_turn_from_await():
            st.info("It's your turn — restored the input card.")

    if st.session_state.get("pending_turn") is not None and st.session_state.get("pause_on_turn", True):
        if st.session_state.get("auto_running", False):
            st.session_state.auto_running = False
            st.session_state.resume_auto_after_turn = True
            st.info("⏸️ Auto paused while you enter your score.")

    needs_kick = False
    if st.session_state.pairing_states:
        statuses = {ps["status"] for ps in st.session_state.pairing_states}
        if statuses == {"pre_tee"}:
            needs_kick = True
    if needs_kick:
        st.warning("Tee sheet is ready. Kick off Round start?")
        if st.button("🏁 Kick tee sheet"):
            tick_clock(st.session_state, 0.1)
            st.session_state.last_wall = time.time()
            RERUN()

    if not st.session_state.get("auto_running", False) and st.session_state.get("pending_turn") is None:
        st.warning("Auto is paused.")
        if st.button("▶ Resume auto"):
            st.session_state.auto_running = True
            st.session_state.resume_auto_after_turn = False
            RERUN()

    ui = st.session_state.get("user_index")
    if ui is not None and st.session_state.pairings:
        your_pair_idx = next((pi for pi, grp in enumerate(st.session_state.pairings) if ui in grp), None)
        if your_pair_idx is not None:
            ps = st.session_state.pairing_states[your_pair_idx]
            nh = ps["next_hole"] + 1 if ps["next_hole"] < HOLES_PER_ROUND else "—"
            st.info(f"Your pairing: #{your_pair_idx+1} • Status: {ps['status']} • Next hole: {nh}")
        else:
            st.warning("Your pairing not found in current draw.")
    else:
        st.warning("Your pairing isn’t identified yet — start a new game or check your name.")

    if st.session_state.pending_turn is not None:
        need=st.session_state.pending_turn
        with st.form("your_turn"):
            st.markdown(f"### ⛳ Your turn — Hole {need['hole_num_in_round']} • {need['par_type'].upper()} (Par {need['par']})")
            st.caption(f"Finish distance: {need['finish']}")
            your_score=st.number_input("Enter your darts", 1, MAX_DARTS, value=need["par"])
            if st.form_submit_button("Submit"):
                submit_user_score_and_queue_next(st.session_state, need["pairing_index"], int(your_score))
                st.session_state.pending_turn=None
                if st.session_state.get("resume_auto_after_turn"):
                    st.session_state.auto_running = True
                    st.session_state.resume_auto_after_turn = False
                st.session_state.last_wall=time.time()
                RERUN()

    step_cols=st.columns(3)
    if step_cols[0].button("▶ Step 1s"):  tick_clock(st.session_state,1.0);  st.session_state.last_wall=time.time(); RERUN()
    if step_cols[1].button("⏩ Step 5s"):  tick_clock(st.session_state,5.0);  st.session_state.last_wall=time.time(); RERUN()
    if step_cols[2].button("⏭ Step 30s"): tick_clock(st.session_state,30.0); st.session_state.last_wall=time.time(); RERUN()

    ac1,ac2=st.columns(2)
    if ac1.button("🚀 Start Auto"): st.session_state.auto_running=True; st.session_state.last_wall=time.time(); RERUN()
    if ac2.button("🛑 Stop Auto"):  st.session_state.auto_running=False; RERUN()

    la=st.session_state.get("last_action")
    if la:
        st.info(f"Last: pairing {la['pairing_index']+1} finished hole {la['hole_in_round_after']} "
                f"({la['par_type'].upper()} Par {la['par']}) • {', '.join(la['players'])}")

    if st.session_state.eliminated: st.error("You were eliminated at the cut after Round 2.")
    elif st.session_state.round_num>NUM_ROUNDS: st.success("🏁 Championship finished!")

with right:
    st.subheader("Leaderboard")
    st.dataframe(st.session_state.board_df, use_container_width=True, hide_index=True)

    st.subheader("Course (holes & pairings)")
    rows=[]
    for h in range(HOLES_PER_ROUND):
        occ=st.session_state.holes_occupancy[h]
        if occ is None:
            rows.append({"Hole":h+1,"Pairing":"—","Players":"—","Time left":"—"})
        else:
            names=", ".join(st.session_state.players[i]["Name"] for i in st.session_state.pairings[occ])
            ps=st.session_state.pairing_states[occ]
            t="—" if ps["status"]!="on_hole" else f"{max(0.0, ps['timer']):.1f}s"
            rows.append({"Hole":h+1,"Pairing":occ+1,"Players":names,"Time left":t})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Pairings (status)")
    data=[]
    for idx, pr in enumerate(st.session_state.pairings, start=1):
        names=", ".join(st.session_state.players[i]["Name"] for i in pr)
        ps=st.session_state.pairing_states[idx-1]
        data.append({"Pairing":idx,"Status":ps["status"],
                     "Next hole": ps["next_hole"]+1 if ps["next_hole"]<HOLES_PER_ROUND else "—",
                     "Queued since (sim)": "—" if not ps.get("queued_since") else f"{ps['queued_since']:.1f}s",
                     "Tee (sim)": f"{ps['tee_time']:.1f}s", "Players":names})
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

st.caption("Free holes fill immediately. If Manual, your group waits between holes for your input — never blocking others.")

# ---------- Auto clock ----------
now_wall=time.time()
if (
    st.session_state.auto_running
    and st.session_state.pending_turn is None
    and not st.session_state.eliminated
    and st.session_state.round_num <= NUM_ROUNDS
):
    dt=max(0.0, min(1.0, now_wall - st.session_state.last_wall))
    if dt>0:
        tick_clock(st.session_state, dt)
        st.session_state.last_wall=now_wall
    time.sleep(0.15)
    RERUN()

        st.session_state.last_wall=now_wall
    time.sleep(0.15)
    RERUN()
