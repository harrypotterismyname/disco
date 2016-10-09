import six

from holster.enum import Enum

from disco.util.snowflake import to_snowflake
from disco.util.functional import cached_property, one_or_many, chunks
from disco.types.user import User
from disco.types.base import Model, Field, snowflake, enum, listof, dictof, text
from disco.types.permissions import Permissions, Permissible, PermissionValue
from disco.voice.client import VoiceClient


ChannelType = Enum(
    GUILD_TEXT=0,
    DM=1,
    GUILD_VOICE=2,
    GROUP_DM=3,
)

PermissionOverwriteType = Enum(
    ROLE='role',
    MEMBER='member'
)


class PermissionOverwrite(Model):
    """
    A PermissionOverwrite for a :class:`Channel`


    Attributes
    ----------
    id : snowflake
        The overwrite ID
    type : :const:`disco.types.channel.PermissionsOverwriteType`
        The overwrite type
    allowed : :class:`PermissionValue`
        All allowed permissions
    denied : :class:`PermissionValue`
        All denied permissions
    """

    id = Field(snowflake)
    type = Field(enum(PermissionOverwriteType))
    allow = Field(PermissionValue)
    deny = Field(PermissionValue)

    def save(self):
        return self.channel.update_overwrite(self)

    def delete(self):
        return self.channel.delete_overwrite(self)


class Channel(Model, Permissible):
    """
    Represents a Discord Channel

    Attributes
    ----------
    id : snowflake
        The channel ID.
    guild_id : Optional[snowflake]
        The guild id this channel is part of.
    name : str
        The channels name.
    topic : str
        The channels topic.
    position : int
        The channels position.
    bitrate : int
        The channels bitrate.
    recipients: list(:class:`disco.types.user.User`)
        Members of this channel (if this is a DM channel).
    type : :const:`ChannelType`
        The type of this channel.
    overwrites : dict(snowflake, :class:`disco.types.channel.PermissionOverwrite`)
        Channel permissions overwrites.
    """
    id = Field(snowflake)
    guild_id = Field(snowflake)
    name = Field(text)
    topic = Field(text)
    last_message_id = Field(snowflake)
    position = Field(int)
    bitrate = Field(int)
    recipients = Field(listof(User))
    type = Field(enum(ChannelType))
    overwrites = Field(dictof(PermissionOverwrite, key='id'), alias='permission_overwrites')

    def __init__(self, *args, **kwargs):
        super(Channel, self).__init__(*args, **kwargs)

        self.attach(six.itervalues(self.overwrites), {'channel_id': self.id, 'channel': self})

    def get_permissions(self, user):
        """
        Get the permissions a user has in the channel

        Returns
        -------
        :class:`disco.types.permissions.PermissionValue`
            Computed permission value for the user.
        """
        if not self.guild_id:
            return Permissions.ADMINISTRATOR

        member = self.guild.members.get(user.id)
        base = self.guild.get_permissions(user)

        for ow in six.itervalues(self.overwrites):
            if ow.id != user.id and ow.id not in member.roles:
                continue

            base -= ow.deny
            base += ow.allow

        return base

    @property
    def is_guild(self):
        """
        Whether this channel belongs to a guild
        """
        return self.type in (ChannelType.GUILD_TEXT, ChannelType.GUILD_VOICE)

    @property
    def is_dm(self):
        """
        Whether this channel is a DM (does not belong to a guild)
        """
        return self.type in (ChannelType.DM, ChannelType.GROUP_DM)

    @property
    def is_voice(self):
        """
        Whether this channel supports voice
        """
        return self.type in (ChannelType.GUILD_VOICE, ChannelType.GROUP_DM)

    @property
    def messages(self):
        """
        a default :class:`MessageIterator` for the channel
        """
        return self.messages_iter()

    def messages_iter(self, **kwargs):
        """
        Creates a new :class:`MessageIterator` for the channel with the given
        keyword arguments
        """
        return MessageIterator(self.client, self.id, **kwargs)

    @cached_property
    def guild(self):
        """
        Guild this channel belongs to (if relevant)
        """
        return self.client.state.guilds.get(self.guild_id)

    def get_invites(self):
        """
        Returns
        -------
        list(:class:`disco.types.invite.Invite`)
            All invites for this channel.
        """
        return self.client.api.channels_invites_list(self.id)

    def get_pins(self):
        """
        Returns
        -------
        list(:class:`disco.types.message.Message`)
            All pinned messages for this channel.
        """
        return self.client.api.channels_pins_list(self.id)

    def send_message(self, content, nonce=None, tts=False):
        """
        Send a message in this channel

        Parameters
        ----------
        content : str
            The message contents to send.
        nonce : Optional[snowflake]
            The nonce to attach to the message.
        tts : Optional[bool]
            Whether this is a TTS message.

        Returns
        -------
        :class:`disco.types.message.Message`
            The created message.
        """
        return self.client.api.channels_messages_create(self.id, content, nonce, tts)

    def connect(self, *args, **kwargs):
        """
        Connect to this channel over voice
        """
        assert self.is_voice, 'Channel must support voice to connect'
        vc = VoiceClient(self)
        vc.connect(*args, **kwargs)
        return vc

    def create_overwrite(self, entity, allow=0, deny=0):
        from disco.types.guild import Role

        type = PermissionOverwriteType.ROLE if isinstance(entity, Role) else PermissionOverwriteType.MEMBER
        ow = PermissionOverwrite(
            id=entity.id,
            type=type,
            allow=allow,
            deny=deny
        )

        ow.channel_id = self.id
        ow.channel = self

        return self.update_overwrite(ow)

    def update_overwrite(self, ow):
        self.client.api.channels_permissions_modify(self.id,
            ow.id,
            ow.allow.value if ow.allow else 0,
            ow.deny.value if ow.deny else 0,
            ow.type.name)
        return ow

    def delete_overwrite(self, ow):
        self.client.api.channels_permissions_delete(self.id, ow.id)

    def delete_message(self, message):
        """
        Deletes a single message from this channel.

        Args
        ----
        message : snowflake|:class:`disco.types.message.Message`
            The message to delete.
        """
        self.client.api.channels_messages_delete(self.id, to_snowflake(message))

    @one_or_many
    def delete_messages(self, messages):
        """
        Deletes a set of messages using the correct API route based on the number
        of messages passed.

        Args
        ----
        messages : list[snowflake|:class:`disco.types.message.Message`]
            List of messages (or message ids) to delete. All messages must originate
            from this channel.
        """
        messages = map(to_snowflake, messages)

        if not messages:
            return

        if len(messages) <= 2:
            for msg in messages:
                self.delete_message(msg)
        else:
            for chunk in chunks(messages, 100):
                self.client.api.channels_messages_delete_bulk(self.id, chunk)


