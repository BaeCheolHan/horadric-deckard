import psutil
import os
import threading
import time
from typing import Dict, List, Any

def get_system_metrics() -> Dict[str, Any]:
    """Returns a dictionary of current system resource usage."""
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        try:
            disk = psutil.disk_usage(os.getcwd())
            disk_percent = disk.percent
        except Exception:
            disk_percent = 0.0
        
        process = psutil.Process(os.getpid())
        with process.oneshot():
            proc_mem_mb = process.memory_info().rss / (1024**2)
            proc_cpu_percent = process.cpu_percent(interval=None)
            thread_count = process.num_threads()

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "disk_percent": disk_percent,
            "process_memory_mb": round(proc_mem_mb, 1),
            "process_cpu_percent": proc_cpu_percent,
            "process_thread_count": thread_count,
            "active_threads": threading.active_count()
        }
    except Exception:
        return {"error": "Failed to collect metrics"}

def list_sari_processes() -> List[Dict[str, Any]]:
    """Lists all running Sari-related processes."""
    procs = []
    my_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'memory_info']):
        try:
            cmdline = proc.info.get('cmdline') or []
            cmd_str = " ".join(cmdline).lower()
            # Filter for Sari related processes
            if "sari" in cmd_str and ("python" in cmd_str or "sari" in proc.info['name'].lower()):
                procs.append({
                    "pid": proc.info['pid'],
                    "name": proc.info['name'],
                    "cmd": " ".join(cmdline),
                    "created": proc.info['create_time'],
                    "memory_mb": round(proc.info['memory_info'].rss / (1024**2), 1),
                    "is_self": proc.info['pid'] == my_pid
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(procs, key=lambda x: x['created'])

def kill_sari_process(pid: int) -> bool:
    """Terminates a specific process by PID."""
    try:
        if pid == os.getpid():
            return False # Don't suicide via this API
        proc = psutil.Process(pid)
        proc.terminate()
        return True
    except Exception:
        return False