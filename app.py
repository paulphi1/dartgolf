# app.py — Golf Darts (Streamlit) with safe fallback player names
# - No external files required (no dgplayers.txt)
# - "Load players" -> "Start game" flow
# - 18-hole course, leaderboard, session Top 10
# - Mobile-friendly

import os
import sys
import time
import math
import random
import datetime as dt
import pandas as pd
import streamlit as st

# ---------------- Utils: safe crash surface (never blank page) ----------------
def _report_uncaught(exc_type, exc, tb):
    try:
        st.set_page_config(page_title="Golf Darts", page_icon="🎯", layout="wide")
        st.title("🎯 Golf Darts")
        st.error("App crashed while rendering the UI.")
        import traceback
        st.code("".join(traceback.format_exception(exc_type, exc, tb)))
    except Exception:
        pass

# Make sure Streamlit shows any unexpected exception instead of a blank screen.
sys.excepthook = _report_uncaught

# ---------------- Page config ----------------
st.set_page_config(page_title="Golf Darts", page_icon="🎯", layout="wide")

# ---------------- Constants ----------------
NUM_HOLES = 18
# A simple course: mostly par 3s with a few par 4s and one par 5
PARS = [3, 3, 3, 4, 3, 3, 4, 3, 4, 3, 3, 3, 4, 3, 3, 4, 3, 5]
assert len(PARS) == NUM_HOLES

# Built-in fake players list (feel free to change/add)
FAKE_PLAYERS = [
    "Alex", "Bailey", "Charlie", "Drew", "Ellis", "Finley", "Gray", "Harper", "Indy",
    "Jesse", "Kai", "Logan", "Morgan", "Noel", "Oakley", "Parker", "Quinn", "Riley",
    "Sage", "Tate", "Uma", "Val", "Wren", "Xan", "Yael", "Zion",
    "Avery", "Blake", "Casey", "Devon", "Elliot", "Frankie", "Georgie", "Hayden",
    "Jamie", "Kendall", "Lennon", "Marlowe", "Nico", "Ollie", "Peyton", "Reese",
    "Skyler", "Taylor", "Tyler", "Remy", "Rowan", "Shay", "Sid", "Sunny", "Skye",
]

# ---------------- Simple “skill” model ----------------
def strokes_for_hole(skill: int, par: int) -> int:
    """
    Simulate number of darts (“strokes”) for one hole.
    Lower skill value => better player.
    We bias around par with some random noise.
    """
    # Base mean around par with small bias from skill
    # skill is 1..20 (1 = best). Higher skill -> more likely to be over par.
    bias = (skill - 10) / 10.0  # around -0.9 .. +1.0
    mean = par + max(0.0, bias)
    # Clamp to at least 1 and reasonable max
    out = max(1, int(round(random.gauss(mean, 0.8))))
    # Cap ridiculous numbers
    return min(out, par + 5)

# ---------------- Session state init ----------------
def init_state():
    ss = st.session_state
    if "players" not in ss:
        ss.players = []               # list[str]
    if "pairing_size" not in ss:
        ss.pairing_size = 3
    if "started" not in ss:
        ss.started = False
    if "hole" not in ss:
        ss.hole = 0                   # 0..NUM_HOLES-1
    if "scores" not in ss:
        ss.scores = {}                # dict[player] -> list of strokes per hole
    if "skill_map" not in ss:
        ss.skill_map = {}             # dict[player] -> skill (1..20)
    if "autoplay" not in ss:
        ss.autoplay = True
    if "last_wake" not in ss:
        ss.last_wake = dt.datetime.utcnow()
    if "top10" not in ss:
        ss.top10 = pd.DataFrame(columns=["Player", "Score", "Vs Par"])
    if "human_name" not in ss:
        ss.human_name = "You"
    if "human_skill" not in ss:
        ss.human_skill = 12

init_state()

# ---------------- Sidebar controls ----------------
with st.sidebar:
    st.header("Your name")
    st.session_state.human_name = st.text_input(" ", value=st.session_state.human_name, label_visibility="collapsed")
    st.write("Your level")
    st.session_state.human_skill = int(st.slider(" ", min_value=1, max_value=20, value=st.session_state.human_skill, label_visibility="collapsed"))
    st.markdown("---")

    st.checkbox("Auto-play my shots", value=True, key="autoplay")
    st.slider("Pairing size", min_value=2, max_value=4, value=st.session_state.pairing_size, key="pairing_size")

    st.slider("Pace — seconds per hole (baseline)", min_value=1.0, max_value=10.0, value=3.0, step=0.5, key="pace_base")
    st.slider("Tee interval (seconds)", min_value=2.0, max_value=15.0, value=5.0, step=0.5, key="tee_gap")

    st.checkbox("Pause auto when it's my turn", value=True, key="pause_on_turn")

    colL, colR = st.columns(2)
    with colL:
        if st.button("Load players"):
            # Ensure human is always in the list
            names = [n for n in FAKE_PLAYERS if n.lower() != st.session_state.human_name.lower()]
            random.shuffle(names)
            # Pick between 8 and 20 additional players
            extra = names[:random.randint(8, 20)]
            st.session_state.players = [st.session_state.human_name] + extra

            # Assign a skill (1..20) — human uses the slider
            st.session_state.skill_map = {p: random.randint(8, 16) for p in st.session_state.players}
            st.session_state.skill_map[st.session_state.human_name] = st.session_state.human_skill
            st.success(f"Loaded {len(st.session_state.players)} players.")
    with colR:
        if st.button("Start game"):
            if not st.session_state.players:
                st.warning("Load players first.")
            else:
                # Reset game state
                st.session_state.started = True
                st.session_state.hole = 0
                st.session_state.scores = {p: [] for p in st.session_state.players}
                st.session_state.last_wake = dt.datetime.utcnow()
                st.rerun()

    st.markdown("### Save / Load")
    # For now we keep only session-lifetime data. (You can add JSON export if you want.)

