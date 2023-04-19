import asyncio
import inspect
import typing

import attrs
import interactions as ipy
from interactions.ext import prefixed_commands as prefixed
from interactions.models.internal.converters import _LiteralConverter

if typing.TYPE_CHECKING:
    from .context import HybridContext

__all__ = ("HybridSlashCommand", "hybrid_slash_command", "hybrid_slash_subcommand")


def _values_wrapper(a_dict: dict | None):
    return list(a_dict.values()) if a_dict else []


class BasicConverter(ipy.Converter):
    def __init__(self, type_to_convert: typing.Any) -> None:
        self.type_to_convert = type_to_convert

    async def convert(self, ctx: ipy.BaseContext, arg: str) -> typing.Any:
        return self.type_to_convert(arg)


class BoolConverter(ipy.Converter):
    async def convert(self, ctx: ipy.BaseContext, argument: str) -> bool:
        lowered = argument.lower()
        if lowered in {"yes", "y", "true", "t", "1", "enable", "on"}:
            return True
        elif lowered in {"no", "n", "false", "f", "0", "disable", "off"}:
            return False
        else:
            raise ipy.errors.BadArgument(
                f"{argument} is not a recognised boolean option."
            )


class AttachmentConverter(ipy.NoArgumentConverter):
    async def convert(self, ctx: "HybridContext", _: typing.Any) -> ipy.Attachment:
        try:
            attachment = ctx.message.attachments[ctx.__attachment_index__]
            ctx.__attachment_index__ += 1
            return attachment
        except IndexError:
            raise ipy.errors.BadArgument("No attachment found.") from None


class ChoicesConverter(_LiteralConverter):
    def __init__(self, choices: list[ipy.SlashCommandChoice | dict]) -> None:
        standardized_choices = tuple(
            (ipy.SlashCommandChoice(**o) if isinstance(o, dict) else o) for o in choices
        )

        names = tuple(c.name for c in standardized_choices)
        self.values = {str(arg): str for arg in names}
        self.choice_values = {str(c.name): c.value for c in standardized_choices}

    async def convert(self, ctx: ipy.BaseContext, argument: str) -> typing.Any:
        val = await super().convert(ctx, argument)
        return self.choice_values[val]


class RangeConverter(ipy.Converter[float | int]):
    def __init__(
        self,
        number_type: int,
        min_value: typing.Optional[float | int],
        max_value: typing.Optional[float | int],
    ) -> None:
        self.number_type = number_type
        self.min_value = min_value
        self.max_value = max_value

        self.number_convert = int if number_type == ipy.OptionType.INTEGER else float

    async def convert(self, ctx: ipy.BaseContext, argument: str) -> float | int:
        try:
            converted: float | int = await ipy.utils.maybe_coroutine(
                self.number_convert, ctx, argument
            )

            if self.min_value and converted < self.min_value:
                raise ipy.errors.BadArgument(
                    f'Value "{argument}" is less than {self.min_value}.'
                )
            if self.max_value and converted > self.max_value:
                raise ipy.errors.BadArgument(
                    f'Value "{argument}" is greater than {self.max_value}.'
                )

            return converted
        except ValueError:
            type_name = (
                "number" if self.number_type == ipy.OptionType.NUMBER else "integer"
            )

            if type_name.startswith("i"):
                raise ipy.errors.BadArgument(
                    f'Argument "{argument}" is not an {type_name}.'
                ) from None
            else:
                raise ipy.errors.BadArgument(
                    f'Argument "{argument}" is not a {type_name}.'
                ) from None
        except ipy.errors.BadArgument:
            raise


class StringLengthConverter(ipy.Converter[str]):
    def __init__(
        self, min_length: typing.Optional[int], max_length: typing.Optional[int]
    ) -> None:
        self.min_length = min_length
        self.max_length = max_length

    async def convert(self, ctx: ipy.BaseContext, argument: str) -> str:
        if self.min_length and len(argument) < self.min_length:
            raise ipy.errors.BadArgument(
                f'The string "{argument}" is shorter than'
                f" {self.min_length} character(s)."
            )
        elif self.max_length and len(argument) > self.max_length:
            raise ipy.errors.BadArgument(
                f'The string "{argument}" is longer than'
                f" {self.max_length} character(s)."
            )

        return argument


class NarrowedChannelConverter(ipy.BaseChannelConverter):
    def __init__(self, channel_types: list[ipy.ChannelType | int]) -> None:
        self.channel_types = channel_types

    def _check(self, result: ipy.BaseChannel) -> bool:
        return result.type in self.channel_types


