"""CLI boundary separating generation and deterministic execution."""

import argparse
import json
from functools import partial

from .store import Store, read_json, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="AUTOTEST monitoring: separate generation and replay")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "regenerate", "run", "_worker"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--store", required=True, help="Absolute artifact directory")
        cmd.add_argument("--headed", action="store_true")
        cmd.add_argument("--output", help="Write JSON report to this path")
        if name == "_worker":
            cmd.add_argument("--request", required=True)
        else:
            cmd.add_argument("--site", required=True)
        if name in ("generate", "regenerate"):
            cmd.add_argument("--provider", type=int, choices=range(1, 7), default=1)
            cmd.add_argument("--max-depth", type=int, default=2)
        if name == "regenerate":
            group = cmd.add_mutually_exclusive_group(required=True)
            group.add_argument("--page")
            group.add_argument("--pending", action="store_true")
        if name == "run":
            cmd.add_argument("--page-timeout", type=float, default=120)
    args = parser.parse_args(argv)
    store = Store(args.store)
    from .browser import create_driver
    factory = partial(create_driver, headless=not args.headed)
    try:
        if args.command == "_worker":
            from .runner import execute_page
            report = execute_page(store, read_json(args.request), driver_factory=factory)
            if not args.output:
                parser.error("_worker requires --output")
            write_json(args.output, report)
            return 0
        if args.command == "run":
            if args.page_timeout <= 0:
                parser.error("--page-timeout must be positive")
            from .runner import run_site
            report = run_site(store, args.site, args.page_timeout, headless=not args.headed)
            code = 1 if report["counts"]["FAIL"] else 2 if report["counts"]["SKIP"] else 0
        else:
            if args.max_depth < 0:
                parser.error("--max-depth must be nonnegative")
            pages = None
            if args.command == "regenerate":
                pages = ([r["page_url"] for r in store.pending(args.site)]
                         if args.pending else [args.page])
                if not pages:
                    report = {"site_url": args.site, "published": [], "errors": []}
                    if args.output:
                        write_json(args.output, report)
                    print(json.dumps(report))
                    return 0
            # These imports must stay out of run/_worker, including transitively.
            from ..core.web_test_generator import WebTestGenerator
            from .generation import generate_site
            generator = WebTestGenerator(llm_provider_choice=args.provider, driver_factory=factory)
            try:
                report = generate_site(store, args.site, generator, args.max_depth, pages)
            finally:
                generator.driver.quit()
            code = 2 if report["errors"] else 0
        if args.output:
            write_json(args.output, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return code
    except Exception as exc:
        parser.exit(2, "Monitoring error: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
