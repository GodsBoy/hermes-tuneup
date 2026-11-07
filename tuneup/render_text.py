"""Plain-text rendering of the core report for /tuneup and the CLI."""

from __future__ import annotations

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
        "Run hermes tuneup check for details."
    )


def render_active(rep: dict, cap: int | None = None) -> str:
    """Header, the active profile's findings high to low, then one fleet line."""
    entry = _active_entry(rep)
    if entry is None:
        return "tuneup: no Hermes profiles found."
    findings = sorted(entry.get("findings", []), key=lambda f: severity_rank(f["severity"]))
    head, tail = header(entry), fleet_line(rep)
    if entry.get("receipts"):
        head += f"\nReceipts: {entry['receipts']['text']}"
    blocks = [finding_block(f) for f in findings] or ["No findings: this profile's compaction settings look right."]

    def assemble(kept: list[str], dropped: int) -> str:
        parts = [head, *kept]
        if dropped:
            parts.append(f"{dropped} more, run hermes tuneup check")
        parts.append(tail)
        return "\n".join(parts)

    text = assemble(blocks, 0)
    if cap is None or len(text) <= cap or not findings:
        return text
    kept = list(blocks)
    while kept and len(assemble(kept, len(blocks) - len(kept))) > cap:
        kept.pop()
    return assemble(kept, len(blocks) - len(kept))


def render_fleet(rep: dict) -> str:
    """Every profile in full: routes, then findings, for the terminal."""
    out: list[str] = []
    for entry in rep["profiles"]:
        out.append(header(entry))
        for route in entry.get("routes", []):
            if route["role"] == "main":
                continue
            detail = route["explain"] or route["note"] or route["status"]
            out.append(f"  {route['role']}: {route['model']} on {route['provider']} {detail}")
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
