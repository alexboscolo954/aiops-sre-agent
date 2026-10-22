"""Load for the optimizer lab: one container burns CPU and holds memory in a shape
chosen by PROFILE, so Sizings have real usage to learn from.

PROFILE: steady | diurnal | spiky | leak | idle | burst-once (CronJob)
CPU (cores) and MEMORY_MIB set the level; PERIOD_S stretches the diurnal day.
"""

import math
import multiprocessing as mp
import os
import time

PROFILE = os.environ.get("PROFILE", "steady")
CPU = float(os.environ.get("CPU", "0.2"))
MEMORY_MIB = int(os.environ.get("MEMORY_MIB", "64"))
PERIOD_S = float(os.environ.get("PERIOD_S", str(24 * 3600)))
SLICE = 0.1


def cores(t: float) -> float:
    """How many cores to burn at time t (seconds since start)."""
    if PROFILE == "diurnal":
        return CPU * (0.55 + 0.45 * math.sin(2 * math.pi * t / PERIOD_S))
    if PROFILE == "spiky":
        return CPU * 6 if t % 900 < 60 else CPU * 0.25  # a minute's burst every 15 minutes
    if PROFILE == "idle":
        return 0.01
    return CPU


PEAK = {"diurnal": CPU, "spiky": CPU * 6, "idle": 0.01}.get(PROFILE, CPU)


def burn(worker: int, level: "mp.sharedctypes.Synchronized[float]") -> None:
    """Burn this worker's share of `level` cores, in 100 ms slices."""
    while True:
        share = max(0.0, min(1.0, level.value - worker))
        t0 = time.monotonic()
        while time.monotonic() - t0 < SLICE * share:
            pass
        time.sleep(max(0.0, SLICE * (1 - share)))


def main() -> None:
    start = time.time()
    level = mp.Value("d", cores(0))
    for w in range(max(1, math.ceil(PEAK))):
        mp.Process(target=burn, args=(w, level), daemon=True).start()
    held = [bytearray(MEMORY_MIB * 2**20)]
    stop = start + float(os.environ.get("DURATION_S", "60"))
    while True:
        level.value = cores(time.time() - start)
        if PROFILE == "leak":
            held.append(bytearray(int(os.environ.get("LEAK_MIB_PER_MIN", "4")) * 2**20))
        if PROFILE == "burst-once" and time.time() > stop:
            return
        newest = held[-1]  # touch its pages so they count as resident memory
        newest[::4096] = b"x" * len(newest[::4096])
        time.sleep(60 if PROFILE == "leak" else 5)


if __name__ == "__main__":
    main()
