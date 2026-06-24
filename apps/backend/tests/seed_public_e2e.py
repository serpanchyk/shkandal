"""Compatibility wrapper for the deterministic public demo seed."""

from asyncio import run

from shkandal_backend.seed_demo import seed_demo

if __name__ == "__main__":
    run(seed_demo())
