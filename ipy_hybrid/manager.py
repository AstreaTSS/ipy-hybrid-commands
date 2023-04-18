import typing

import interactions as ipy
from interactions.ext import prefixed_commands as prefixed
from naff import HybridContext

from .context import HybridContext
from .hybrid_slash import _values_wrapper
from .hybrid_slash import base_subcommand_generator
from .hybrid_slash import HybridSlashCommand
from .hybrid_slash import slash_to_prefixed

__all__ = ("HybridManager", "setup")


class HybridManager:
    def __init__(
        self, client: ipy.Client, hybrid_context: type[ipy.BaseContext] = HybridContext
    ) -> None:
        if not hasattr(client, "prefixed") or not isinstance(
            client.prefixed, prefixed.PrefixedManager
        ):
            raise TypeError("Prefixed commands are not set up for this bot.")

        self.client = typing.cast(prefixed.PrefixedInjectedClient, client)
        self.hybrid_context = hybrid_context
        self.ext_command_list: dict[str, list[str]] = {}

        self.client.add_listener(self.on_callback_added.copy_with_binding(self))
        self.client.add_listener(self.handle_ext_unload.copy_with_binding(self))

        self.client.hybrid = self

    @ipy.listen()
    async def on_callback_added(self, event: ipy.events.CallbackAdded):
        if (
            not isinstance(event.callback, HybridSlashCommand)
            or not event.callback.callback
        ):
            return

        cmd = event.callback
        prefixed_transform = slash_to_prefixed(cmd)

        if cmd.is_subcommand:
            base = None
            if not (base := self.client.prefixed.commands.get(str(cmd.name))):
                base = base_subcommand_generator(
                    str(cmd.name),
                    list(_values_wrapper(cmd.name.to_locale_dict())),
                    str(cmd.name),
                    group=False,
                )
                self.client.prefixed.add_command(base)

            if cmd.group_name:  # group command
                group = None
                if not (group := base.subcommands.get(str(cmd.group_name))):
                    group = base_subcommand_generator(
                        str(cmd.group_name),
                        list(_values_wrapper(cmd.group_name.to_locale_dict())),
                        str(cmd.group_name),
                        group=True,
                    )
                    base.add_command(group)
                base = group

            base.add_command(prefixed_transform)
        else:
            self.client.prefixed.add_command(prefixed_transform)

        if cmd.extension:
            self.ext_command_list.setdefault(cmd.extension.extension_name, []).append(
                cmd.resolved_name
            )

    @ipy.listen("extension_unload")
    async def handle_ext_unload(self, event: ipy.events.ExtensionUnload) -> None:
        if not self.ext_command_list.get(event.extension.extension_name):
            return

        for cmd in self.ext_command_list[event.extension.extension_name]:
            self.client.prefixed.remove_command(cmd, delete_parent_if_empty=True)

        del self.ext_command_list[event.extension.extension_name]


def setup(
    client: ipy.Client, hybrid_context: type[ipy.BaseContext] = HybridContext
) -> HybridManager:
    return HybridManager(client, hybrid_context)
