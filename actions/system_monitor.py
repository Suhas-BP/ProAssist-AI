"""
System Monitor — background metric checks with voice alert support.
Zero subprocess calls on all platforms — uses ctypes/pynvml/psutil/wmi only.
"""
import ctypes
import platform
import time

import psutil

from core.tool import AgentTool, ToolResult

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

DEFAULT_THRESHOLDS = {
    "cpu":  90.0,
    "ram":  90.0,
    "temp": 85.0,
    "gpu":  95.0,
}

_COOLDOWN   = 300
_CPU_STREAK = 3

# ── NVML DLL cache (Windows: nvml.dll, Linux: libnvidia-ml.so.1) ─────────────
_nvml_lib: object = None
_nvml_ok:  object = None   # None=untested  True=works  False=unavailable


def _nvml_gpu() -> float:
    """GPU utilisation via NVML — zero subprocess on all platforms."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            if _OS == "Windows":
                candidates = ("nvml", r"C:\Windows\System32\nvml.dll")
                _load = ctypes.WinDLL
            else:
                candidates = (
                    "libnvidia-ml.so.1",
                    "libnvidia-ml.so",
                    "libnvidia-ml.dylib",
                )
                _load = ctypes.CDLL
            for name in candidates:
                try:
                    lib = _load(name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            _nvml_ok = False
            return -1.0

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        u = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
        _nvml_ok = True
        return float(u.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


def _get_gpu_usage() -> float:
    # pynvml — subprocess-free, works everywhere if installed
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
    except Exception:
        pass

    return _nvml_gpu()


def _get_cpu_temp() -> float:
    # psutil — works on Linux; occasionally Windows with proper drivers
    try:
        temps = psutil.sensors_temperatures()
        for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                     "cpu-thermal", "zenpower", "it8688"]:
            if name in temps and temps[name]:
                return temps[name][0].current
        for entries in temps.values():
            if entries:
                return entries[0].current
    except Exception:
        pass

    # Windows: wmi module (pure Python COM, zero subprocess)
    if _OS == "Windows":
        try:
            import wmi  # type: ignore
            w = wmi.WMI(namespace="root/wmi")
            tz = w.MSAcpi_ThermalZoneTemperature()
            if tz:
                return (tz[0].CurrentTemperature / 10.0) - 273.15
        except Exception:
            pass

    return -1.0


def get_disk_metrics() -> dict:
    """Returns structured disk usage metrics across partitions and formatted summary."""
    drives = []
    try:
        parts = psutil.disk_partitions(all=False)
        for p in parts:
            try:
                usage = psutil.disk_usage(p.mountpoint)
                drives.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "total_gb": round(usage.total / (1024 ** 3), 1),
                    "used_gb": round(usage.used / (1024 ** 3), 1),
                    "free_gb": round(usage.free / (1024 ** 3), 1),
                    "percent": round(usage.percent, 1),
                })
            except Exception:
                continue
    except Exception:
        pass

    summary_text = ""
    try:
        from actions.file_controller import get_disk_usage
        summary_text = get_disk_usage("home")
    except Exception:
        pass

    return {
        "drives": drives,
        "summary": summary_text,
    }


def get_network_throughput(interval: float = 0.3) -> dict:
    """Computes network transfer rates (sent/recv per sec) sampled over interval."""
    try:
        t0 = time.monotonic()
        c0 = psutil.net_io_counters()
        time.sleep(max(0.1, interval))
        t1 = time.monotonic()
        c1 = psutil.net_io_counters()
        dt = max(0.001, t1 - t0)

        sent_sec = (c1.bytes_sent - c0.bytes_sent) / dt
        recv_sec = (c1.bytes_recv - c0.bytes_recv) / dt
        return {
            "kb_sent_per_sec": round(sent_sec / 1024, 1),
            "kb_recv_per_sec": round(recv_sec / 1024, 1),
            "mb_sent_per_sec": round(sent_sec / (1024 * 1024), 2),
            "mb_recv_per_sec": round(recv_sec / (1024 * 1024), 2),
            "total_sent_mb": round(c1.bytes_sent / (1024 * 1024), 1),
            "total_recv_mb": round(c1.bytes_recv / (1024 * 1024), 1),
        }
    except Exception as e:
        return {
            "kb_sent_per_sec": 0.0,
            "kb_recv_per_sec": 0.0,
            "mb_sent_per_sec": 0.0,
            "mb_recv_per_sec": 0.0,
            "total_sent_mb": 0.0,
            "total_recv_mb": 0.0,
            "error": str(e),
        }


def get_top_processes(n: int = 5, sample_interval: float = 0.25, timeout: float = 3.0) -> dict:
    """Enumerate top resource-consuming processes by CPU% and memory (read-only, with timeout)."""
    n = max(1, min(20, int(n)))
    deadline = time.monotonic() + timeout
    procs = []

    # Phase 1: prime CPU counters
    try:
        for p in psutil.process_iter(["pid", "name"]):
            if time.monotonic() > deadline:
                break
            try:
                p.cpu_percent(None)
                procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    # Sample interval
    time.sleep(max(0.1, sample_interval))

    # Phase 2: compute CPU% and memory info
    cpu_count = psutil.cpu_count() or 1
    collected = []
    try:
        for p in procs:
            if time.monotonic() > deadline:
                break
            try:
                name = p.name() or "unknown"
                if p.pid == 0 or "idle" in name.lower():
                    continue
                cpu_raw = p.cpu_percent(None)
                cpu_norm = round(cpu_raw / cpu_count, 1)
                mem_info = p.memory_info()
                mem_mb = round(mem_info.rss / (1024 * 1024), 1) if mem_info else 0.0
                mem_pct = round(p.memory_percent(), 1)
                collected.append({
                    "pid": p.pid,
                    "name": name,
                    "cpu_percent": cpu_norm,
                    "memory_percent": mem_pct,
                    "memory_mb": mem_mb,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    top_cpu = sorted(collected, key=lambda x: x["cpu_percent"], reverse=True)[:n]
    top_memory = sorted(collected, key=lambda x: x["memory_mb"], reverse=True)[:n]

    return {
        "top_cpu": top_cpu,
        "top_memory": top_memory,
        "total_processes_scanned": len(collected),
    }


def diagnose_system(top_n: int = 5, timeout: float = 4.0) -> dict:
    """
    Diagnostic flow: gathers CPU, RAM, disk, network, temperature, battery,
    and top-consuming processes together in one call.
    Produces evidence-grounded data points and a plain-language summary
    explaining why the computer may be slow.
    """
    t0 = time.monotonic()
    deadline = t0 + timeout

    # 1. Overlap network sampling and process priming in parallel
    c0 = psutil.net_io_counters() if hasattr(psutil, "net_io_counters") else None
    proc_sample = []
    try:
        for p in psutil.process_iter(["pid", "name"]):
            if time.monotonic() > deadline:
                break
            try:
                p.cpu_percent(None)
                proc_sample.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

    time.sleep(0.3)
    t1 = time.monotonic()
    dt = max(0.001, t1 - t0)

    # 2. Network rate
    net_metrics = {}
    if c0 and hasattr(psutil, "net_io_counters"):
        try:
            c1 = psutil.net_io_counters()
            sent_sec = (c1.bytes_sent - c0.bytes_sent) / dt
            recv_sec = (c1.bytes_recv - c0.bytes_recv) / dt
            net_metrics = {
                "kb_sent_per_sec": round(sent_sec / 1024, 1),
                "kb_recv_per_sec": round(recv_sec / 1024, 1),
                "mb_sent_per_sec": round(sent_sec / (1024 * 1024), 2),
                "mb_recv_per_sec": round(recv_sec / (1024 * 1024), 2),
            }
        except Exception:
            pass

    # 3. CPU, RAM, GPU, Temp
    cpu_pct = round(psutil.cpu_percent(interval=None), 1)
    ram = psutil.virtual_memory()
    ram_pct = round(ram.percent, 1)
    ram_used_gb = round(ram.used / (1024 ** 3), 1)
    ram_total_gb = round(ram.total / (1024 ** 3), 1)
    temp = _get_cpu_temp()
    gpu = _get_gpu_usage()

    # 4. Process metrics
    cpu_count = psutil.cpu_count() or 1
    proc_data = []
    for p in proc_sample:
        if time.monotonic() > deadline:
            break
        try:
            name = p.name() or "unknown"
            if p.pid == 0 or "idle" in name.lower():
                continue
            cpu_val = round(p.cpu_percent(None) / cpu_count, 1)
            mem_mb = round(p.memory_info().rss / (1024 * 1024), 1)
            mem_pct = round(p.memory_percent(), 1)
            proc_data.append({
                "pid": p.pid,
                "name": name,
                "cpu_percent": cpu_val,
                "memory_percent": mem_pct,
                "memory_mb": mem_mb,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    top_cpu = sorted(proc_data, key=lambda x: x["cpu_percent"], reverse=True)[:top_n]
    top_mem = sorted(proc_data, key=lambda x: x["memory_mb"], reverse=True)[:top_n]

    # 5. Disk metrics (reusing file_controller)
    disk_metrics = get_disk_metrics()

    # 6. Battery info (reusing computer_settings.battery_status)
    battery_info = {}
    try:
        from actions.computer_settings import battery_status
        battery_info = battery_status()
    except Exception:
        pass

    # 7. Formulate evidence-grounded bottlenecks
    bottlenecks = []

    if cpu_pct >= 80.0:
        top_culprit = f" (top consumer: {top_cpu[0]['name']} at {top_cpu[0]['cpu_percent']}%)" if top_cpu else ""
        bottlenecks.append(f"CPU is under heavy load ({cpu_pct}%){top_culprit}")

    if ram_pct >= 85.0:
        top_mem_culprit = f" (top consumer: {top_mem[0]['name']} using {top_mem[0]['memory_mb']} MB)" if top_mem else ""
        bottlenecks.append(f"RAM is nearly exhausted ({ram_pct}% used, {ram_used_gb}/{ram_total_gb} GB){top_mem_culprit}")

    for d in disk_metrics.get("drives", []):
        if d.get("percent", 0) >= 90.0:
            bottlenecks.append(f"Drive {d['mountpoint']} is critically full ({d['percent']}% used, {d['free_gb']} GB free)")

    if temp > 0 and temp >= 80.0:
        bottlenecks.append(f"High CPU temperature ({temp:.1f}°C)")

    if gpu >= 90.0:
        bottlenecks.append(f"GPU is heavily utilized ({gpu:.1f}%)")

    if battery_info.get("has_battery") and not battery_info.get("plugged") and (battery_info.get("percent") or 100) <= 15:
        bottlenecks.append(f"Battery is critically low ({battery_info.get('percent')}%) on discharge")

    # 8. Plain-language explanation grounded in actual observed numbers
    primary_drive_pct = disk_metrics.get("drives", [{}])[0].get("percent", "N/A") if disk_metrics.get("drives") else "N/A"
    if bottlenecks:
        summary = (
            f"Computer performance diagnosis found {len(bottlenecks)} pressure point(s): "
            + "; ".join(bottlenecks) + ". "
            f"Current state: CPU {cpu_pct}%, RAM {ram_pct}%, Primary Disk {primary_drive_pct}%."
        )
    else:
        top_c_info = f"Top CPU process: {top_cpu[0]['name']} ({top_cpu[0]['cpu_percent']}%)" if top_cpu else "CPU normal"
        summary = (
            f"System performance is normal with no critical bottlenecks detected. "
            f"CPU is at {cpu_pct}%, RAM at {ram_pct}% ({ram_used_gb}/{ram_total_gb} GB), "
            f"primary drive at {primary_drive_pct}% capacity. "
            f"{top_c_info}."
        )

    return {
        "bottlenecks": bottlenecks,
        "summary": summary,
        "cpu_percent": cpu_pct,
        "ram_percent": ram_pct,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "gpu_percent": round(gpu, 1) if gpu >= 0 else None,
        "cpu_temp_c": round(temp, 1) if temp > 0 else None,
        "network": net_metrics,
        "disk": disk_metrics,
        "battery": battery_info,
        "top_cpu_processes": top_cpu,
        "top_memory_processes": top_mem,
    }


def get_system_status() -> dict:
    """Snapshot of current system metrics for the system_status tool."""
    cpu  = psutil.cpu_percent(interval=0.2)
    ram  = psutil.virtual_memory()
    temp = _get_cpu_temp()
    gpu  = _get_gpu_usage()

    boot_time   = psutil.boot_time()
    uptime_secs = time.time() - boot_time
    uptime_h    = int(uptime_secs // 3600)
    uptime_m    = int((uptime_secs % 3600) // 60)

    disk_data = get_disk_metrics()
    net_data = get_network_throughput(interval=0.1)

    battery_data = {}
    try:
        from actions.computer_settings import battery_status
        battery_data = battery_status()
    except Exception:
        pass

    procs = get_top_processes(n=3, sample_interval=0.1)

    return {
        "cpu_percent":        round(cpu, 1),
        "ram_percent":        round(ram.percent, 1),
        "ram_used_gb":        round(ram.used / 1024 ** 3, 1),
        "ram_total_gb":       round(ram.total / 1024 ** 3, 1),
        "cpu_temp_c":         round(temp, 1) if temp > 0 else None,
        "gpu_percent":        round(gpu, 1) if gpu >= 0 else None,
        "uptime":             f"{uptime_h}h {uptime_m}m",
        "process_count":      len(psutil.pids()),
        "disk":               disk_data.get("drives", []),
        "network_throughput": net_data,
        "battery":            battery_data,
        "top_cpu_processes":  procs.get("top_cpu", []),
        "top_mem_processes":  procs.get("top_memory", []),
    }


class SystemMonitor:
    """
    Stateful monitor — cooldown state persists across session reconnections.
    Call check() periodically; returns a [SYSTEM_ALERT] string or None.
    """

    def __init__(self, thresholds: dict | None = None):
        self.thresholds   = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._last_alert: dict[str, float] = {}
        self._cpu_streak  = 0

    def _can_alert(self, key: str) -> bool:
        return (time.monotonic() - self._last_alert.get(key, 0)) > _COOLDOWN

    def _record(self, key: str):
        self._last_alert[key] = time.monotonic()

    def check(self) -> str | None:
        try:
            cpu  = psutil.cpu_percent(interval=None)
            ram  = psutil.virtual_memory().percent
            temp = _get_cpu_temp()
            gpu  = _get_gpu_usage()
        except Exception:
            return None

        alerts: list[str] = []

        if cpu >= self.thresholds["cpu"]:
            self._cpu_streak += 1
            if self._cpu_streak >= _CPU_STREAK and self._can_alert("cpu"):
                alerts.append(
                    f"[SYSTEM_ALERT] CPU usage has been critically high ({cpu:.0f}%) "
                    "for several seconds. Warn the user in their language and suggest "
                    "closing heavy applications."
                )
                self._record("cpu")
                self._cpu_streak = 0
        else:
            self._cpu_streak = 0

        if ram >= self.thresholds["ram"] and self._can_alert("ram"):
            alerts.append(
                f"[SYSTEM_ALERT] RAM is at {ram:.0f}% — nearly exhausted. "
                "Warn the user in their language and suggest freeing memory."
            )
            self._record("ram")

        if temp > 0 and temp >= self.thresholds["temp"] and self._can_alert("temp"):
            alerts.append(
                f"[SYSTEM_ALERT] CPU temperature is {temp:.0f}°C — above the safe limit. "
                "Warn the user in their language and advise reducing system load "
                "or checking cooling."
            )
            self._record("temp")

        if gpu >= 0 and gpu >= self.thresholds["gpu"] and self._can_alert("gpu"):
            alerts.append(
                f"[SYSTEM_ALERT] GPU load is at {gpu:.0f}%. "
                "Briefly inform the user in their language."
            )
            self._record("gpu")

        return " ".join(alerts) if alerts else None


def system_monitor(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
    **extra,
) -> dict:
    """Action handler for the system_monitor tool."""
    params = parameters or {}
    raw_action = str(params.get("action") or "status").lower().strip()
    n = int(params.get("n") or 5)

    if raw_action in ("diagnose", "why_is_my_computer_slow", "slow", "performance", "check_health"):
        diag = diagnose_system(top_n=n)
        return {
            "success": True,
            "action": "diagnose",
            "value": diag,
            "message": diag.get("summary", "System performance diagnostic complete."),
        }
    elif raw_action in ("processes", "top_processes", "proc", "running_processes"):
        proc_data = get_top_processes(n=n)
        top_cpu_names = ", ".join(f"{p['name']} ({p['cpu_percent']}%)" for p in proc_data["top_cpu"][:3])
        return {
            "success": True,
            "action": "processes",
            "value": proc_data,
            "message": f"Top CPU consumers: {top_cpu_names}." if top_cpu_names else "Process listing retrieved.",
        }
    elif raw_action in ("disk", "disk_usage", "storage"):
        disk_data = get_disk_metrics()
        summary = disk_data.get("summary") or f"Found {len(disk_data.get('drives', []))} drive(s)."
        return {
            "success": True,
            "action": "disk",
            "value": disk_data,
            "message": summary,
        }
    elif raw_action in ("network", "network_throughput", "net", "throughput"):
        net_data = get_network_throughput(interval=0.3)
        return {
            "success": True,
            "action": "network",
            "value": net_data,
            "message": f"Network: {net_data['kb_sent_per_sec']} KB/s sent, {net_data['kb_recv_per_sec']} KB/s received.",
        }
    else:  # default "status"
        status_data = get_system_status()
        summary = (
            f"CPU: {status_data['cpu_percent']}%, RAM: {status_data['ram_percent']}% "
            f"({status_data['ram_used_gb']}/{status_data['ram_total_gb']} GB), "
            f"Uptime: {status_data['uptime']}."
        )
        return {
            "success": True,
            "action": "status",
            "value": status_data,
            "message": summary,
        }


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
class SystemMonitorTool(AgentTool):
    @property
    def name(self) -> str:
        return "system_monitor"

    @property
    def description(self) -> str:
        return (
            "Inspects system performance, resource usage, and health metrics: "
            "CPU, RAM, GPU, temperature, disk usage, network throughput, battery status, "
            "and top resource-consuming processes. Includes 'diagnose' action for answering "
            "'why is my computer slow?'."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "Monitoring action to perform: "
                        "status (overall system snapshot) | "
                        "diagnose (analyze bottlenecks / why computer is slow) | "
                        "processes (top CPU and memory consuming processes) | "
                        "disk (disk drive usage and capacity) | "
                        "network (current network throughput rates)"
                    ),
                },
                "n": {
                    "type": "INTEGER",
                    "description": "Number of top processes to return (default: 5).",
                },
            },
            "required": [],
        }

    def execute(self, parameters: dict = None, **context):
        known = {"response", "player", "session_memory"}
        filtered = {k: v for k, v in context.items() if k in known}
        return system_monitor(parameters=parameters, **filtered)


ACTION = SystemMonitorTool()
TOOL = ACTION.to_tool_dict()

