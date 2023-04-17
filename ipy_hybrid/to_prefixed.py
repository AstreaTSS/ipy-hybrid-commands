import inspect
import typing

import interactions as ipy
from interactions.ext import prefixed_commands as prefixed

__all__ = ("slash_to_prefixed",)

def type_from_option(option_type: ipy.OptionType | int):
    if option_type == ipy.OptionType.STRING:
        return str
    elif option_type == ipy.OptionType.INTEGER:
        return int
    elif option_type == ipy.OptionType.NUMBER:
        return float
    elif option_type == ipy.OptionType.BOOLEAN:
        return bool
    elif option_type == ipy.OptionType.USER:
        return ipy.Member | ipy.User
    elif option_type == ipy.OptionType.CHANNEL:
        return ipy.BaseChannel
    elif option_type == ipy.OptionType.ROLE:
        return ipy.Role
    elif option_type == ipy.OptionType.MENTIONABLE:
        return ipy.BaseChannel | ipy.Role
    elif option_type == ipy.OptionType.ATTACHMENT:
        raise NotImplementedError("Attachments are not supported in prefixed commands.")
    raise NotImplementedError(f"Unknown option type: {option_type}")


def slash_to_prefixed(cmd: ipy.SlashCommand) -> prefixed.PrefixedCommand:
    prefixed_cmd = prefixed.PrefixedCommand(
        name=cmd.resolved_name,
        help=str(cmd.description),
        callback=cmd.callback,
        checks=cmd.checks,
        cooldown=cmd.cooldown,
        max_concurrency=cmd.max_concurrency,
        pre_run_callback=cmd.pre_run_callback,
        post_run_callback=cmd.post_run_callback,
        error_callback=cmd.error_callback,
    )

    fake_sig_parameters: list[inspect.Parameter] = []

    for option in cmd.options:
        actual_param = inspect.Parameter(name=str(option.name), kind=inspect.Parameter.POSITIONAL_OR_KEYWORD)

        slash_param = cmd.parameters.get(str(option.name))
        no_anno = True
        
        if slash_param:
            if slash_param.converter:
                actual_param = actual_param.replace(annotation=slash_param.converter)
                no_anno = False
            if slash_param.default is not inspect.Parameter.empty:
                actual_param = actual_param.replace(default=slash_param.default)
        
        if no_anno:
            anno_to_use = type_from_option(option.type)
            if not option.required:
                anno_to_use = typing.Optional[anno_to_use]
            actual_param = actual_param.replace(annotation=anno_to_use)

        fake_sig_parameters.append(actual_param)

    prefixed_cmd._inspect_signature = inspect.Signature(parameters=fake_sig_parameters)
    return prefixed_cmd
            


