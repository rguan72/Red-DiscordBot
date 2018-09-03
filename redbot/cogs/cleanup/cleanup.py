import re
from datetime import datetime, timedelta
from typing import Union, List, Callable

import discord

from redbot.core import checks, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.mod import slow_deletion, mass_purge
from redbot.cogs.mod.log import log

_ = Translator("Cleanup", __file__)


@cog_i18n(_)
class Cleanup:
    """Commands for cleaning messages"""

    def __init__(self, bot: Red):
        self.bot = bot

    @staticmethod
    async def check_100_plus(ctx: commands.Context, number: int) -> bool:
        """
        Called when trying to delete more than 100 messages at once.

        Prompts the user to choose whether they want to continue or not.

        Tries its best to cleanup after itself if the response is positive.
        """

        def author_check(message):
            return message.author == ctx.author

        prompt = await ctx.send(
            _("Are you sure you want to delete {} messages? (y/n)").format(number)
        )
        response = await ctx.bot.wait_for("message", check=author_check)

        if response.content.lower().startswith("y"):
            await prompt.delete()
            try:
                await response.delete()
            except:
                pass
            return True
        else:
            await ctx.send(_("Cancelled."))
            return False

    @staticmethod
    async def get_messages_for_deletion(
        *,
        channel: discord.TextChannel,
        number: int = None,
        check: Callable[[discord.Message], bool] = lambda x: True,
        before: Union[discord.Message, datetime] = None,
        after: Union[discord.Message, datetime] = None,
        delete_pinned: bool = False,
    ) -> List[discord.Message]:
        """
        Gets a list of messages meeting the requirements to be deleted.
        Generally, the requirements are:
        - We don't have the number of messages to be deleted already
        - The message passes a provided check (if no check is provided,
          this is automatically true)
        - The message is less than 14 days old
        - The message is not pinned

        Warning: Due to the way the API hands messages back in chunks,
        passing after and a number together is not advisable.
        If you need to accomplish this, you should filter messages on
        the entire applicable range, rather than use this utility.
        """

        # This isn't actually two weeks ago to allow some wiggle room on API limits
        two_weeks_ago = datetime.utcnow() - timedelta(days=14, minutes=-5)

        def message_filter(message):
            return (
                check(message)
                and message.created_at > two_weeks_ago
                and (delete_pinned or not message.pinned)
            )

        if after:
            if isinstance(after, discord.Message):
                after = after.created_at
            after = max(after, two_weeks_ago)

        collected = []
        async for message in channel.history(
            limit=None, before=before, after=after, reverse=False
        ):
            if message.created_at < two_weeks_ago:
                break
            if check(message):
                collected.append(message)
                if number and number <= len(collected):
                    break

        return collected

    @commands.group()
    @checks.mod_or_permissions(manage_messages=True)
    async def cleanup(self, ctx: commands.Context):
        """Deletes messages."""
        pass

    @cleanup.command()
    @commands.guild_only()
    async def text(
        self, ctx: commands.Context, text: str, number: int, delete_pinned: bool = False
    ):
        """Deletes last X messages matching the specified text.

        Example:
        cleanup text \"test\" 5

        Remember to use double quotes."""

        channel = ctx.channel
        if not channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("I need the Manage Messages permission to do this.")
            return

        author = ctx.author

        if number > 100:
            cont = await self.check_100_plus(ctx, number)
            if not cont:
                return

        def check(m):
            if text in m.content:
                return True
            elif m == ctx.message:
                return True
            else:
                return False

        to_delete = await self.get_messages_for_deletion(
            channel=channel,
            number=number,
            check=check,
            before=ctx.message,
            delete_pinned=delete_pinned,
        )

        reason = "{}({}) deleted {} messages containing '{}' in channel {}.".format(
            author.name, author.id, len(to_delete), text, channel.id
        )
        log.info(reason)

        await mass_purge(to_delete, channel)

    @cleanup.command()
    @commands.guild_only()
    async def user(
        self, ctx: commands.Context, user: str, number: int, delete_pinned: bool = False
    ):
        """Deletes last X messages from specified user.

        Examples:
        cleanup user @\u200bTwentysix 2
        cleanup user Red 6"""
        channel = ctx.channel
        if not channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("I need the Manage Messages permission to do this.")
            return

        member = None
        try:
            member = await commands.converter.MemberConverter().convert(ctx, user)
        except commands.BadArgument:
            try:
                _id = int(user)
            except ValueError:
                raise commands.BadArgument()
        else:
            _id = member.id

        author = ctx.author

        if number > 100:
            cont = await self.check_100_plus(ctx, number)
            if not cont:
                return

        def check(m):
            if m.author.id == _id:
                return True
            elif m == ctx.message:
                return True
            # else if m is in the alias list, return True
            else:
                return False

        to_delete = await self.get_messages_for_deletion(
            channel=channel,
            number=number,
            check=check,
            before=ctx.message,
            delete_pinned=delete_pinned,
        )
        reason = (
            "{}({}) deleted {} messages "
            " made by {}({}) in channel {}."
            "".format(author.name, author.id, len(to_delete), member or "???", _id, channel.name)
        )
        log.info(reason)

        await mass_purge(to_delete, channel)

    @cleanup.command()
    @commands.guild_only()
    async def after(self, ctx: commands.Context, message_id: int, delete_pinned: bool = False):
        """Deletes all messages after specified message.

        To get a message id, enable developer mode in Discord's
        settings, 'appearance' tab. Then right click a message
        and copy its id.

        This command only works on bots running as bot accounts.
        """

        channel = ctx.channel
        if not channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("I need the Manage Messages permission to do this.")
            return
        author = ctx.author

        try:
            after = await channel.get_message(message_id)
        except discord.NotFound:
            return await ctx.send(_("Message not found."))

        to_delete = await self.get_messages_for_deletion(
            channel=channel, number=None, after=after, delete_pinned=delete_pinned
        )

        reason = "{}({}) deleted {} messages in channel {}.".format(
            author.name, author.id, len(to_delete), channel.name
        )
        log.info(reason)

        await mass_purge(to_delete, channel)

    @cleanup.command()
    @commands.guild_only()
    async def messages(self, ctx: commands.Context, number: int, delete_pinned: bool = False):
        """Deletes last X messages.

        Example:
        cleanup messages 26"""

        channel = ctx.channel
        if not channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("I need the Manage Messages permission to do this.")
            return
        author = ctx.author

        if number > 100:
            cont = await self.check_100_plus(ctx, number)
            if not cont:
                return

        to_delete = await self.get_messages_for_deletion(
            channel=channel, number=number, before=ctx.message, delete_pinned=delete_pinned
        )
        to_delete.append(ctx.message)

        reason = "{}({}) deleted {} messages in channel {}.".format(
            author.name, author.id, number, channel.name
        )
        log.info(reason)

        await mass_purge(to_delete, channel)

    @cleanup.command(name="bot")
    @commands.guild_only()
    async def cleanup_bot(self, ctx: commands.Context, number: int, delete_pinned: bool = False):
        """Cleans up command messages and messages from the bot."""

        channel = ctx.channel
        if not channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("I need the Manage Messages permission to do this.")
            return
        author = ctx.message.author

        if number > 100:
            cont = await self.check_100_plus(ctx, number)
            if not cont:
                return

        prefixes = await self.bot.get_prefix(ctx.message)  # This returns all server prefixes
        if isinstance(prefixes, str):
            prefixes = [prefixes]

        # In case some idiot sets a null prefix
        if "" in prefixes:
            prefixes.remove("")

        def check(m):
            if m.author.id == self.bot.user.id:
                return True
            elif m == ctx.message:
                return True
            p = discord.utils.find(m.content.startswith, prefixes)
            if p and len(p) > 0:
                cmd_name = m.content[len(p) :].split(" ")[0]
                return bool(self.bot.get_command(cmd_name))
            return False
        # jank solution: just import the _del_alias function from alias.py
        # then call it here
        # better idea: Go through the thing that actually deletes the alias and
        # map out what is going on within the code
        to_delete = await self.get_messages_for_deletion(
            channel=channel,
            number=number,
            check=check,
            before=ctx.message,
            delete_pinned=delete_pinned,
        )
        to_delete.append(ctx.message)

        reason = (
            "{}({}) deleted {} "
            " command messages in channel {}."
            "".format(author.name, author.id, len(to_delete), channel.name)
        )
        log.info(reason)

        await mass_purge(to_delete, channel)

    @cleanup.command(name="self")
    async def cleanup_self(
        self,
        ctx: commands.Context,
        number: int,
        match_pattern: str = None,
        delete_pinned: bool = False,
    ):
        """Cleans up messages owned by the bot.

        By default, all messages are cleaned. If a third argument is specified,
        it is used for pattern matching: If it begins with r( and ends with ),
        then it is interpreted as a regex, and messages that match it are
        deleted. Otherwise, it is used in a simple substring test.

        Some helpful regex flags to include in your pattern:
        Dots match newlines: (?s); Ignore case: (?i); Both: (?si)
        """
        channel = ctx.channel
        author = ctx.message.author

        if number > 100:
            cont = await self.check_100_plus(ctx, number)
            if not cont:
                return

        # You can always delete your own messages, this is needed to purge
        can_mass_purge = False
        if type(author) is discord.Member:
            me = ctx.guild.me
            can_mass_purge = channel.permissions_for(me).manage_messages

        use_re = match_pattern and match_pattern.startswith("r(") and match_pattern.endswith(")")

        if use_re:
            match_pattern = match_pattern[1:]  # strip 'r'
            match_re = re.compile(match_pattern)

            def content_match(c):
                return bool(match_re.match(c))

        elif match_pattern:

            def content_match(c):
                return match_pattern in c

        else:

            def content_match(_):
                return True

        def check(m):
            if m.author.id != self.bot.user.id:
                return False
            elif content_match(m.content):
                return True
            return False

        to_delete = await self.get_messages_for_deletion(
            channel=channel,
            number=number,
            check=check,
            before=ctx.message,
            delete_pinned=delete_pinned,
        )

        if ctx.guild:
            channel_name = "channel " + channel.name
        else:
            channel_name = str(channel)

        reason = (
            "{}({}) deleted {} messages "
            "sent by the bot in {}."
            "".format(author.name, author.id, len(to_delete), channel_name)
        )
        log.info(reason)

        if can_mass_purge:
            await mass_purge(to_delete, channel)
        else:
            await slow_deletion(to_delete)
