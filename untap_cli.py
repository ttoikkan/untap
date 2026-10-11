"""Unified command router above the existing standalone CLI boundaries."""

import argparse
import sys
from typing import Optional, Sequence

from untap_version import __version__


COMMANDS = {
    "run": "Search a query, run a menu or continue an unfinished run.",
    "review": "Open a saved run for local review.",
    "refresh": "Rebuild saved reports and apply selections.",
    "publish": "Publish a report to a local archive.",
    "inspect": "Inspect raw search hits without matching.",
    "smoke": "Run the explicit live integration check.",
}


def _build_parser():
    # The router owns CLI composition; runtime layers do not import this module.
    import untap
    import untap_inspect
    import untap_local_review
    import untap_publish
    import untap_refresh

    parser = argparse.ArgumentParser(
        prog="untap", description="Search, review and publish beer menus.",
        allow_abbrev=False,
        epilog="Legacy query and option forms remain supported. Use untap run --help for search options.",
    )
    parser.add_argument("--version", action="version", version=f"untap {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    definitions = {
        "run": (untap.configure_parser, untap.run_options),
        "review": (untap_local_review.configure_parser, untap_local_review.run_options),
        "refresh": (untap_refresh.configure_parser, untap_refresh.run_options),
        "publish": (untap_publish.configure_parser, untap_publish.run_options),
        "inspect": (untap_inspect.configure_parser, untap_inspect.run_options),
        "smoke": (untap.configure_parser, untap.run_options),
    }
    children = {}
    for command, (configure, execute) in definitions.items():
        # Standalone tools historically accept abbreviations; preserve that
        # policy for their equivalent subcommands. Search stays strict.
        child = subparsers.add_parser(
            command, help=COMMANDS[command], description=COMMANDS[command],
            allow_abbrev=command not in {"run", "smoke"},
        )
        configure(child)
        if command == "smoke":
            child.set_defaults(smoke_test=True)
            visible = {"help", "version", "debug", "debug_timing", "shadow_search_transport", "min_score"}
            for action in child._actions:
                if action.dest not in visible:
                    action.help = argparse.SUPPRESS
        children[command] = (child, execute)
    return parser, children


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    # Only a leading exact command name is reserved. Other text and option-led
    # forms keep the legacy search parser, including its `--` escape.
    if args and args[0] not in COMMANDS and args[0] not in {"--help", "-h", "--version"}:
        from untap import main as legacy_main
        legacy_main(args)
        return 0
    parser, children = _build_parser()
    if not args:
        parser.print_help()
        return 1
    if args[0] not in COMMANDS:
        parser.parse_args(args)
        return 0
    command = args[0]
    child, execute = children[command]
    if command == "run" and len(args) == 1:
        child.print_help()
        return 1
    if command in {"run", "smoke"}:
        from untap import _parse_cli_args
        # argparse's root subparser cannot parse intermixed positionals. Let
        # the shared search parser retain that existing argument ordering.
        options = _parse_cli_args(args[1:], parser=child)
        return execute(options) or 0
    options = child.parse_args(args[1:])
    if command in {"review", "refresh"}:
        return execute(options, child)
    return execute(options)


if __name__ == "__main__":
    raise SystemExit(main())