class HackyUnionConverter(ipy.Converter):
    def __init__(self, *converters: type[ipy.Converter]) -> None:
        self.converters = converters

    async def convert(self, ctx: ipy.BaseContext, arg: str) -> typing.Any:
        for converter in self.converters:
            try:
                return await converter().convert(ctx, arg)
            except Exception:
                continue

        union_names = tuple(
            ipy.utils.get_object_name(t).removesuffix("Converter")
            for t in self.converters
        )
        union_types_str = ", ".join(union_names[:-1]) + f", or {union_names[-1]}"
        raise ipy.errors.BadArgument(
            f'Could not convert "{arg}" into {union_types_str}.'
        )


class ChainConverter(ipy.Converter):
    def __init__(
        self,
        first_converter: ipy.Converter,
        second_converter: type[ipy.Converter] | ipy.Converter,
        name_of_cmd: str,
    ) -> None:
        self.first_converter = first_converter
        self.second_converter = second_converter
        self.name_of_cmd = name_of_cmd

    async def convert(self, ctx: ipy.BaseContext, arg: str) -> typing.Any:
        first = await self.first_converter.convert(ctx, arg)
        return await ipy.utils.maybe_coroutine(
            ipy.BaseCommand._get_converter_function(
                self.second_converter, self.name_of_cmd
            )(ctx, first)
        )


class ChainNoArgConverter(ipy.NoArgumentConverter):
    def __init__(
        self,
        first_converter: ipy.NoArgumentConverter,
        second_converter: type[ipy.Converter] | ipy.Converter,
        name_of_cmd: str,
    ) -> None:
        self.first_converter = first_converter
        self.second_converter = second_converter
        self.name_of_cmd = name_of_cmd

    async def convert(self, ctx: "HybridContext", _: typing.Any) -> typing.Any:
        first = await self.first_converter.convert(ctx, _)
        return await ipy.utils.maybe_coroutine(
            ipy.BaseCommand._get_converter_function(
                self.second_converter, self.name_of_cmd
            )(ctx, first)
        )


def type_from_option(option_type: ipy.OptionType | int) -> ipy.Converter:
    if option_type == ipy.OptionType.STRING:
        return BasicConverter(str)
    elif option_type == ipy.OptionType.INTEGER:
        return BasicConverter(int)
    elif option_type == ipy.OptionType.NUMBER:
        return BasicConverter(float)
    elif option_type == ipy.OptionType.BOOLEAN:
        return BoolConverter()
    elif option_type == ipy.OptionType.USER:
        return HackyUnionConverter(ipy.MemberConverter, ipy.UserConverter)
    elif option_type == ipy.OptionType.CHANNEL:
        return ipy.BaseChannelConverter()
    elif option_type == ipy.OptionType.ROLE:
        return ipy.RoleConverter()
    elif option_type == ipy.OptionType.MENTIONABLE:
        return HackyUnionConverter(
            ipy.MemberConverter, ipy.UserConverter, ipy.RoleConverter
        )
    elif option_type == ipy.OptionType.ATTACHMENT:
        return AttachmentConverter()
    raise NotImplementedError(f"Unknown option type: {option_type}")


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class HybridSlashCommand(ipy.SlashCommand):
    async def __call__(self, context: ipy.SlashContext, *args, **kwargs) -> None:
        new_ctx = context.client.hybrid.hybrid_context.from_slash_context(context)
        await super().__call__(new_ctx, *args, **kwargs)

    def group(
        self,
        name: str = None,
        description: str = "No Description Set",
        inherit_checks: bool = True,
    ) -> "HybridSlashCommand":
        return HybridSlashCommand(
            name=self.name,
            description=self.description,
            group_name=name,
            group_description=description,
            scopes=self.scopes,
            dm_permission=self.dm_permission,
            checks=self.checks if inherit_checks else [],
        )

    def subcommand(
        self,
        sub_cmd_name: ipy.Absent[ipy.LocalisedName | str] = ipy.MISSING,
        group_name: ipy.LocalisedName | str = None,
        sub_cmd_description: ipy.Absent[ipy.LocalisedDesc | str] = ipy.MISSING,
        group_description: ipy.Absent[ipy.LocalisedDesc | str] = ipy.MISSING,
        options: typing.List[typing.Union[ipy.SlashCommandOption, typing.Dict]] = None,
        nsfw: bool = False,
        inherit_checks: bool = True,
    ) -> typing.Callable[[ipy.const.AsyncCallable], "HybridSlashCommand"]:
        def wrapper(call: ipy.const.AsyncCallable) -> "HybridSlashCommand":
            nonlocal sub_cmd_name, sub_cmd_description

            if not asyncio.iscoroutinefunction(call):
                raise TypeError("Subcommand must be coroutine")

            if sub_cmd_description is ipy.MISSING:
                sub_cmd_description = call.__doc__ or "No Description Set"
            if sub_cmd_name is ipy.MISSING:
                sub_cmd_name = call.__name__

            return HybridSlashCommand(
                name=self.name,
                description=self.description,
                group_name=group_name or self.group_name,
                group_description=group_description or self.group_description,
                sub_cmd_name=sub_cmd_name,
                sub_cmd_description=sub_cmd_description,
                default_member_permissions=self.default_member_permissions,
                dm_permission=self.dm_permission,
                options=options,
                callback=call,
                scopes=self.scopes,
                nsfw=nsfw,
                checks=self.checks if inherit_checks else [],
            )

        return wrapper


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class _HybridToPrefixedCommand(prefixed.PrefixedCommand):
    async def __call__(
        self, context: prefixed.PrefixedContext, *args, **kwargs
    ) -> None:
        new_ctx = context.client.hybrid.hybrid_context.from_prefixed_context(context)
        await super().__call__(new_ctx, *args, **kwargs)


