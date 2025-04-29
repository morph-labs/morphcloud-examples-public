import uuid, uvicorn
import asyncio
from asyncio import DefaultEventLoopPolicy
from pydantic import BaseModel
from typing import Any, Dict, Optional, Literal, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pantograph import Server, ServerError
from pantograph.server import TacticFailure
from pantograph.data import CompilationUnit
from pantograph.expr import TacticHave, TacticLet, TacticCalc, TacticExpr

class StringTacticRequest(BaseModel):
    type: Literal["string"]
    tactic: str

class HaveTacticRequest(BaseModel):
    type: Literal["have"]
    branch: str
    binder_name: Optional[str] = None

class LetTacticRequest(BaseModel):
    type: Literal["let"]
    branch: str
    binder_name: Optional[str] = None

class CalcTacticRequest(BaseModel):
    type: Literal["calc"]
    step: str

class ExprTacticRequest(BaseModel):
    type: Literal["expr"]
    expr: str

# Combined request model
TacticRequest = Union[
    StringTacticRequest, 
    HaveTacticRequest, 
    LetTacticRequest, 
    CalcTacticRequest, 
    ExprTacticRequest
]

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
@app.exception_handler(TacticFailure)
async def tactic_failure_handler(request: Request, exc: TacticFailure):
    # Return the tactic error messages as JSON
    return JSONResponse(
        status_code=422,  # Unprocessable Entity - request was valid but couldn't be processed
        content={"tactic_error": exc.args[0]}
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
async def goal_tactic(
    handle: str, 
    goal_id: int, 
    tactic_request: Union[TacticRequest, Dict[str, Any]]
):
    if handle not in handles:
        raise HTTPException(404)
    
    # First determine if this is a direct tactic specification or a TacticRequest
    if isinstance(tactic_request, dict) and "__tactic_type" in tactic_request:
        # Direct tactic specification format
        tactic_type = tactic_request.pop("__tactic_type")
        
        if tactic_type == "TacticHave":
            tactic = TacticHave(**tactic_request)
        elif tactic_type == "TacticLet":
            tactic = TacticLet(**tactic_request)
        elif tactic_type == "TacticCalc":
            tactic = TacticCalc(**tactic_request)
        elif tactic_type == "TacticExpr":
            tactic = TacticExpr(**tactic_request)
        elif tactic_type == "string":
            tactic = tactic_request.get("tactic", "")
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid direct tactic type: {tactic_type}"
            )
    else:
        # Standard TacticRequest format
        if tactic_request.type == "string":
            tactic = tactic_request.tactic
        elif tactic_request.type == "have":
            tactic = TacticHave(
                branch=tactic_request.branch,
                binder_name=tactic_request.binder_name
            )
        elif tactic_request.type == "let":
            tactic = TacticLet(
                branch=tactic_request.branch,
                binder_name=tactic_request.binder_name
            )
        elif tactic_request.type == "calc":
            tactic = TacticCalc(step=tactic_request.step)
        elif tactic_request.type == "expr":
            tactic = TacticExpr(expr=tactic_request.expr)
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid tactic type: {tactic_request.type}"
            )
    
    # Call the pantograph service with the constructed tactic
    st = await srv.goal_tactic_async(handles[handle], goal_id, tactic)
    out = vars(st).copy()
    out["handle"] = _new_handle(st)
    out.pop("state_id", None)
    
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
    # Handle messages as strings instead of dictionaries
    messages_list = [{"text": m, "severity": "info", "line": 0, "col": 0} for m in cu.messages]
    
    return {
        "messages": messages_list,
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