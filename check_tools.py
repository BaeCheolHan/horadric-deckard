import subprocess
import json
import sys
import os
import time

def test_tools_list():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    
    proc = subprocess.Popen(
        [sys.executable, "-m", "sari"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=0
    )
    
    # Send initialize first
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }
    }
    
    # Send tools/list
    list_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    
    try:
        # Using JSONL for simplicity as we fixed hybrid framing
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.write(json.dumps(list_req) + "\n")
        proc.stdin.flush()
        
        start_time = time.time()
        while time.time() - start_time < 5:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    print("Process exited")
                    break
                continue
                
            print(f"OUT: {line.strip()}")
            
            # If we see Content-Length, read body
            if line.lower().startswith("content-length:"):
                length = int(line.split(":")[1].strip())
                proc.stdout.readline() # Skip empty line
                body = proc.stdout.read(length)
                print(f"BODY: {body}")
                resp = json.loads(body)
                if resp.get("id") == 2:
                    tools = resp.get("result", {}).get("tools", [])
                    print(f"Tool count: {len(tools)}")
                    return len(tools) > 0
                    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        proc.terminate()
        
    return False

if __name__ == "__main__":
    if test_tools_list():
        print("✅ Tools found")
    else:
        print("❌ No tools found or error")