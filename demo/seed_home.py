"""Create or reset the synthetic `tuneup-demo` profile used to film the demo.

It only ever writes ~/.hermes/profiles/tuneup-demo/config.yaml (backing up
an existing one first) and never touches any other profile. The config is
synthetic: it reproduces, on one profile, the settings tuneup flags.

    python3 demo/seed_home.py [--hermes-root ~/.hermes]

Then enable the plugin for that profile:

    hermes -p tuneup-demo plugins enable hermes-tuneup
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROFILE = "tuneup-demo"

SEED = """\
# Synthetic demo profile for hermes-tuneup. Safe to delete.
model:
  default: claude-opus-5-5[1m]
  provider: claude-subscription-directsdk-experimental
compression:
  threshold: 0.5
  proactive_prune_tokens: 48000
  model_thresholds:
    "anthropic:claude-opus": 0.8
delegation:
  model: gpt-6.1-sol
  provider: openai-codex
  reasoning_effort: high
plugins:
  enabled:
    - hermes-tuneup
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hermes-root", default=str(Path.home() / ".hermes"))
    args = parser.parse_args()
    profile = Path(args.hermes_root).expanduser() / "profiles" / PROFILE
    profile.mkdir(parents=True, exist_ok=True)
    config = profile / "config.yaml"
    if config.exists():
        backup = profile / f"config.yaml.seed-backup.{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(config, backup)
        print(f"Backed up the existing demo config to {backup}")
    config.write_text(SEED, encoding="utf-8")
    print(f"Seeded {config}")
    print("Check it with: hermes -p tuneup-demo tuneup check --profile tuneup-demo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
