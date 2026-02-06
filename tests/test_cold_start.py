import json
import os
import subprocess
import time
import socket
import pytest
import shutil
from pathlib import Path

class TestColdStart:
    
    @pytest.fixture
    def clean_env(self, tmp_path):
        # 완전 클린 환경 구축
        fake_home = tmp_path / "cold_home"
        fake_home.mkdir()
        
        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["SARI_REGISTRY_FILE"] = str(tmp_path / "cold_registry.json")
        env["PYTHONPATH"] = os.getcwd() + ":" + env.get("PYTHONPATH", "")
        # CLI 기동 시 데몬 자동 시작 옵션 활성화
        env["SARI_DAEMON_AUTOSTART"] = "1"
        env["SARI_DAEMON_PORT"] = "47995"
        
        # 포트가 사용 중인지 확인하고 청소 (강제)
        self._kill_by_port(47995)
        
        return env

    def _kill_by_port(self, port):
        try:
            output = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True)
            for pid in output.split():
                os.kill(int(pid), 9)
        except:
            pass

    def test_pure_cold_start_via_proxy(self, tmp_path, clean_env):
        workspace = str(tmp_path / "cold_ws")
        os.makedirs(os.path.join(workspace, ".sari"), exist_ok=True)
        clean_env["SARI_WORKSPACE_ROOT"] = workspace
        
        init_req = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"rootUri": f"file://{workspace}"}})
        
        def frame(msg):
            return f"Content-Length: {len(msg)}\r\n\r\n{msg}".encode()

        # 프록시 실행 (데몬이 없으므로 자동 시작 트리거)
        proc = subprocess.Popen(
            ["python3", "-m", "sari.mcp.cli", "proxy"],
            env=clean_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        try:
            # 첫 번째 initialize 요청 전송
            stdout, stderr = proc.communicate(input=frame(init_req), timeout=15)
            stdout_str = stdout.decode(errors='ignore')
            stderr_str = stderr.decode(errors='ignore')
            
            # 2. 결과 확인
            # (a) 프록시가 정상 응답을 받았는가?
            assert '"result":' in stdout_str, f"Proxy failed to respond. Stderr: {stderr_str}"
            
            # (b) 데몬이 떴는가?
            status_proc = subprocess.run(
                ["python3", "-m", "sari.mcp.cli", "daemon", "status", "--daemon-port", "47995"],
                env=clean_env, capture_output=True, text=True
            )
            assert "Running" in status_proc.stdout
            
            # (c) 중요: 임베디드 HTTP 서버가 자동으로 떴는가?
            from sari.core.server_registry import ServerRegistry
            os.environ["SARI_REGISTRY_FILE"] = clean_env["SARI_REGISTRY_FILE"]
            registry = ServerRegistry()
            
            # 워크스페이스가 리졸브될 때까지 약간 대기 (비동기 기동 대응)
            found = False
            for _ in range(10):
                ws_info = registry.get_workspace(workspace)
                if ws_info and ws_info.get("http_port"):
                    found = True
                    break
                time.sleep(0.5)
            
            assert found, "Workspace info or HTTP port missing from registry"
            
            # (d) 실제로 HTTP 포트가 살아있는가?
            http_port = ws_info["http_port"]
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                assert s.connect_ex(("127.0.0.1", http_port)) == 0, f"HTTP server at {http_port} not reachable"

        finally:
            subprocess.run(["python3", "-m", "sari.mcp.cli", "daemon", "stop", "--daemon-port", "47995"], env=clean_env)
            proc.kill()