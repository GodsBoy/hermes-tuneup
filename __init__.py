"""hermes-tuneup: compaction and cost advisor for Hermes Agent.

register(ctx) wires the agent tool, the /tuneup slash command, the
`hermes tuneup` CLI and the hooks. It does no I/O and touches no Hermes home,
because `hermes plugins validate` imports it in a throwaway home.
"""

from __future__ import annotations


def register(ctx) -> None:
    """Register tuneup's surfaces with Hermes."""
    from .tuneup import cli, commands, guard, receipts, tool

    recorder = receipts.Recorder(ctx)

    ctx.register_tool(
        name="tuneup_check",
        toolset="tuneup",
        schema=tool.SCHEMA,
        handler=tool.handle,
        description=tool.SCHEMA["description"],
    )
    ctx.register_command(
        "tuneup",
        handler=commands.make_handler(ctx, recorder),
        description="When compaction really fires, and what wastes quota",
        args_hint="[fix <code> | receipts on|off | models [add|remove <provider>:<model> | days <n>]]",
    )
    ctx.register_cli_command(
        name="tuneup",
        help="Compaction and cost advisor for every profile",
        setup_fn=cli.setup,
        handler_fn=cli.handle,
    )
    ctx.register_hook("pre_tool_call", guard.pre_tool_call)
    ctx.register_hook("post_api_request", recorder.on_api_request)
    ctx.register_hook("post_compaction", recorder.on_compaction)