class MessageIterator(object):
    """
    An iterator which supports scanning through the messages for a channel.

    Parameters
    ----------
    client : :class:`disco.client.Client`
        The disco client instance to use when making requests.
    channel : `Channel`
        The channel to iterate within.
    direction : :attr:`MessageIterator.Direction`
        The direction in which this iterator will move.
    bulk : bool
        If true, this iterator will yield messages in list batches, otherwise each
        message will be yield individually.
    before : snowflake
        The message to begin scanning at.
    after : snowflake
        The message to begin scanning at.
    chunk_size : int
        The number of messages to request per API call.
    """
    Direction = Enum('UP', 'DOWN')

    def __init__(self, client, channel, direction=Direction.UP, bulk=False, before=None, after=None, chunk_size=100):
        self.client = client
        self.channel = channel
        self.direction = direction
        self.bulk = bulk
        self.before = before
        self.after = after
        self.chunk_size = chunk_size

        self.last = None
        self._buffer = []

        if not any((before, after)) and self.direction == self.Direction.DOWN:
            raise Exception('Must specify either before or after for downward seeking')

    def fill(self):
        """
        Fills the internal buffer up with :class:`disco.types.message.Message` objects from the API
        """
        self._buffer = self.client.api.channels_messages_list(
                self.channel,
                before=self.before,
                after=self.after,
                limit=self.chunk_size)

        if not len(self._buffer):
            raise StopIteration

        self.after = None
        self.before = None

        if self.direction == self.Direction.UP:
            self.before = self._buffer[-1].id
        else:
            self._buffer.reverse()
            self.after == self._buffer[-1].id

    def next(self):
        return self.__next__()

    def __iter__(self):
        return self

    def __next__(self):
        if not len(self._buffer):
            self.fill()

        if self.bulk:
            res = self._buffer
            self._buffer = []
            return res
        else:
            return self._buffer.pop()