def slash_to_prefixed(cmd: ipy.SlashCommand) -> _HybridToPrefixedCommand:
    prefixed_cmd = _HybridToPrefixedCommand(
        name=str(cmd.sub_cmd_name) if cmd.is_subcommand else str(cmd.name),
        aliases=list(_values_wrapper(cmd.sub_cmd_name.to_locale_dict()))
        if cmd.is_subcommand
        else list(_values_wrapper(cmd.name.to_locale_dict())),
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
        if isinstance(option, dict):
            # makes my life easier
            option = ipy.SlashCommandOption(**option)

        if option.autocomplete:
            # there isn't much we can do here
            raise ValueError("Cannot use autocomplete in hybrid commands.")

        name = str(option.name)
        annotation = inspect.Parameter.empty
        default = inspect.Parameter.empty

        if slash_param := cmd.parameters.get(name):
            if slash_param.converter:
                annotation = slash_param.converter
            if slash_param.default is not ipy.MISSING:
                default = slash_param.default

        if option.choices:
            option_anno = ChoicesConverter(option.choices)
        elif option.min_value is not None or option.max_value is not None:
            option_anno = RangeConverter(
                option.type, option.min_value, option.max_value
            )
        elif option.min_length is not None or option.max_length is not None:
            option_anno = StringLengthConverter(option.min_length, option.max_length)
        elif option.type == ipy.OptionType.CHANNEL and option.channel_types:
            option_anno = NarrowedChannelConverter(option.channel_types)
        else:
            option_anno = type_from_option(option.type)

        if annotation is inspect.Parameter.empty:
            annotation = option_anno
        elif isinstance(option_anno, ipy.NoArgumentConverter):
            annotation = ChainNoArgConverter(option_anno, annotation, name)
        else:
            annotation = ChainConverter(option_anno, annotation, name)

        if not option.required and default == inspect.Parameter.empty:
            default = None

        actual_param = inspect.Parameter(
            name=name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=default,
            annotation=annotation,
        )
        fake_sig_parameters.append(actual_param)

    prefixed_cmd._inspect_signature = inspect.Signature(parameters=fake_sig_parameters)
    return prefixed_cmd


def create_subcmd_func(group: bool = False) -> typing.Callable:
    async def _subcommand_base(*args, **kwargs) -> None:
        if group:
            raise ipy.errors.BadArgument(
                "Cannot run this subcommand group without a valid subcommand."
            )
        else:
            raise ipy.errors.BadArgument(
                "Cannot run this command without a valid subcommand."
            )

    return _subcommand_base


def base_subcommand_generator(
    name: str, aliases: list[str], description: str, group: bool = False
) -> _HybridToPrefixedCommand:
    return _HybridToPrefixedCommand(
        callback=create_subcmd_func(group=group),
        name=name,
        aliases=aliases,
        help=description,
        ignore_extra=False,
        inspect_signature=inspect.Signature(None),  # type: ignore
    )


def hybrid_slash_command(
    name: ipy.Absent[str | ipy.LocalisedName] = ipy.MISSING,
    *,
    description: ipy.Absent[str | ipy.LocalisedDesc] = ipy.MISSING,
    scopes: ipy.Absent[list["ipy.Snowflake_Type"]] = ipy.MISSING,
    options: typing.Optional[
        list[typing.Union[ipy.SlashCommandOption, typing.Dict]]
    ] = None,
    default_member_permissions: typing.Optional["ipy.Permissions"] = None,
    dm_permission: bool = True,
    sub_cmd_name: str | ipy.LocalisedName = None,
    group_name: str | ipy.LocalisedName = None,
    sub_cmd_description: str | ipy.LocalisedDesc = "No Description Set",
    group_description: str | ipy.LocalisedDesc = "No Description Set",
    nsfw: bool = False,
) -> typing.Callable[[ipy.const.AsyncCallable], HybridSlashCommand]:
    """
    A decorator to declare a coroutine as a hybrid slash command.

    Hybrid commands are a slash command that can also function as a prefixed command.
    These use a HybridContext instead of an SlashContext, but otherwise are mostly identical to normal slash commands.

    Note that hybrid commands do not support autocompletes.
    They also only partially support attachments, allowing one attachment option for a command.

    !!! note
        While the base and group descriptions arent visible in the discord client, currently.
        We strongly advise defining them anyway, if you're using subcommands, as Discord has said they will be visible in
        one of the future ui updates.

    Args:
        name: 1-32 character name of the command, defaults to the name of the coroutine.
        description: 1-100 character description of the command
        scopes: The scope this command exists within
        options: The parameters for the command, max 25
        default_member_permissions: What permissions members need to have by default to use this command.
        dm_permission: Should this command be available in DMs.
        sub_cmd_name: 1-32 character name of the subcommand
        sub_cmd_description: 1-100 character description of the subcommand
        group_name: 1-32 character name of the group
        group_description: 1-100 character description of the group
        nsfw: This command should only work in NSFW channels

    Returns:
        HybridSlashCommand Object

    """

    def wrapper(func: ipy.const.AsyncCallable) -> HybridSlashCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        perm = default_member_permissions
        if hasattr(func, "default_member_permissions"):
            if perm:
                perm = perm | func.default_member_permissions
            else:
                perm = func.default_member_permissions

        _name = name
        if _name is ipy.MISSING:
            _name = func.__name__

        _description = description
        if _description is ipy.MISSING:
            _description = func.__doc__ or "No Description Set"

        cmd = HybridSlashCommand(
            name=_name,
            group_name=group_name,
            group_description=group_description,
            sub_cmd_name=sub_cmd_name,
            sub_cmd_description=sub_cmd_description,
            description=_description,
            scopes=scopes or [ipy.const.GLOBAL_SCOPE],
            default_member_permissions=perm,
            dm_permission=dm_permission,
            callback=func,
            options=options,
            nsfw=nsfw,
        )

        return cmd

    return wrapper


def hybrid_slash_subcommand(
    base: str | ipy.LocalisedName,
    *,
    subcommand_group: typing.Optional[str | ipy.LocalisedName] = None,
    name: ipy.Absent[str | ipy.LocalisedName] = ipy.MISSING,
    description: ipy.Absent[str | ipy.LocalisedDesc] = ipy.MISSING,
    base_description: typing.Optional[str | ipy.LocalisedDesc] = None,
    base_desc: typing.Optional[str | ipy.LocalisedDesc] = None,
    base_default_member_permissions: typing.Optional["ipy.Permissions"] = None,
    base_dm_permission: bool = True,
    subcommand_group_description: typing.Optional[str | ipy.LocalisedDesc] = None,
    sub_group_desc: typing.Optional[str | ipy.LocalisedDesc] = None,
    scopes: typing.List["ipy.Snowflake_Type"] = None,
    options: typing.List[dict] = None,
    nsfw: bool = False,
) -> typing.Callable[[ipy.const.AsyncCallable], HybridSlashCommand]:
    """
    A decorator specifically tailored for creating hybrid slash subcommands.

    Args:
        base: The name of the base command
        subcommand_group: The name of the subcommand group, if any.
        name: The name of the subcommand, defaults to the name of the coroutine.
        description: The description of the subcommand
        base_description: The description of the base command
        base_desc: An alias of `base_description`
        base_default_member_permissions: What permissions members need to have by default to use this command.
        base_dm_permission: Should this command be available in DMs.
        subcommand_group_description: Description of the subcommand group
        sub_group_desc: An alias for `subcommand_group_description`
        scopes: The scopes of which this command is available, defaults to GLOBAL_SCOPE
        options: The options for this command
        nsfw: This command should only work in NSFW channels

    Returns:
        A HybridSlashCommand object

    """

    def wrapper(func: ipy.const.AsyncCallable) -> HybridSlashCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        _name = name
        if _name is ipy.MISSING:
            _name = func.__name__

        _description = description
        if _description is ipy.MISSING:
            _description = func.__doc__ or "No Description Set"

        cmd = HybridSlashCommand(
            name=base,
            description=(base_description or base_desc) or "No Description Set",
            group_name=subcommand_group,
            group_description=(subcommand_group_description or sub_group_desc)
            or "No Description Set",
            sub_cmd_name=_name,
            sub_cmd_description=_description,
            default_member_permissions=base_default_member_permissions,
            dm_permission=base_dm_permission,
            scopes=scopes or [ipy.const.GLOBAL_SCOPE],
            callback=func,
            options=options,
            nsfw=nsfw,
        )
        return cmd

    return wrapper