# ---------------- Pairings helper ----------------
def make_pairings(players, k):
    """Split list into chunks of size k."""
    out = []
    cur = []
    for p in players:
        cur.append(p)
        if len(cur) == k:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out

# ---------------- Compute leaderboard ----------------
def leaderboard_df(scores: dict) -> pd.DataFrame:
    data = []
    for p, arr in scores.items():
        total = sum(arr)
        holes_played = len(arr)
        par_sum = sum(PARS[:holes_played])
        vspar = total - par_sum
        data.append((p, holes_played, total, vspar))
    df = pd.DataFrame(data, columns=["Player", "Holes", "Score", "Vs Par"])
    df = df.sort_values(["Vs Par", "Score", "Player"], ascending=[True, True, True]).reset_index(drop=True)
    return df

# ---------------- Play one hole (simulation) ----------------
def play_hole():
    ss = st.session_state
    hole_idx = ss.hole
    par = PARS[hole_idx]

    # Simulate each player's strokes for the hole
    for p in ss.players:
        skill = ss.skill_map.get(p, 12)
        strokes = strokes_for_hole(skill, par)
        ss.scores[p].append(strokes)

    ss.hole += 1
    ss.last_wake = dt.datetime.utcnow()

# ---------------- Finalize / store session Top-10 ----------------
def maybe_finish_and_store():
    ss = st.session_state
    if ss.hole >= NUM_HOLES:
        df = leaderboard_df(ss.scores)
        if not df.empty:
            final_rows = df[["Player", "Score", "Vs Par"]]
            # Keep a running Top 10 for this session
            combined = pd.concat([ss.top10, final_rows], ignore_index=True)
            combined = combined.sort_values(["Vs Par", "Score"], ascending=[True, True]).drop_duplicates(subset=["Player"], keep="first")
            ss.top10 = combined.head(10)

# ---------------- Main layout ----------------
st.title("⛳ Golf Darts — Course Mode (one pairing per hole)")
st.caption("Manual mode never blocks a hole: your group waits between holes for your score. "
           "Free holes are filled immediately. Leaderboard: Score vs Par → Thru → Total Darts.")

# Header metrics
colA, colB, colC, colD, colE, colF = st.columns(6)
with colA:
    st.metric("Round", st.session_state.hole + 1 if st.session_state.started else 1)
with colB:
    st.metric("Players", len(st.session_state.players))
with colC:
    st.metric("Pairings", len(make_pairings(st.session_state.players, st.session_state.pairing_size)) if st.session_state.players else 0)
with colD:
    st.metric("Auto", "On" if st.session_state.autoplay else "Off")
with colE:
    st.metric("Pace base (s)", int(st.session_state.pace_base))
with colF:
    st.metric("Tee gap (s)", int(st.session_state.tee_gap))

# Info / actions
if not st.session_state.players:
    st.info("Load players and press **Start game**.")
elif not st.session_state.started:
    st.info("Press **Start game** when you’re ready.")
else:
    # Game in progress or finished
    if st.session_state.hole < NUM_HOLES:
        hole_idx = st.session_state.hole
        st.subheader(f"Hole {hole_idx+1} — Par {PARS[hole_idx]}")

        # Live leaderboard
        lb = leaderboard_df(st.session_state.scores)
        if not lb.empty:
            st.dataframe(lb, use_container_width=True, height=360)

        # Controls to play this hole
        play_cols = st.columns([1,1,2,2,2])
        with play_cols[0]:
            if st.button("Play hole", type="primary"):
                play_hole()
                st.rerun()
        with play_cols[1]:
            if st.button("Fast forward ⏩"):
                # play the rest of the round quickly
                while st.session_state.hole < NUM_HOLES:
                    play_hole()
                maybe_finish_and_store()
                st.rerun()

        # (Optional) wake/sleep info
        st.caption("Tip: If the app sleeps, it may briefly show a ‘waking up’ message. That’s normal.")

    else:
        st.success("Round complete! 🎉")
        final = leaderboard_df(st.session_state.scores)
        st.dataframe(final, use_container_width=True, height=420)
        maybe_finish_and_store()

# Session Top 10
st.markdown("### 🌟 Top 10 (this session)")
if st.session_state.top10.empty:
    st.caption("No finished games yet — complete a round to record results.")
else:
    st.dataframe(st.session_state.top10, use_container_width=True, height=300)

st.caption("Made by @pauldartbrain • questforqschool.com")

