"""
Account Intelligence: ask questions about accounts, physicians, and programs.

Run:  streamlit run app.py
"""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

import agent
from semantic_layer import DEFAULT_DB_PATH, SemanticLayer, User

st.set_page_config(page_title="Account Intelligence", page_icon="🫀", layout="centered")

st.markdown(
    """
    <style>
      .block-container { max-width: 780px; padding-top: 2.2rem; }
      h1 { font-weight: 650; letter-spacing: -0.01em; margin-bottom: 0.1rem; }
      .lede { color: #4A5A70; font-size: 1.02rem; margin-bottom: 1.4rem; max-width: 62ch; }
      .scope { border-left: 3px solid #B3122E; padding: 0.35rem 0 0.35rem 0.8rem;
               color: #16233A; margin-bottom: 1.2rem; font-size: 0.95rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

SUGGESTED = [
    "Which physicians at Riverbend have gone quiet since the Plaque dinner program?",
    "Which accounts in my territory have the lowest estimated utilization?",
    "How has Plaque's share of cases trended by month this year?",
    "Who were the top 5 ordering physicians last quarter?",
    "Which accounts need review, and which are just data gaps?",
    "Show me the patient names for Riverbend's cases last month.",
]


@st.cache_resource
def load_layer() -> SemanticLayer:
    return SemanticLayer()


def reset_chat() -> None:
    st.session_state.messages = []


if not os.path.exists(DEFAULT_DB_PATH):
    st.error("No data yet. In a terminal, run `python3 generate_data.py`, then refresh this page.")
    st.stop()

layer = load_layer()
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------- sidebar: who is asking, and how ----------
with st.sidebar:
    st.subheader("Signed in as")
    people = {"Regional VP (all territories)": User("Regional VP")}
    for territory, tam in layer.territories():
        people[f"{tam}, TAM {territory}"] = User(tam, territory)
    who = st.selectbox("Signed in as", list(people), label_visibility="collapsed", on_change=reset_chat)
    user = people[who]

    replay_mode = st.toggle("Use saved answers", value=False,
                            help="Answers questions from cache/answers.json instead of calling the API. "
                                 "Every live answer is saved there automatically.")

    st.subheader("Try asking")
    clicked = None
    for i, q in enumerate(SUGGESTED):
        if st.button(q, key=f"suggest-{i}", width="stretch"):
            clicked = q

    st.caption(f"Synthetic data, snapshot {layer.as_of}. No patient data exists in this system.")

# ---------- main ----------
st.title("Account Intelligence")
st.markdown(
    '<p class="lede">Ask about accounts, ordering physicians, and field programs. '
    "Every number comes from a governed metric definition, and you can see the exact query behind it.</p>",
    unsafe_allow_html=True,
)
scope = f"Showing {user.territory} only" if user.territory else "Showing all territories"
st.markdown(f'<div class="scope">{who}. {scope}.</div>', unsafe_allow_html=True)


def clean_history(msgs, keep: int = 6):
    """Last few turns as strict user/assistant pairs (failed turns leave gaps)."""
    out = []
    for m in msgs:
        turn = {"role": m["role"], "content": m["content"]}
        if out and out[-1]["role"] == turn["role"]:
            out[-1] = turn
        else:
            out.append(turn)
    out = out[-keep:]
    while out and out[0]["role"] != "user":
        out.pop(0)
    while out and out[-1]["role"] != "assistant":
        out.pop()
    return out


def show_steps(steps) -> None:
    if not steps:
        return
    label = "How this was answered: 1 metric query" if len(steps) == 1 else \
        f"How this was answered: {len(steps)} metric queries"
    with st.expander(label):
        for n, s in enumerate(steps, start=1):
            if len(steps) > 1:
                st.markdown(f"**Query {n}**")
            st.json(s.query, expanded=False)
            if s.error:
                st.warning(f"Rejected by the semantic layer: {s.error}")
                continue
            st.code(s.sql, language="sql")
            df = pd.DataFrame(s.rows)
            if "case_month" in df.columns and len(df.columns) == 2:
                st.line_chart(df.set_index("case_month"))
            st.dataframe(df, width="stretch", hide_index=True)


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            if msg.get("from_cache"):
                st.caption("Saved answer")
            show_steps(msg.get("steps", []))

prompt = st.chat_input("Ask a question about your accounts") or clicked

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        result = None
        if replay_mode:
            result = agent.replay(prompt, user)
            if result is None:
                st.info("No saved answer for this question and user. Turn off saved answers to ask it live.")
        else:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                st.error("ANTHROPIC_API_KEY is not set. Export it in the terminal before running "
                         "`streamlit run app.py`, or turn on saved answers.")
            else:
                history = clean_history(st.session_state.messages[:-1])
                with st.spinner("Querying governed metrics"):
                    try:
                        result = agent.ask(prompt, user, layer, history=history)
                    except Exception as e:  # network, auth, or rate limit
                        st.error(f"The assistant could not answer: {e}. Turn on saved answers to keep demoing.")

        if result is not None:
            st.markdown(result.answer)
            if result.from_cache:
                st.caption("Saved answer")
            show_steps(result.steps)
            st.session_state.messages.append({"role": "assistant", "content": result.answer,
                                              "steps": result.steps, "from_cache": result.from_cache})
