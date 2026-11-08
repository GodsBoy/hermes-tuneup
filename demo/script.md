# Demo script (under 90 seconds)

Filmed on the synthetic `tuneup-demo` profile (`python3 demo/seed_home.py`). The caption says so: "Demo profile seeded with settings we hit on real profiles."

## Before recording

- Reseed the demo profile so every finding is present.
- Receipts on for the demo profile (`/tuneup receipts on`) and one long session run to a threshold compaction with the current tuneup, so beat 4 has a real receipt that carries the request size.
- A model route with working credentials for the chat beats. The demo profile's main route must be able to answer.
- Terminal font large, window about 1280 by 720, no other profiles' names on screen.

## Beats

| Time | Beat | On screen |
|---|---|---|
| 0 to 10 s | The problem | A long session; the user asks Hermes "why did my quota vanish?" |
| 10 to 35 s | Hermes diagnoses itself | Hermes calls `tuneup_check`, explains that the main route compacts at about 500K tokens, that the `anthropic:claude-opus` rule never applies on the subscription provider, and that pruning is breaking the prompt cache. It ends with the exact fix command and does not apply anything. |
| 35 to 60 s | The confirmed fix | The user types `/tuneup fix <code>`; the confirm prompt shows the profile, the one-line diff and when it takes effect; the user picks Apply; the reply shows the backup path and the new trigger. |
| 60 to 80 s | Proof | `/tuneup` shows the receipt: the last threshold compaction fired after a request in line with tuneup's predicted trigger, both measured on the whole request. If the pane shipped, show it for about ten seconds. |
| 80 to 90 s | Close | `hermes plugins install GodsBoy/hermes-tuneup --enable`, repo link, end card. |

## Lines to say or caption

- "Hermes says 50%. Your real trigger depends on the route, the rules that actually match, the summariser and the cache."
- "tuneup asks Hermes' own code, so the number is the one Hermes uses."
- "Nothing changes until you confirm, and there is always a backup."
