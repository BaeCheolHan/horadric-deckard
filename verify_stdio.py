import subprocess
import json
import sys
import os
import time

def test_stdio():
    # Set PYTHONPATH to current directory to ensure we use the local source
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    
    # Run sari without arguments (should default to stdio server)
    proc = subprocess.Popen(
        [sys.executable, "-m", "sari"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=0  # Unbuffered
    )
    
    print(f"Started process {proc.pid}")
    
    # Send initialize request (JSONL)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }
    }
    
    try:
        msg = json.dumps(req) + "\n"
        print(f"Sending: {msg.strip()}")
        proc.stdin.write(msg)
        proc.stdin.flush()
        
        # Read response
        print("Waiting for response...")
        
        start_time = time.time()
        while time.time() - start_time < 5:
            if proc.poll() is not None:
                print(f"Process exited with code {proc.returncode}")
                stderr_out = proc.stderr.read()
                print(f"STDERR: {stderr_out}")
                return False
                
            line = proc.stdout.readline()
            if line:
                print(f"Received STDOUT: {line.strip()}")
                return True
            time.sleep(0.1)
            
        print("Timeout waiting for response")
        stderr_out = proc.stderr.read()
        if stderr_out:
            print(f"STDERR output:\n{stderr_out}")
            
    except Exception as e:
        print(f"Exception: {e}")
    finally:
        proc.terminate()
        
    return False

if __name__ == "__main__":
    if test_stdio():
        print("✅ Test Passed")
        sys.exit(0)
    else:
        print("❌ Test Failed")
        sys.exit(1)