"""Plain-text rendering of the core report for /tuneup and the CLI."""

from __future__ import annotations

from .report import hermes_command
from .routes import SWITCHED_ROLES
from .severity import severity_counts, severity_rank


def _active_entry(rep: dict) -> dict | None:
    return next((p for p in rep["profiles"] if p.get("active")), rep["profiles"][0] if rep["profiles"] else None)


def _main(entry: dict) -> dict | None:
    return next((r for r in entry.get("routes", []) if r["role"] == "main"), None)


def header(entry: dict) -> str:
    if entry["status"] != "ok":
        return f"tuneup: profile {entry['name']} could not be read ({entry['note']})"
    main = _main(entry)
    if main is None or main["status"] == "unresolved":
        return f"tuneup: profile {entry['name']}: main route unresolved ({(main or {}).get('note', 'no model configured')})"
    return f"tuneup: profile {entry['name']}, {main['model']} on {main['provider']} {main['explain']}"


def route_line(route: dict) -> str:
    """One route under its label ("you switch to" for a declared model), for chat and terminal."""
    detail = route["explain"] or route["note"] or route["status"]
    return f"{route['label']}: {route['model']} on {route['provider']} {detail}"


def _switched_lines(entry: dict) -> list[str]:
    return [route_line(r) for r in entry.get("routes", []) if r["role"] in SWITCHED_ROLES]


def finding_block(f: dict) -> str:
    return f"[{f['severity'].upper()}] {f['summary']}\n  fix: {f['fix_command']}"


def fleet_line(rep: dict) -> str:
    profiles = rep["profiles"]
    findings = [f for p in profiles for f in p.get("findings", [])]
    counts = severity_counts(findings)
    unresolved = sum(1 for p in profiles if p["status"] != "ok")
    extra = f", {unresolved} unreadable" if unresolved else ""
    def plural(n: int, word: str) -> str:
        return f"{n} {word}" + ("" if n == 1 else "s")

    return (
        f"Fleet: {plural(len(profiles), 'profile')}{extra}, {plural(len(findings), 'finding')} "
        f"({counts['high']} high, {counts['medium']} medium, {counts['low']} low). "
        f"Run {hermes_command(rep['active_profile'], 'tuneup check')} for details."
    )


def render_active(rep: dict, cap: int | None = None) -> str:
    """Header, the models the profile switches to, the active profile's findings high to low, then one
    fleet line.

    Under a messaging cap, findings come first: route lines for switched models are dropped before
    any finding, leaving a count that points to /tuneup models, and only then are findings dropped.
    """
    entry = _active_entry(rep)
    if entry is None:
        return "tuneup: no Hermes profiles found."
    findings = sorted(entry.get("findings", []), key=lambda f: severity_rank(f["severity"]))
    tail = fleet_line(rep)
    switched = _switched_lines(entry)
    receipts = f"Receipts: {entry['receipts']['text']}" if entry.get("receipts") else ""
    blocks = [finding_block(f) for f in findings] or ["No findings: this profile's compaction settings look right."]

    def assemble(lines: list[str], kept: list[str], dropped: int) -> str:
        parts = [header(entry), *lines]
        if len(lines) < len(switched):
            hidden = len(switched) - len(lines)
            parts.append(f"{hidden} more models you switch to or were seen using, run /tuneup models")
        if receipts:
            parts.append(receipts)
        parts += kept
        if dropped:
            parts.append(f"{dropped} more, run {hermes_command(rep['active_profile'], 'tuneup check')}")
        parts.append(tail)
        return "\n".join(parts)

    lines = list(switched)
    if cap is None or len(assemble(lines, blocks, 0)) <= cap:
        return assemble(lines, blocks, 0)
    while lines and len(assemble(lines, blocks, 0)) > cap:
        lines.pop()
    if len(assemble(lines, blocks, 0)) <= cap or not findings:
        return assemble(lines, blocks, 0)
    kept = list(blocks)
    while kept and len(assemble(lines, kept, len(blocks) - len(kept))) > cap:
        kept.pop()
    return assemble(lines, kept, len(blocks) - len(kept))


def render_fleet(rep: dict) -> str:
    """Every profile in full: routes, then findings, for the terminal."""
    out: list[str] = []
    for entry in rep["profiles"]:
        out.append(header(entry))
        for route in entry.get("routes", []):
            if route["role"] == "main":
                continue
            out.append(f"  {route_line(route)}")
        for f in sorted(entry.get("findings", []), key=lambda f: severity_rank(f["severity"])):
            out.append("  " + finding_block(f).replace("\n", "\n  "))
        if entry["status"] == "ok" and not entry.get("findings"):
            out.append("  No findings.")
        out.append("")
    out.append(fleet_line(rep))
    return "\n".join(out)


def render_receipts(rep: dict) -> str:
    """One receipts summary per profile, for hermes tuneup report."""
    lines = []
    for entry in rep["profiles"]:
        text = (entry.get("receipts") or {}).get("text") or entry.get("note") or entry["status"]
        lines.append(f"{entry['name']}: {text}")
    return "\n".join(lines) or "tuneup: no Hermes profiles found."
