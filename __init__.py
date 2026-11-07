"""hermes-tuneup: compaction and cost advisor for Hermes Agent.

register(ctx) wires the agent tool, the /tuneup slash command, the
`hermes tuneup` CLI and the hooks. It does no I/O and touches no Hermes home,
because `hermes plugins validate` imports it in a throwaway home.
"""

from __future__ import annotations


def register(ctx) -> None:
    """Register tuneup's surfaces with Hermes."""
    from .tuneup import cli, commands, guard, tool

    ctx.register_tool(
        name="tuneup_check",
        toolset="tuneup",
        schema=tool.SCHEMA,
        handler=tool.handle,
        description=tool.SCHEMA["description"],
    )
    ctx.register_command(
        "tuneup",
        handler=commands.make_handler(ctx),
        description="When compaction really fires, and what wastes quota",
        args_hint="[fix <code> | receipts on|off]",
    )
    ctx.register_cli_command(
        name="tuneup",
        help="Compaction and cost advisor for every profile",
        setup_fn=cli.setup,
        handler_fn=cli.handle,
    )
    ctx.register_hook("pre_tool_call", guard.pre_tool_call)
