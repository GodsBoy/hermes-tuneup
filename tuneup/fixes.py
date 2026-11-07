"""Preview, back up, apply and read back one confirmed fix.

The preview runs the exact write on a temporary copy, so the diff the user
confirms is what will land, including any normalisation Hermes applies when it
saves. The real write is refused if the file changed since the preview.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import hermes_adapter as adapter
from . import profiles, report
from .redact import clean
from .report import Finding
from .routes import build_routes

NO_SUCH_CODE = "No finding with that code. Run /tuneup to see current codes."
_SECRET_LINE = re.compile(
    r"^(?P<head>[ +\-]\s*[\w.\-\"']*(?:key|token|secret|password|auth|url)[\w.\-\"']*\s*:\s*)(?P<value>.+)$",
    re.IGNORECASE,
)
_PLAIN_SCALAR = re.compile(r"^(?:-?\d+(?:\.\d+)?|null|~|true|false)\s*$", re.IGNORECASE)


class FixRefused(Exception):
    """The fix did not run; the message says why and nothing was changed."""


@dataclass
class FixPlan:
    profile: str
    profile_dir: Path
    config_path: Path
    finding: Finding
    diff: str
    preview_bytes: bytes
    signature: tuple
    effect_timing: str


@dataclass
class FixResult:
    profile: str
    key: str
    before: object
    after: object
    backup: Path
    config_path: Path
    main_route: str
    effect_timing: str
    read_back_ok: bool


def normalise_code(code: str) -> str:
    return (code or "").strip().lower()


def _signature(path: Path) -> tuple:
    if not path.exists():
        return ("absent",)
    data = path.read_bytes()
    st = path.stat()
    return (st.st_mtime_ns, st.st_size, hashlib.sha256(data).hexdigest())


def _redacted_diff(before: str, after: str) -> str:
    lines = []
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), "before", "after", lineterm="", n=1):
        if line.startswith(("---", "+++", "@@")):
            continue
        match = _SECRET_LINE.match(line)
        if match and not _PLAIN_SCALAR.match(match.group("value")):
            line = match.group("head") + "[redacted]"
        lines.append(clean(line, 200))
    return "\n".join(lines) or "(no textual change)"


def _find(code: str, profile: str, active: str) -> tuple[profiles.ProfileSnapshot, Finding]:
    snapshot = profiles.find_profile(profile)
    if snapshot is None:
        raise FixRefused(f"No profile named {profile!r}. Nothing changed.")
    if snapshot.status != "ok":
        raise FixRefused(f"Profile {profile} could not be read ({snapshot.note}). Nothing changed.")
    for finding in report.findings_for(snapshot, active):
        if finding.code == code:
            return snapshot, finding
    for other in profiles.read_fleet():
        if other.name != profile and any(f.code == code for f in report.findings_for(other, active)):
            raise FixRefused(
                f"That code belongs to profile {other.name}: run `hermes tuneup fix {code} --profile {other.name}` "
                "in a terminal. Nothing changed."
            )
    raise FixRefused(NO_SUCH_CODE)


def prepare(code: str, profile: str, active: str) -> FixPlan:
    """Locate the finding fresh and build the exact preview. Writes nothing to the profile."""
    code = normalise_code(code)
    if adapter.is_managed():
        raise FixRefused("This Hermes config is managed by an administrator, so tuneup will not change it.")
    snapshot, finding = _find(code, profile, active)
    config_path = snapshot.path / "config.yaml"
    signature = _signature(config_path)
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    with adapter.isolated_home(snapshot.path) as temp:
        adapter.write_value(finding.key_path, finding.proposed)
        preview = (temp / "config.yaml").read_bytes()
    return FixPlan(
        profile=snapshot.name,
        profile_dir=snapshot.path,
        config_path=config_path,
        finding=finding,
        diff=_redacted_diff(before, preview.decode("utf-8")),
        preview_bytes=preview,
        signature=signature,
        effect_timing=finding.effect_timing,
    )


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def write_backup(config_path: Path) -> Path:
    """Exclusive-create a copy next to Hermes' own backups; never overwrite one."""
    folder = config_path.parent / "backups" / "config"
    folder.mkdir(parents=True, exist_ok=True)
    data = config_path.read_bytes() if config_path.exists() else b""
    mode = (stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600) & 0o600
    base = f"config.yaml.tuneup.{_timestamp()}"
    for n in range(1, 1000):
        target = folder / (base if n == 1 else f"{base}-{n}")
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        return target
    raise FixRefused("Could not create a unique backup name. Nothing changed.")


def _resolved(config: dict, key_path: list) -> object:
    node: object = config
    for key in key_path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def apply(plan: FixPlan) -> FixResult:
    """Write the previewed change if nothing moved underneath it, then read it back."""
    if _signature(plan.config_path) != plan.signature:
        raise FixRefused("The config changed while you were deciding. Run /tuneup again. Nothing changed.")
    original_mode = stat.S_IMODE(plan.config_path.stat().st_mode) if plan.config_path.exists() else None
    backup = write_backup(plan.config_path)
    try:
        with adapter.profile_home(plan.profile_dir):
            adapter.write_value(plan.finding.key_path, plan.finding.proposed)
    except Exception as exc:
        raise FixRefused(
            f"tuneup could not write the change ({type(exc).__name__}). The original is untouched; "
            f"backup: {backup}."
        ) from None
    if original_mode is not None:
        os.chmod(plan.config_path, original_mode)
    after_config = adapter.load_profile_config(plan.profile_dir)
    after_value = _resolved(after_config, plan.finding.key_path)
    main = next((r for r in build_routes(after_config) if r.role == "main"), None)
    return FixResult(
        profile=plan.profile,
        key=".".join(str(k) for k in plan.finding.key_path),
        before=plan.finding.current,
        after=after_value,
        backup=backup,
        config_path=plan.config_path,
        main_route=main.explain if main is not None else "",
        effect_timing=plan.effect_timing,
        read_back_ok=after_value == plan.finding.proposed,
    )


def describe(result: FixResult) -> str:
    lines = [
        f"Applied to profile {result.profile}: {result.key} changed from {clean(result.before)} to {clean(result.after)}.",
        f"Backup: {result.backup} (restore with: cp {result.backup} {result.config_path}).",
    ]
    if result.main_route:
        lines.append(f"Main route now {result.main_route}.")
    if not result.read_back_ok:
        lines.append("Warning: reading the value back through Hermes did not match what was written; check the file.")
    lines.append(f"Takes effect: {result.effect_timing}.")
    return "\n".join(lines)
