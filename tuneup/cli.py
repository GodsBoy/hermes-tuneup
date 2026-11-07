"""`hermes tuneup check|report|fix`: the fleet view, receipts and confirmed fixes for the terminal."""

from __future__ import annotations

import json

from . import confirm, fixes, profiles, render_text, report

EXIT_CLEAN, EXIT_HIGH, EXIT_UNRESOLVED = 0, 1, 2


def setup(parser) -> None:
    subs = parser.add_subparsers(dest="tuneup_command")
    check = subs.add_parser("check", help="Show when compaction fires on every profile and what to fix")
    check.add_argument("--profile", help="Only this profile")
    check.add_argument("--json", action="store_true", help="Machine-readable report")
    rep = subs.add_parser("report", help="Show prediction receipts: predicted against actual compaction")
    rep.add_argument("--profile", help="Only this profile")
    rep.add_argument("--json", action="store_true", help="Machine-readable receipts")
    fix = subs.add_parser("fix", help="Apply one finding's fix after you confirm it at this terminal")
    fix.add_argument("code", help="The six-character code shown with the finding")
    fix.add_argument("--profile", help="The profile the finding belongs to (default: the active profile)")
    parser.set_defaults(func=handle)


def exit_code(rep: dict) -> int:
    unresolved = any(p["status"] != "ok" for p in rep["profiles"]) or any(
        r["status"] == "unresolved" for p in rep["profiles"] for r in p.get("routes", [])
    )
    if unresolved or not rep["profiles"]:
        return EXIT_UNRESOLVED
    if any(f["severity"] == "high" for p in rep["profiles"] for f in p.get("findings", [])):
        return EXIT_HIGH
    return EXIT_CLEAN


def _unknown_profile(name: str | None) -> bool:
    if name and name not in profiles.profile_names():
        print(f"tuneup: no profile named {name!r}")
        return True
    return False


def _check(args) -> int:
    name = args.profile
    if _unknown_profile(name):
        return EXIT_UNRESOLVED
    rep = report.build_report(only=name)
    print(json.dumps(rep, indent=2) if args.json else render_text.render_fleet(rep))
    return exit_code(rep)


def _fix(args) -> int:
    refusal = confirm.cli_refusal()
    if refusal:
        print(refusal)
        return EXIT_UNRESOLVED
    active = profiles.active_profile()
    try:
        plan = fixes.prepare(args.code, profile=getattr(args, "profile", None) or active, active=active)
    except fixes.FixRefused as exc:
        print(exc)
        return EXIT_UNRESOLVED
    print(confirm.question(plan))
    if input("Type yes to apply: ").strip().lower() != "yes":
        print("Nothing changed.")
        return EXIT_CLEAN
    try:
        result = fixes.apply(plan)
    except fixes.FixRefused as exc:
        print(exc)
        return EXIT_UNRESOLVED
    print(fixes.describe(result))
    return EXIT_CLEAN if result.read_back_ok else EXIT_HIGH


def _report(args) -> int:
    name = args.profile
    if _unknown_profile(name):
        return EXIT_UNRESOLVED
    rep = report.build_report(only=name, checks=[])
    if args.json:
        print(json.dumps({p["name"]: p.get("receipts") for p in rep["profiles"]}, indent=2))
    else:
        print(render_text.render_receipts(rep))
    return EXIT_CLEAN


def handle(args) -> int:
    sub = getattr(args, "tuneup_command", None) or "check"
    if sub == "check":
        return _check(args)
    if sub == "report":
        return _report(args)
    if sub == "fix":
        return _fix(args)
    print("Usage: hermes tuneup check|report [--profile NAME] [--json] | hermes tuneup fix CODE [--profile NAME]")
    return EXIT_UNRESOLVED
