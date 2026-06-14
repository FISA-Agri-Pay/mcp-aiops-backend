from __future__ import annotations

import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer


QUERY_FIELDS = (
    "index",
    "name",
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "memory.free",
    "temperature.gpu",
    "power.draw",
)

HELP_LINES = (
    "# HELP DCGM_FI_DEV_GPU_UTIL GPU utilization percent",
    "# TYPE DCGM_FI_DEV_GPU_UTIL gauge",
    "# HELP DCGM_FI_DEV_MEM_COPY_UTIL GPU memory copy utilization percent",
    "# TYPE DCGM_FI_DEV_MEM_COPY_UTIL gauge",
    "# HELP DCGM_FI_DEV_FB_USED GPU framebuffer memory used in MiB",
    "# TYPE DCGM_FI_DEV_FB_USED gauge",
    "# HELP DCGM_FI_DEV_FB_FREE GPU framebuffer memory free in MiB",
    "# TYPE DCGM_FI_DEV_FB_FREE gauge",
    "# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature in Celsius",
    "# TYPE DCGM_FI_DEV_GPU_TEMP gauge",
    "# HELP DCGM_FI_DEV_POWER_USAGE GPU power draw in watts",
    "# TYPE DCGM_FI_DEV_POWER_USAGE gauge",
)


class MetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path not in {"/", "/metrics"}:
            self.send_response(404)
            self.end_headers()
            return

        body = build_metrics().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_metrics() -> str:
    command = [
        "nvidia-smi",
        "--query-gpu=" + ",".join(QUERY_FIELDS),
        "--format=csv,noheader,nounits",
    ]
    rows = subprocess.check_output(command, text=True).strip().splitlines()
    lines = list(HELP_LINES)
    for row in rows:
        index, name, gpu_util, memory_util, memory_used, memory_free, temp, power = [
            part.strip() for part in row.split(",")
        ]
        labels = f'gpu="{index}",modelName="{escape_label(name)}"'
        lines.extend(
            [
                f"DCGM_FI_DEV_GPU_UTIL{{{labels}}} {gpu_util}",
                f"DCGM_FI_DEV_MEM_COPY_UTIL{{{labels}}} {memory_util}",
                f"DCGM_FI_DEV_FB_USED{{{labels}}} {memory_used}",
                f"DCGM_FI_DEV_FB_FREE{{{labels}}} {memory_free}",
                f"DCGM_FI_DEV_GPU_TEMP{{{labels}}} {temp}",
                f"DCGM_FI_DEV_POWER_USAGE{{{labels}}} {power}",
            ]
        )
    return "\n".join(lines) + "\n"


def escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9400), MetricsHandler).serve_forever()
