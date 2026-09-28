"""Forge companion UI:  streamlit run app/streamlit_app.py

Pages
  Run a lab       run any chapter lab with chosen model/seeds and see tables and charts
  Agent run       watch one Forge run step by step with harness toggles
  Approvals       the governed pipeline flow from Lab 10, with real Approve/Deny buttons
  Traces          explore runs/traces.jsonl produced by Lab 20
  Harness Cards   render the cards produced by Labs 3, 14, and 28
"""
from __future__ import annotations

import importlib
import inspect
import json
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forge.config import HarnessConfig  # noqa: E402
from forge.loop import AgentLoop  # noqa: E402
from forge.models import make_model  # noqa: E402
from forge.platform import GovernedPipelineService  # noqa: E402
from forge.tasks import dev_tasks  # noqa: E402
from run_lab import lab_modules  # noqa: E402

st.set_page_config(page_title="Forge Harness Labs", layout="wide")
MODELS = ["sim:frontier", "sim:open-weight", "sim:small"]
page = st.sidebar.radio("Page", ["Run a lab", "Agent run", "Approvals", "Traces", "Harness Cards"])
st.sidebar.caption("Real models: set ANTHROPIC_API_KEY or OPENAI_API_KEY and type anthropic:<id> or openai:<id>.")


def render_report(report) -> None:
    st.subheader(f"Lab {report.lab}: {report.title}")
    st.write(report.summary)
    numeric = {k: v for k, v in report.metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    cols = st.columns(min(4, max(1, len(numeric))))
    for i, (k, v) in enumerate(numeric.items()):
        cols[i % len(cols)].metric(k, v)
    other = {k: v for k, v in report.metrics.items() if k not in numeric}
    if other:
        st.json(other, expanded=False)
    if report.table:
        st.dataframe(report.table, width="stretch")
    if report.chart and report.table:
        data = {row[report.chart["x"]]: {y: row[y] for y in report.chart["y"] if y in row} for row in report.table}
        (st.line_chart if report.chart.get("kind") == "line" else st.bar_chart)(
            {y: {str(x): vals.get(y) for x, vals in data.items()} for y in report.chart["y"]})
    for note in report.notes:
        st.info(note)
    for art in report.artifacts:
        p = ROOT / art
        if p.is_file():
            st.download_button(f"Download {p.name}", p.read_bytes(), file_name=p.name, key=art)


if page == "Run a lab":
    mods = lab_modules()
    choice = st.selectbox("Lab", list(mods), format_func=lambda n: f"{n}  {mods[n]}")
    module = importlib.import_module(f"labs.{mods[choice]}")
    st.caption((module.__doc__ or "").strip())
    params = inspect.signature(module.run).parameters
    kwargs = {}
    c1, c2 = st.columns(2)
    if "model" in params:
        default = params["model"].default
        kwargs["model"] = c1.selectbox("Model", MODELS if default in MODELS else [default, *MODELS],
                                       index=(MODELS.index(default) if default in MODELS else 0))
    if "seeds" in params:
        kwargs["seeds"] = c2.number_input("Seeds", 1, 10, int(params["seeds"].default))
    for name, p in params.items():
        if name in ("model", "seeds"):
            continue
        if isinstance(p.default, bool):
            kwargs[name] = st.checkbox(name, p.default)
        elif isinstance(p.default, int):
            kwargs[name] = st.number_input(name, 0, 1000, p.default)
        elif isinstance(p.default, str):
            kwargs[name] = st.text_input(name, p.default)
    if st.button("Run lab", type="primary"):
        with st.spinner("Running..."):
            st.session_state["report"] = module.run(**kwargs)
    if "report" in st.session_state:
        render_report(st.session_state["report"])

elif page == "Agent run":
    tasks = dev_tasks()
    task = st.selectbox("Task", tasks, format_func=lambda t: f"{t.bug_id}: {t.prompt[:70]}")
    c = st.columns(4)
    model = c[0].selectbox("Model", MODELS)
    seed = c[1].number_input("Seed", 0, 99, 0)
    style = c[2].selectbox("Tool style", ["good", "bad"])
    compaction = c[3].selectbox("Compaction", ["none", "truncate", "compact", "offload"])
    t = st.columns(5)
    cfg = HarnessConfig(enable_tests_tool=t[0].checkbox("test tool", True), enable_guides=t[1].checkbox("AGENTS.md", True),
                        enable_feedback=t[2].checkbox("sensor detail", True), protect_tests=t[3].checkbox("protect tests"),
                        loop_detection=t[4].checkbox("loop detector", True), compaction=compaction,
                        extra={"tool_style": style})
    if st.button("Run agent", type="primary"):
        events = []
        result = AgentLoop(make_model(model, int(seed)), cfg, on_event=lambda k, d: events.append((k, d))).run(task)
        st.session_state["run"] = result
    if "run" in st.session_state:
        r = st.session_state["run"]
        m = st.columns(5)
        m[0].metric("success (hidden tests)", str(r.success))
        m[1].metric("status", r.status)
        m[2].metric("steps", r.steps)
        m[3].metric("cost USD", f"{r.cost_usd:.4f}")
        m[4].metric("tampered", str(r.grade["tampered"]))
        for msg in r.messages:
            role = "user" if msg.role in ("user", "tool") else "assistant"
            with st.chat_message(role):
                if msg.tool_calls:
                    for call in msg.tool_calls:
                        st.code(f"{call.name}({json.dumps(call.arguments)[:400]})", language="json")
                if msg.content:
                    st.text(msg.content[:1500])
        st.caption(f"config fingerprint {r.config_fingerprint}")

elif page == "Approvals":
    if "gov" not in st.session_state:
        work = Path(tempfile.mkdtemp(prefix="forge-ui-"))
        shutil.copy(ROOT / "fixtures" / "sample_repo" / ".forge" / "pipeline.yaml", work / "pipeline.yaml")
        st.session_state["gov"] = GovernedPipelineService(work / "pipeline.yaml", work / "audit.jsonl")
    svc = st.session_state["gov"]
    req = st.text_input("Natural-language change request", "Add a lint stage before test")
    if st.button("Agent: propose change"):
        st.session_state["last"] = svc.propose(req, "forge-agent")
    last = st.session_state.get("last")
    if last:
        st.write(f"Status: **{last['status']}**")
        if last.get("diff"):
            st.code(last["diff"], language="diff")
        for p in last.get("problems", []):
            st.error(p)
    pending = svc.queue.pending()
    st.subheader(f"Pending approvals ({len(pending)})")
    approver = st.text_input("You are", "alice@release-eng")
    for item in pending:
        cols = st.columns([4, 1, 1])
        cols[0].write(f"`{item.id}` {item.reason}")
        if cols[1].button("Approve", key=f"a{item.id}"):
            st.toast(str(svc.decide(item.id, True, approver)))
            st.rerun()
        if cols[2].button("Deny", key=f"d{item.id}"):
            st.toast(str(svc.decide(item.id, False, approver)))
            st.rerun()
    st.subheader("Current pipeline")
    st.code(svc.pipeline_path.read_text(), language="yaml")
    if svc.audit_path.exists():
        st.subheader("Audit log")
        st.dataframe([json.loads(l) for l in svc.audit_path.read_text().splitlines()], width="stretch")

elif page == "Traces":
    path = ROOT / "runs" / "traces.jsonl"
    if not path.exists():
        st.warning("Run Lab 20 first: python run_lab.py 20")
    else:
        spans = [json.loads(l) for l in path.read_text().splitlines()]
        names = sorted({s["name"] for s in spans})
        pick = st.multiselect("Span types", names, default=["invoke_agent"])
        rows = [{"name": s["name"], "trace": s["trace_id"][:8], "ms": round(((s["end"] or s["start"]) - s["start"]) * 1000, 1),
                 "status": s["status"], **{k.split(".")[-1]: v for k, v in s["attributes"].items()
                                          if k.startswith(("forge.", "gen_ai."))}} for s in spans if s["name"] in pick]
        st.dataframe(rows, width="stretch")

elif page == "Harness Cards":
    cards = sorted((ROOT / "runs").glob("harness_card_*.md"))
    if not cards:
        st.warning("Run Lab 3, 14, or 28 to generate cards.")
    for card in cards:
        with st.expander(card.name, expanded=card.name.endswith("v1.md")):
            st.markdown(card.read_text())
