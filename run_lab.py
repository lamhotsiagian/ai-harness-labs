#!/usr/bin/env python3
"""Run any chapter lab:  python run_lab.py 04   |   python run_lab.py --list   |   python run_lab.py all"""
import importlib
import pkgutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def lab_modules() -> dict[str, str]:
    import labs
    mods = {}
    for m in pkgutil.iter_modules(labs.__path__):
        if m.name.startswith("lab") and m.name[3:5].isdigit():
            mods[m.name[3:5]] = m.name
    return dict(sorted(mods.items()))


def main() -> None:
    mods = lab_modules()
    arg = sys.argv[1] if len(sys.argv) > 1 else "--list"
    if arg == "--list":
        for num, name in mods.items():
            doc = (importlib.import_module(f"labs.{name}").__doc__ or "").strip().splitlines()[0]
            print(f"{num}  {name:<34} {doc}")
        return
    targets = list(mods) if arg == "all" else [arg.zfill(2)]
    for num in targets:
        mod = importlib.import_module(f"labs.{mods[num]}")
        t0 = time.time()
        sys.argv = [mods[num]] + sys.argv[2:]
        mod.main()
        print(f"[lab {num} finished in {time.time() - t0:.1f}s]")


if __name__ == "__main__":
    main()
