import sys
import requests

BASE_URL = "https://pantograph-morphvm-5avoedvy.http.cloud.morph.so"

def _print_response(resp: requests.Response):
    print(f"Status: {resp.status_code}")
    if resp.status_code >= 500:
        try:
            print("Error JSON:", resp.json())
        except ValueError:
            print("Error text:", resp.text)
        print("❌ Server error, aborting tests.")
        sys.exit(1)

    try:
        payload = resp.json()
        print("Response JSON:", payload)
    except ValueError:
        print("Response text:", resp.text)
        payload = None
    return resp, payload

def test_goal_start(term: str):
    url = f"{BASE_URL}/goal_start"
    params = {"term": term}
    print(f"\n>>> POST {url} params={params}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

def test_goal_tactic(handle: str, tactic: str):
    url = f"{BASE_URL}/goal_tactic"
    params = {"handle": handle, "goal_id": 0, "tactic": tactic}
    print(f"\n>>> POST {url} params={params}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

def test_goal_state(handle: str):
    """GET /goal_state/{handle}"""
    url = f"{BASE_URL}/goal_state/{handle}"
    print(f">>> GET {url}")
    resp = requests.get(url)
    return _print_response(resp)

def test_goal_continue(handle: str):
    """POST /goal_continue?handle=..."""
    url = f"{BASE_URL}/goal_continue"
    params = {"handle": handle}
    print(f">>> POST {url} params={params}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

def test_expr_type(expr: str):
    """POST /expr_type?expr=..."""
    url = f"{BASE_URL}/expr_type"
    params = {"expr": expr}
    print(f">>> POST {url} params={params}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

def test_gc():
    """POST /gc"""
    url = f"{BASE_URL}/gc"
    print(f">>> POST {url}")
    resp = requests.post(url)
    return _print_response(resp)

def test_goal_save(handle: str, path: str):
    """POST /goal_save?handle=...&path=..."""
    url = f"{BASE_URL}/goal_save"
    params = {"handle": handle, "path": path}
    print(f">>> POST {url} params={params}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

def test_goal_load(path: str):
    """POST /goal_load?path=..."""
    url = f"{BASE_URL}/goal_load"
    params = {"path": path}
    print(f">>> POST {url} params={params}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

def test_compile(content: str, file_name: str = "Agent.lean"):
    """POST /compile?content=...&file_name=..."""
    url = f"{BASE_URL}/compile"
    params = {"content": content, "file_name": file_name}
    print(f">>> POST {url} params={{'content':'<...>', 'file_name':{file_name!r}}}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

def test_tactic_invocations(content: str, file_name: str = "Agent.lean"):
    """POST /tactic_invocations?content=...&file_name=..."""
    url = f"{BASE_URL}/tactic_invocations"
    params = {"content": content, "file_name": file_name}
    print(f">>> POST {url} params={{'content':'<...>', 'file_name':{file_name!r}}}")
    resp = requests.post(url, params=params)
    return _print_response(resp)

if __name__ == "__main__":
    # 1. Start with a Pi-type
    resp, data = test_goal_start("∀ n m : nat, n + m = m + n")
    handle = data and data.get("handle")
    if not handle:
        print("❌ goal_start failed, aborting.")
        sys.exit(1)
    print(f"✅ Got handle: {handle}")

    # 2–4. Two intros then rfl, always use goal_id=0
    for tactic in ("intro", "intro", "rfl"):
        resp, data = test_goal_tactic(handle, tactic)
        handle = data and data.get("handle", handle)
        print(f"✅ After `{tactic}`, new handle: {handle}")

    # 5. Fetch state
    test_goal_state(handle)

    # 6. Continue (coverage)
    _, cont = test_goal_continue(handle)
    cont_handle = cont and cont.get("handle")
    if cont_handle:
        print("✅ Continued to handle:", cont_handle)

    # 7. Save & load
    test_goal_save(handle, "state1.json")
    if cont_handle:
        test_goal_save(cont_handle, "state2.json")
    _, loaded = test_goal_load("state1.json")
    load_handle = loaded and loaded.get("handle")
    if load_handle:
        test_goal_state(load_handle)

    # 8. Environment ops
    test_expr_type("1 + 1")
    test_gc()

    # 9. Whole-file ops
    snippet = "theorem foo : 1 = 1 := by rfl"
    test_compile(snippet)
    test_tactic_invocations(snippet)

    print("\n✅ All endpoint tests completed successfully.")