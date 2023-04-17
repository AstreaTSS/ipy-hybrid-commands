import interactions as ipy
from interactions.ext import prefixed_commands as prefixed

from .to_prefixed import slash_to_prefixed

__all__ = ("HackyBot",)

class HackyBot(prefixed.PrefixedInjectedClient):
    def add_interaction(self, command: ipy.InteractionCommand) -> bool:
        actual_cmd = super().add_interaction(command)
        if actual_cmd and isinstance(command, ipy.SlashCommand):
            prefixed = slash_to_prefixed(command)
            self.prefixed.add_command(prefixed)

        return actual_cmd