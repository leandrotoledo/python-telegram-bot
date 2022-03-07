#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2022
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains the PicklePersistence class."""
import copyreg
import pickle
from copy import deepcopy
from pathlib import Path
from sys import version_info as py_ver
from typing import (
    Any,
    Dict,
    Optional,
    Tuple,
    overload,
    cast,
    Type,
    Set,
    Callable,
    TypeVar,
)

from telegram import Bot, TelegramObject
from telegram._utils.types import FilePathInput
from telegram._utils.warnings import warn
from telegram.ext import BasePersistence, PersistenceInput
from telegram.ext._contexttypes import ContextTypes
from telegram.ext._utils.types import UD, CD, BD, ConversationDict, CDCData


_REPLACED_KNOWN_BOT = "a known bot replaced by PTB's PicklePersistence"
_REPLACED_UNKNOWN_BOT = "an unknown bot replaced by PTB's PicklePersistence"

TO = TypeVar('TO', bound=TelegramObject)


def _all_subclasses(cls: Type[TO]) -> Set[Type[TO]]:
    """Gets all subclasses of the specified object, recursively. from
    https://stackoverflow.com/a/3862957/9706202
    """
    subclasses = cls.__subclasses__()
    return set(subclasses).union([s for c in subclasses for s in _all_subclasses(c)])


def _reconstruct_to(cls: Type[TO], kwargs: dict) -> TO:
    """
    This method is used for unpickling. The data, which is in the form a dictionary, is
    converted back into a class. Functions the same as :meth:`TelegramObject.__setstate__`.
    This function should be kept in place for backwards compatibility even if the pickling logic
    is changed, since `_custom_reduction` places references to this function into the pickled data.
    """
    bot = kwargs.pop('_bot', None)
    obj = cls.__new__(cls)
    for key, val in kwargs.items():
        setattr(obj, key, val)
    obj.set_bot(bot)
    return obj  # type: ignore[return-value]


def _custom_reduction(cls: TO) -> Tuple[Callable, Tuple[Type[TO], dict]]:
    """
    This method is used for pickling. The bot attribute is preserved so _BotPickler().persistent_id
    works as intended.
    """
    data = cls._get_attrs(include_private=True)  # pylint: disable=protected-access
    return _reconstruct_to, (cls.__class__, data)


class _BotPickler(pickle.Pickler):
    __slots__ = ('_bot',)

    def __init__(self, bot: Bot, *args: Any, **kwargs: Any):
        self._bot = bot
        # Here we define a private dispatch_table, because we want to preserve the bot attribute of
        # objects so persistent_id works as intended. Otherwise, the bot attribute is deleted in
        # __getstate__, which is used during regular pickling (via pickle.dumps(...))
        if py_ver < (3, 8):  # self.reducer_override is used above this version
            self.dispatch_table = copyreg.dispatch_table.copy()  # type: ignore[attr-defined]
            for obj in _all_subclasses(TelegramObject):
                self.dispatch_table[obj] = _custom_reduction  # type: ignore[index]
        super().__init__(*args, **kwargs)

    def reducer_override(  # pylint: disable=no-self-use
        self, obj: TO
    ) -> Tuple[Callable, Tuple[Type[TO], dict]]:
        if not isinstance(obj, TelegramObject):
            return NotImplemented

        return _custom_reduction(obj)

    def persistent_id(self, obj: object) -> Optional[str]:
        """Used to 'mark' the Bot, so it can be replaced later. See
        https://docs.python.org/3/library/pickle.html#pickle.Pickler.persistent_id for more info
        """
        if obj is self._bot:
            return _REPLACED_KNOWN_BOT
        if isinstance(obj, Bot):
            warn(
                'Unknown bot instance found. Will be replaced by `None` during unpickling',
                stacklevel=7,
            )
            return _REPLACED_UNKNOWN_BOT
        return None  # pickles as usual


class _BotUnpickler(pickle.Unpickler):
    __slots__ = ('_bot',)

    def __init__(self, bot: Bot, *args: Any, **kwargs: Any):
        self._bot = bot
        super().__init__(*args, **kwargs)

    def persistent_load(self, pid: str) -> Optional[Bot]:
        """Replaces the bot with the current bot if known, else it is replaced by :obj:`None`."""
        return self._bot if pid == _REPLACED_KNOWN_BOT else None


class PicklePersistence(BasePersistence[UD, CD, BD]):
    """Using python's builtin pickle for making your bot persistent.

    Attention:
        The interface provided by this class is intended to be accessed exclusively by
        :class:`~telegram.ext.Dispatcher`. Calling any of the methods below manually might
        interfere with the integration of persistence into :class:`~telegram.ext.Dispatcher`.

    Note:
        This implementation of :class:`BasePersistence` uses the functionality of the pickle module
        to support serialization of bot instances. Specifically any reference to
        :attr:`~BasePersistence.bot` will be replaced by a placeholder before pickling and
        :attr:`~BasePersistence.bot` will be inserted back when loading the data.

    .. versionchanged:: 14.0

        * The parameters and attributes ``store_*_data`` were replaced by :attr:`store_data`.
        * The parameter and attribute ``filename`` were replaced by :attr:`filepath`.
        * :attr:`filepath` now also accepts :obj:`pathlib.Path` as argument.

    Args:
        filepath (:obj:`str` | :obj:`pathlib.Path`): The filepath for storing the pickle files.
            When :attr:`single_file` is :obj:`False` this will be used as a prefix.
        store_data (:class:`PersistenceInput`, optional): Specifies which kinds of data will be
            saved by this persistence instance. By default, all available kinds of data will be
            saved.
        single_file (:obj:`bool`, optional): When :obj:`False` will store 5 separate files of
            `filename_user_data`, `filename_bot_data`, `filename_chat_data`,
            `filename_callback_data` and `filename_conversations`. Default is :obj:`True`.
        on_flush (:obj:`bool`, optional): When :obj:`True` will only save to file when
            :meth:`flush` is called and keep data in memory until that happens. When
            :obj:`False` will store data on any transaction *and* on call to :meth:`flush`.
            Default is :obj:`False`.
        context_types (:class:`telegram.ext.ContextTypes`, optional): Pass an instance
            of :class:`telegram.ext.ContextTypes` to customize the types used in the
            ``context`` interface. If not passed, the defaults documented in
            :class:`telegram.ext.ContextTypes` will be used.

            .. versionadded:: 13.6

    Attributes:
        filepath (:obj:`str` | :obj:`pathlib.Path`): The filepath for storing the pickle files.
            When :attr:`single_file` is :obj:`False` this will be used as a prefix.
        store_data (:class:`PersistenceInput`): Specifies which kinds of data will be saved by this
            persistence instance.
        single_file (:obj:`bool`): Optional. When :obj:`False` will store 5 separate files of
            `filename_user_data`, `filename_bot_data`, `filename_chat_data`,
            `filename_callback_data` and `filename_conversations`. Default is :obj:`True`.
        on_flush (:obj:`bool`, optional): When :obj:`True` will only save to file when
            :meth:`flush` is called and keep data in memory until that happens. When
            :obj:`False` will store data on any transaction *and* on call to :meth:`flush`.
            Default is :obj:`False`.
        context_types (:class:`telegram.ext.ContextTypes`): Container for the types used
            in the ``context`` interface.

            .. versionadded:: 13.6
    """

    __slots__ = (
        'filepath',
        'single_file',
        'on_flush',
        'user_data',
        'chat_data',
        'bot_data',
        'callback_data',
        'conversations',
        'context_types',
    )

    @overload
    def __init__(
        self: 'PicklePersistence[Dict, Dict, Dict]',
        filepath: FilePathInput,
        store_data: PersistenceInput = None,
        single_file: bool = True,
        on_flush: bool = False,
    ):
        ...

    @overload
    def __init__(
        self: 'PicklePersistence[UD, CD, BD]',
        filepath: FilePathInput,
        store_data: PersistenceInput = None,
        single_file: bool = True,
        on_flush: bool = False,
        context_types: ContextTypes[Any, UD, CD, BD] = None,
    ):
        ...

    def __init__(
        self,
        filepath: FilePathInput,
        store_data: PersistenceInput = None,
        single_file: bool = True,
        on_flush: bool = False,
        context_types: ContextTypes[Any, UD, CD, BD] = None,
    ):
        super().__init__(store_data=store_data)
        self.filepath = Path(filepath)
        self.single_file = single_file
        self.on_flush = on_flush
        self.user_data: Optional[Dict[int, UD]] = None
        self.chat_data: Optional[Dict[int, CD]] = None
        self.bot_data: Optional[BD] = None
        self.callback_data: Optional[CDCData] = None
        self.conversations: Optional[Dict[str, Dict[Tuple, object]]] = None
        self.context_types = cast(ContextTypes[Any, UD, CD, BD], context_types or ContextTypes())

    def _load_singlefile(self) -> None:
        try:
            with self.filepath.open("rb") as file:
                data = _BotUnpickler(self.bot, file).load()

            self.user_data = data['user_data']
            self.chat_data = data['chat_data']
            # For backwards compatibility with files not containing bot data
            self.bot_data = data.get('bot_data', self.context_types.bot_data())
            self.callback_data = data.get('callback_data', {})
            self.conversations = data['conversations']
        except OSError:
            self.conversations = {}
            self.user_data = {}
            self.chat_data = {}
            self.bot_data = self.context_types.bot_data()
            self.callback_data = None
        except pickle.UnpicklingError as exc:
            filename = self.filepath.name
            raise TypeError(f"File {filename} does not contain valid pickle data") from exc
        except Exception as exc:
            raise TypeError(f"Something went wrong unpickling {self.filepath.name}") from exc

    def _load_file(self, filepath: Path) -> Any:
        try:
            with filepath.open("rb") as file:
                return _BotUnpickler(self.bot, file).load()

        except OSError:
            return None
        except pickle.UnpicklingError as exc:
            raise TypeError(f"File {filepath.name} does not contain valid pickle data") from exc
        except Exception as exc:
            raise TypeError(f"Something went wrong unpickling {filepath.name}") from exc

    def _dump_singlefile(self) -> None:
        data = {
            'conversations': self.conversations,
            'user_data': self.user_data,
            'chat_data': self.chat_data,
            'bot_data': self.bot_data,
            'callback_data': self.callback_data,
        }
        with self.filepath.open("wb") as file:
            _BotPickler(self.bot, file, protocol=pickle.HIGHEST_PROTOCOL).dump(data)

    def _dump_file(self, filepath: Path, data: object) -> None:
        with filepath.open("wb") as file:
            _BotPickler(self.bot, file, protocol=pickle.HIGHEST_PROTOCOL).dump(data)

    def get_user_data(self) -> Dict[int, UD]:
        """Returns the user_data from the pickle file if it exists or an empty :obj:`dict`.

        Returns:
            Dict[:obj:`int`, :obj:`dict`]: The restored user data.
        """
        if self.user_data:
            pass
        elif not self.single_file:
            data = self._load_file(Path(f"{self.filepath}_user_data"))
            if not data:
                data = {}
            self.user_data = data
        else:
            self._load_singlefile()
        return deepcopy(self.user_data)  # type: ignore[arg-type]

    def get_chat_data(self) -> Dict[int, CD]:
        """Returns the chat_data from the pickle file if it exists or an empty :obj:`dict`.

        Returns:
            Dict[:obj:`int`, :obj:`dict`]: The restored chat data.
        """
        if self.chat_data:
            pass
        elif not self.single_file:
            data = self._load_file(Path(f"{self.filepath}_chat_data"))
            if not data:
                data = {}
            self.chat_data = data
        else:
            self._load_singlefile()
        return deepcopy(self.chat_data)  # type: ignore[arg-type]

    def get_bot_data(self) -> BD:
        """Returns the bot_data from the pickle file if it exists or an empty object of type
        :obj:`dict` | :attr:`telegram.ext.ContextTypes.bot_data`.

        Returns:
            :obj:`dict` | :attr:`telegram.ext.ContextTypes.bot_data`: The restored bot data.
        """
        if self.bot_data:
            pass
        elif not self.single_file:
            data = self._load_file(Path(f"{self.filepath}_bot_data"))
            if not data:
                data = self.context_types.bot_data()
            self.bot_data = data
        else:
            self._load_singlefile()
        return deepcopy(self.bot_data)  # type: ignore[return-value]

    def get_callback_data(self) -> Optional[CDCData]:
        """Returns the callback data from the pickle file if it exists or :obj:`None`.

        .. versionadded:: 13.6

        Returns:
            Optional[Tuple[List[Tuple[:obj:`str`, :obj:`float`, \
                Dict[:obj:`str`, :class:`object`]]], Dict[:obj:`str`, :obj:`str`]]]:
                The restored metadata or :obj:`None`, if no data was stored.
        """
        if self.callback_data:
            pass
        elif not self.single_file:
            data = self._load_file(Path(f"{self.filepath}_callback_data"))
            if not data:
                data = None
            self.callback_data = data
        else:
            self._load_singlefile()
        if self.callback_data is None:
            return None
        return deepcopy((self.callback_data[0], self.callback_data[1].copy()))

    def get_conversations(self, name: str) -> ConversationDict:
        """Returns the conversations from the pickle file if it exists or an empty dict.

        Args:
            name (:obj:`str`): The handlers name.

        Returns:
            :obj:`dict`: The restored conversations for the handler.
        """
        if self.conversations:
            pass
        elif not self.single_file:
            data = self._load_file(Path(f"{self.filepath}_conversations"))
            if not data:
                data = {name: {}}
            self.conversations = data
        else:
            self._load_singlefile()
        return self.conversations.get(name, {}).copy()  # type: ignore[union-attr]

    def update_conversation(
        self, name: str, key: Tuple[int, ...], new_state: Optional[object]
    ) -> None:
        """Will update the conversations for the given handler and depending on :attr:`on_flush`
        save the pickle file.

        Args:
            name (:obj:`str`): The handler's name.
            key (:obj:`tuple`): The key the state is changed for.
            new_state (:obj:`tuple` | :class:`object`): The new state for the given key.
        """
        if not self.conversations:
            self.conversations = {}
        if self.conversations.setdefault(name, {}).get(key) == new_state:
            return
        self.conversations[name][key] = new_state
        if not self.on_flush:
            if not self.single_file:
                self._dump_file(Path(f"{self.filepath}_conversations"), self.conversations)
            else:
                self._dump_singlefile()

    def update_user_data(self, user_id: int, data: UD) -> None:
        """Will update the user_data and depending on :attr:`on_flush` save the pickle file.

        Args:
            user_id (:obj:`int`): The user the data might have been changed for.
            data (:obj:`dict`): The :attr:`telegram.ext.Dispatcher.user_data` ``[user_id]``.
        """
        if self.user_data is None:
            self.user_data = {}
        if self.user_data.get(user_id) == data:
            return
        self.user_data[user_id] = deepcopy(data)
        if not self.on_flush:
            if not self.single_file:
                self._dump_file(Path(f"{self.filepath}_user_data"), self.user_data)
            else:
                self._dump_singlefile()

    def update_chat_data(self, chat_id: int, data: CD) -> None:
        """Will update the chat_data and depending on :attr:`on_flush` save the pickle file.

        Args:
            chat_id (:obj:`int`): The chat the data might have been changed for.
            data (:obj:`dict`): The :attr:`telegram.ext.Dispatcher.chat_data` ``[chat_id]``.
        """
        if self.chat_data is None:
            self.chat_data = {}
        if self.chat_data.get(chat_id) == data:
            return
        self.chat_data[chat_id] = deepcopy(data)
        if not self.on_flush:
            if not self.single_file:
                self._dump_file(Path(f"{self.filepath}_chat_data"), self.chat_data)
            else:
                self._dump_singlefile()

    def update_bot_data(self, data: BD) -> None:
        """Will update the bot_data and depending on :attr:`on_flush` save the pickle file.

        Args:
            data (:obj:`dict` | :attr:`telegram.ext.ContextTypes.bot_data`): The
                :attr:`telegram.ext.Dispatcher.bot_data`.
        """
        if self.bot_data == data:
            return
        self.bot_data = deepcopy(data)
        if not self.on_flush:
            if not self.single_file:
                self._dump_file(Path(f"{self.filepath}_bot_data"), self.bot_data)
            else:
                self._dump_singlefile()

    def update_callback_data(self, data: CDCData) -> None:
        """Will update the callback_data (if changed) and depending on :attr:`on_flush` save the
        pickle file.

        .. versionadded:: 13.6

        Args:
            data (Tuple[List[Tuple[:obj:`str`, :obj:`float`, \
                Dict[:obj:`str`, :class:`object`]]], Dict[:obj:`str`, :obj:`str`]]):
                The relevant data to restore :class:`telegram.ext.CallbackDataCache`.
        """
        if self.callback_data == data:
            return
        self.callback_data = deepcopy((data[0], data[1].copy()))
        if not self.on_flush:
            if not self.single_file:
                self._dump_file(Path(f"{self.filepath}_callback_data"), self.callback_data)
            else:
                self._dump_singlefile()

    def drop_chat_data(self, chat_id: int) -> None:
        """Will delete the specified key from the ``chat_data`` and depending on
        :attr:`on_flush` save the pickle file.

        .. versionadded:: 14.0

        Args:
            chat_id (:obj:`int`): The chat id to delete from the persistence.
        """
        if self.chat_data is None:
            return
        self.chat_data.pop(chat_id, None)  # type: ignore[arg-type]

        if not self.on_flush:
            if not self.single_file:
                self._dump_file(Path(f"{self.filepath}_chat_data"), self.chat_data)
            else:
                self._dump_singlefile()

    def drop_user_data(self, user_id: int) -> None:
        """Will delete the specified key from the ``user_data`` and depending on
        :attr:`on_flush` save the pickle file.

        .. versionadded:: 14.0

        Args:
            user_id (:obj:`int`): The user id to delete from the persistence.
        """
        if self.user_data is None:
            return
        self.user_data.pop(user_id, None)  # type: ignore[arg-type]

        if not self.on_flush:
            if not self.single_file:
                self._dump_file(Path(f"{self.filepath}_user_data"), self.user_data)
            else:
                self._dump_singlefile()

    def refresh_user_data(self, user_id: int, user_data: UD) -> None:
        """Does nothing.

        .. versionadded:: 13.6
        .. seealso:: :meth:`telegram.ext.BasePersistence.refresh_user_data`
        """

    def refresh_chat_data(self, chat_id: int, chat_data: CD) -> None:
        """Does nothing.

        .. versionadded:: 13.6
        .. seealso:: :meth:`telegram.ext.BasePersistence.refresh_chat_data`
        """

    def refresh_bot_data(self, bot_data: BD) -> None:
        """Does nothing.

        .. versionadded:: 13.6
        .. seealso:: :meth:`telegram.ext.BasePersistence.refresh_bot_data`
        """

    def flush(self) -> None:
        """Will save all data in memory to pickle file(s)."""
        if self.single_file:
            if (
                self.user_data
                or self.chat_data
                or self.bot_data
                or self.callback_data
                or self.conversations
            ):
                self._dump_singlefile()
        else:
            if self.user_data:
                self._dump_file(Path(f"{self.filepath}_user_data"), self.user_data)
            if self.chat_data:
                self._dump_file(Path(f"{self.filepath}_chat_data"), self.chat_data)
            if self.bot_data:
                self._dump_file(Path(f"{self.filepath}_bot_data"), self.bot_data)
            if self.callback_data:
                self._dump_file(Path(f"{self.filepath}_callback_data"), self.callback_data)
            if self.conversations:
                self._dump_file(Path(f"{self.filepath}_conversations"), self.conversations)
