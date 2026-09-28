"""Lab 2: Forge v0, a framework-free agent loop with budgets, streaming, and interrupts."""
from __future__ import annotations

import time

from labs.common import LabReport, finish, lab_args
from forge.config import HarnessConfig
from forge.messages import Message
from forge.models import cost_usd, make_model
from forge.sandbox import Sandbox
from forge.tasks import cleanup, dev_tasks, grade, prepare_workspace
from forge.toolkit import build_forge_tools


def forge_v0(task, model, max_steps=12, max_cost=0.50, cancel_after=None, stream=print) -> dict:
    """The whole agent in one function: the loop every framework hides from you."""
    ws = prepare_workspace(task)
    tools = build_forge_tools(Sandbox(ws), HarnessConfig())
    system = "You are Forge. Fix the bug, run the tests, then answer starting with DONE:."
    messages = [Message("user", task.user_message())]
    spent, stop_reason, steps = 0.0, "max_steps", 0
    for step in range(1, max_steps + 1):
        if cancel_after is not None and step > cancel_after:          # interrupt: checked between steps
            stop_reason = "interrupted"
            break
        steps = step
        resp = model.complete(system, messages, tools.schemas())
        spent += cost_usd(getattr(model, "prices", (0, 0, 0)), resp.usage)
        messages.append(resp.message)
        if not resp.message.tool_calls:                               # stop condition 1: final answer
            stream(f"  [{step}] final: {resp.message.content}")
            stop_reason = "final_answer"
            break
        for call in resp.message.tool_calls:                          # act, then observe
            out = tools.call(call.name, call.arguments)
            stream(f"  [{step}] {call.name}({', '.join(f'{k}=' + repr(v)[:40] for k, v in call.arguments.items())})"
                   f" -> {out.content.splitlines()[0][:70] if out.content else ''}")
            messages.append(Message("tool", out.content, tool_call_id=call.id, name=call.name))
        if spent >= max_cost:                                         # stop condition 2: money
            stop_reason = "max_cost"
            break
    g = grade(task, ws)
    cleanup(ws)
    return {"task": task.id, "stop_reason": stop_reason, "steps": steps, "cost_usd": round(spent, 5),
            "passed_hidden_tests": g["passed"]}


def run(model: str = "sim:frontier", seeds: int = 1) -> LabReport:
    task = dev_tasks()[5]
    print(f"Task: {task.prompt}")
    t0 = time.time()
    normal = forge_v0(task, make_model(model, 0))
    interrupted = forge_v0(task, make_model(model, 0), cancel_after=1, stream=lambda s: None)
    tiny_budget = forge_v0(task, make_model(model, 0), max_steps=2, stream=lambda s: None)
    rows = [dict(scenario="normal", **normal), dict(scenario="interrupt after step 1", **interrupted),
            dict(scenario="step budget = 2", **tiny_budget)]
    return LabReport("02", "Forge v0: a framework-free loop", "Three stop conditions on one task. The budget stop "
                     "can leave an unverified edit behind: grading, not the stop reason, tells you if it worked.", {"wall_seconds": round(time.time() - t0, 2)}, rows)


def main() -> None:
    a = lab_args(__doc__, seeds=1)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()
