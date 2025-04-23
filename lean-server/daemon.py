import uuid, uvicorn
import asyncio
from asyncio import DefaultEventLoopPolicy
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pantograph import Server, ServerError
from pantograph.data import CompilationUnit

PORT, app = 5326, FastAPI()
srv = None
handles: dict[str, Any] = {}   # handle → full state object
rev:     dict[int, str] = {}   # state_id → handle

def _slug() -> str:
    return f"gs_{uuid.uuid4().hex[:8]}"

def _new_handle(st: Any) -> str:
    sid = st.state_id
    if sid in rev:
        return rev[sid]

    h = _slug()
    handles[h] = st       # store the *object*, not just sid
    rev[sid] = h
    return h

# Global exception handler for Pantograph errors
@app.exception_handler(ServerError)
async def pantograph_exception_handler(request: Request, exc: ServerError):
    # Return the Lean server error payload as JSON
    return JSONResponse(
        status_code=422,
        content={"lean_error": exc.args[0]}
    )

@app.on_event("startup")
async def boot():  # one Lean kernel
    global srv; srv = await Server.create(imports=['Init', 'Mathlib'], project_path = "/root/mathlib_project/", timeout = 350)
    imports = srv.imports
    print(f"{imports}")

# ---------- goal helpers ----------
@app.post("/goal_start")
async def goal_start(term: str):
    st = await srv.goal_start_async(term)
    out = vars(st).copy(); out["handle"] = _new_handle(st); out.pop("state_id", None)
    return out

@app.post("/goal_tactic")
async def goal_tactic(handle: str, goal_id: int, tactic: str):
    if handle not in handles: raise HTTPException(404)
    st = await srv.goal_tactic_async(handles[handle], goal_id, tactic)
    out = vars(st).copy(); out["handle"] = _new_handle(st); out.pop("state_id", None)
    return out

@app.get("/goal_state/{handle}")
async def goal_state(handle: str):
    if handle not in handles: raise HTTPException(404)
    
    # Get the state object from handles dictionary
    state_obj = handles[handle]
    
    # Use the same pattern as goal_start and goal_tactic
    # This accesses the state object's __dict__ directly instead of using goal_root_async
    out = vars(state_obj).copy()
    out["handle"] = handle
    out.pop("state_id", None)
    
    return out

# ---------- environment ----------
@app.post("/expr_type")
async def expr_type(expr: str):
    return {"type": await srv.expr_type_async(expr)}

@app.post("/gc")
async def gc(): await srv.gc_async(); return {"ok": True}

# ---------- goal save/load ----------
@app.post("/goal_save")
async def goal_save(handle: str, path: str):
    if handle not in handles: raise HTTPException(404)
    await srv.goal_save_async(handles[handle], path)
    return {"saved": path}

@app.post("/goal_load")
async def goal_load(path: str):
    st = await srv.goal_load_async(path)
    out = vars(st).copy(); out["handle"] = _new_handle(st); out.pop("state_id", None)
    return out

# ---------- whole‑file compilation ----------
def _cu_to_dict(cu: CompilationUnit):
    return {
        "messages": [
            {"severity": m["severity"],
             "text": m["data"]["pp"],
             "line": m["data"]["pos"]["line"],
             "col": m["data"]["pos"]["column"]} for m in cu.messages
        ],
        **({"goal_handle": _new_handle(cu.goal_state)} if cu.goal_state else {}),
        **({"tactic_invocations": cu.invocations} if cu.invocations else {})
    }

@app.post("/compile")
async def compile(content: str):
    units = await srv.load_sorry_async(content)
    return {"units": [_cu_to_dict(u) for u in units]}

@app.post("/tactic_invocations")
async def tactic_invocations(file_name: str = "Agent.lean"):
    units = await srv.tactic_invocations_async(file_name=file_name)
    return {"units": [_cu_to_dict(u) for u in units]}

if __name__ == "__main__":
    # force the built‑in loop
    asyncio.set_event_loop_policy(DefaultEventLoopPolicy())

    # instruct uvicorn to use asyncio, not auto‑detect uvloop
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        loop="asyncio",
    )