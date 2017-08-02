#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2017
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
import os
import sys
from collections import defaultdict
from queue import Queue
from threading import Thread, Event

import pytest

from pytests.bots import get_bot
from telegram import Bot
from telegram.ext import Dispatcher

TRAVIS = os.getenv('TRAVIS', False)

if TRAVIS:
    pytest_plugins = ['pytests.travis_fold']


@pytest.fixture(scope='session')
def bot_info():
    return get_bot()


@pytest.fixture(scope='session')
def bot(bot_info):
    return Bot(bot_info['token'])


@pytest.fixture(scope='session')
def chat_id(bot_info):
    return bot_info['chat_id']


@pytest.fixture(scope='session')
def provider_token(bot_info):
    return bot_info['payment_provider_token']


@pytest.fixture(scope='session')
def _dp(bot):
    # Dispatcher is heavy to init (due to many threads and such) so we have a single session
    # scoped one here, but before each test, reset it (dp fixture below)
    dispatcher = Dispatcher(bot, Queue(), workers=2)
    thr = Thread(target=dispatcher.start)
    thr.start()
    yield dispatcher
    dispatcher.stop()
    thr.join()


@pytest.fixture(scope='function')
def dp(_dp):
    # Reset the dispatcher first
    while not _dp.update_queue.empty():
        _dp.update_queue.get(False)
    _dp.chat_data = defaultdict(dict)
    _dp.user_data = defaultdict(dict)
    _dp.handlers = {}
    _dp.groups = []
    _dp.error_handlers = []
    _dp.__stop_event = Event()
    _dp.__exception_event = Event()
    _dp.__async_queue = Queue()
    _dp.__async_threads = set()
    return _dp


def pytest_configure(config):
    if sys.version_info >= (3,):
        config.addinivalue_line('filterwarnings', 'ignore::ResourceWarning')
        # TODO: Write so good code that we don't need to ignore ResourceWarnings anymore
