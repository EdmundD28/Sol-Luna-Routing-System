def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("config", "schedule", "results", "artifacts", "cache", "patches", "rollout", "retention"))
    parser.add_argument("--input", default="-")
    args = parser.parse_args(argv)
    # Dispatch positions are frozen here; domain operations remain unimplemented.
    if args.command == "artifacts":
        from .artifacts import build_inventory
        build_inventory(())
    elif args.command == "cache":
        from .cache import resolve_cache
        resolve_cache((), {})
    elif args.command == "patches":
        from .patches import plan_patch_waves
        plan_patch_waves(())
    elif args.command == "rollout":
        from .rollout import assign_rollout
        assign_rollout((), {})
    elif args.command == "retention":
        from .retention import apply_retention
        apply_retention((), (), {}, 0)
    else:
        raise NotImplementedError
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
