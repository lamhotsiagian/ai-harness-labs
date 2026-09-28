# ai-harness-labs

> **Companion Code Repository**: [https://github.com/lamhotsiagian/ai-harness-labs](https://github.com/lamhotsiagian/ai-harness-labs)

Companion code for the book **Harness Engineering in Practice: Building Agent, Agentic & Evaluation Harnesses** (Volume 2 Edition).
*A Systems Engineering Guide to DeepSeek Harness, Production Agent Runtimes, Execution Sandboxes, Multi-Agent Workflows, Continuous Evaluation & Harness System Design Interviews.*

One running project, **Forge**, a CI/CD and repository maintenance agent, grows chapter by chapter from a 40-line loop into a governed, observable, evaluated harness, alongside a dedicated chapter and lab for **DeepSeek Harness (dsh)** with local Ollama runtime.

- Pure Python 3.10+ standard library for the core and every lab.
- Deterministic and free by default: labs use `SimulatedModel`, an oracle-backed policy calibrated to
  react to harness changes the way real models do (context rot, feedback, injection, reward hacking).
- Real models plug in with one flag: `--model anthropic:<model-id>` or `--model openai:<model-id>`
  (`OPENAI_BASE_URL` also covers vLLM, Ollama, and LiteLLM gateways).

## Quick start

```bash
cd ai-harness-labs
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                          # optional extras: streamlit, mcp
python run_lab.py --list                                 # all 28 labs
python run_lab.py 01                                     # one lab
python run_lab.py all                                    # every lab (about 10 minutes)
python -m unittest discover -s tests -t .                # unit + headless UI tests
streamlit run app/streamlit_app.py                       # companion UI
```

## Layout

```
forge/                  the harness
  loop.py               budgeted, traced agent loop (Ch 2)
  messages.py config.py provider-neutral types, HarnessConfig + fingerprint (Ch 2-3)
  models.py             SimulatedModel, Anthropic and OpenAI-compatible adapters
  tools.py toolkit.py   tool registry, validation, truncation, idempotency; Forge tools (Ch 8)
  context.py            prompt layout, spotlighting, compaction/offload (Ch 4)
  skills.py             Skills with progressive disclosure (Ch 5)
  memory.py             progress ledger, episodic store with write gate (Ch 6)
  retrieval.py          BM25, dense proxy, RRF hybrid, rerank, agentic search (Ch 7)
  mcp_server.py         stdlib MCP server + client; mcp_fastmcp_server.py (official SDK) (Ch 9)
  platform.py           governed pipeline changes, approvals, audit, contract tests (Ch 10)
  sandbox.py            path jail, allowlist, scrubbed env, egress policy, container cmd (Ch 11)
  hooks.py hook_suite.py lifecycle hooks and the standard suite (Ch 12)
  sensors.py            tamper detector, critic reviewer (Ch 13)
  harness_card.py       Harness Cards and seven-layer teardowns (Ch 3, 14)
  longhorizon.py        initializer/worker sessions over a backlog (Ch 15)
  multiagent.py         reviewer subagent, context firewall, durable workflow, kill switch (Ch 16)
  policy.py             permission modes, approvals, guardrails, lethal trifecta (Ch 18-19)
  tracing.py            OTel GenAI-style spans, JSONL and OTLP export (Ch 20)
  cost.py               token ledger, routing, cascade, gateway failover (Ch 21)
  reliability.py        chaos model, retries, circuit breaker, canary gate (Ch 22)
  improve.py            correction capture, improvement gate, trajectory export (Ch 23)
  evals/                runner, graders, judge calibration, statistics, red-team, reports (Ch 24-27)
fixtures/               sample repo with 20 real bugs, runbooks, Skills, injection payloads
labs/lab01..lab28       one lab per chapter; each exposes run(...) -> LabReport
app/streamlit_app.py    UI: run labs, watch an agent run, approve pipeline changes, traces, cards
tests/                  unit tests and a headless Streamlit test
runs/                   outputs (reports, traces, cards, datasets)
```

## Testing from the UI

1. `streamlit run app/streamlit_app.py` and open http://localhost:8501.
2. **Run a lab**: pick a lab, choose a model and seeds, press *Run lab*. Tables, charts, and artifacts render.
3. **Agent run**: pick a task, toggle harness features (test tool, AGENTS.md, sensor detail, protect tests,
   loop detector, compaction, tool style), press *Run agent*, and read the transcript step by step.
4. **Approvals**: type a change request, press *Agent: propose change*, inspect the diff, then *Approve* or
   *Deny* as a human. Self-approval by the agent is refused; every event lands in the audit table.
5. **Traces** (after Lab 20) and **Harness Cards** (after Labs 3, 14, 28).

## Real models

```bash
export ANTHROPIC_API_KEY=...;  python run_lab.py 01 --model anthropic:<model-id> --seeds 1
export OPENAI_API_KEY=...;     python run_lab.py 01 --model openai:<model-id> --seeds 1
export OPENAI_BASE_URL=http://localhost:8000/v1; python run_lab.py 21 --model openai:<served-model>
```
Real runs cost money: start with `--seeds 1` and a small lab. The simulator's task oracle is used only by
`SimulatedModel`; real models see the same prompts, tools, and hidden-test grading.

## Observability backends

`forge.tracing.Tracer.ship_otlp()` posts OTLP/HTTP JSON to `$OTEL_EXPORTER_OTLP_ENDPOINT/v1/traces`.
For Langfuse, set the endpoint to your Langfuse OTel URL and export `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY` (basic auth is added automatically).

Author: AI Engineering Insider, http://aiengineeringinsider.com
Subscribe: https://aiengineeringinsider.substack.com/subscribe
# ai-harness-labs
