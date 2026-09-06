"""Run local algorithm benchmarks without fragile pass/fail timing limits."""

from geometry_dash_ai.app.benchmark import run_benchmarks

for result in run_benchmarks():
    print(f"{result.name}: {result.rate_hz:.1f} Hz ({result.total_ms:.2f} ms total)")
