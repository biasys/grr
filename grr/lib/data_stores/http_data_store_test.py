#!/usr/bin/env python
"""Tests the HTTP remote data store abstraction."""


import os
import platform
import shutil
import socket
import tempfile
import threading
import unittest


import portpicker

import logging

from grr.lib import data_store
from grr.lib import data_store_test
from grr.lib import flags
from grr.lib import test_lib

from grr.lib.data_stores import http_data_store
from grr.lib.data_stores import sqlite_data_store

from grr.server.data_server import data_server


class StoppableHTTPServer(data_server.ThreadedHTTPServer):
  """HTTP server that can be stopped."""

  STOP = False

  def serve_forever(self):
    self.socket.settimeout(1)
    while not self.STOP:
      self.handle_request()
    self.socket.shutdown(socket.SHUT_RDWR)
    self.socket.close()


class MockRequestHandler(data_server.DataServerHandler):
  """Mock request handler that can stop a server."""

  def do_POST(self):  # pylint: disable=invalid-name
    if self.path == "/exit":
      StoppableHTTPServer.STOP = True
      return self._EmptyResponse(200)
    else:
      return super(MockRequestHandler, self).do_POST()


class MockRequestHandler1(MockRequestHandler):
  pass


class MockRequestHandler2(MockRequestHandler):
  pass


STARTED_SERVER = None
HTTP_DB = None
PORT = None
TMP_DIR = tempfile.mkdtemp(dir=(os.environ.get("TEST_TMPDIR") or "/tmp"))
CONFIG_OVERRIDER = None


def _StartServers():
  global HTTP_DB
  global STARTED_SERVER
  logging.info("Using TMP_DIR:" + TMP_DIR)
  temp_dir_1 = TMP_DIR + "/1"
  temp_dir_2 = TMP_DIR + "/2"
  os.mkdir(temp_dir_1)
  os.mkdir(temp_dir_2)
  HTTP_DB = [sqlite_data_store.SqliteDataStore(temp_dir_1),
             sqlite_data_store.SqliteDataStore(temp_dir_2)]
  STARTED_SERVER = [
      threading.Thread(
          target=data_server.Start,
          args=(HTTP_DB[0], PORT[0], True, StoppableHTTPServer,
                MockRequestHandler1)), threading.Thread(
                    target=data_server.Start,
                    args=(HTTP_DB[1], PORT[1], False, StoppableHTTPServer,
                          MockRequestHandler2))
  ]
  STARTED_SERVER[0].start()
  STARTED_SERVER[1].start()


def _SetConfig():
  global CONFIG_OVERRIDER
  CONFIG_OVERRIDER = test_lib.ConfigOverrider({
      "Dataserver.server_list": ["http://127.0.0.1:%d" % PORT[0],
                                 "http://127.0.0.1:%d" % PORT[1]],
      "Dataserver.server_username": "root",
      "Dataserver.server_password": "root",
      "Dataserver.client_credentials": ["user:user:rw"],
      "HTTPDataStore.username": "user",
      "HTTPDataStore.password": "user",
      "Datastore.location": TMP_DIR
  })
  CONFIG_OVERRIDER.Start()


def _CloseServers():
  # Directly tell both HTTP servers to stop.
  StoppableHTTPServer.STOP = True


def SetupDataStore():
  global PORT
  if PORT:
    return
  PORT = [portpicker.PickUnusedPort(), portpicker.PickUnusedPort()]
  _SetConfig()
  _StartServers()

  try:
    data_store.DB = http_data_store.HTTPDataStore()
    data_store.DB.Initialize()
  except http_data_store.HTTPDataStoreError:
    data_store.DB = None
    _CloseServers()


@unittest.skipUnless(platform.system() == "Linux",
                     "We only expect the datastore to work on Linux")
def setUpModule():
  SetupDataStore()


def tearDownModule():
  _CloseServers()
  CONFIG_OVERRIDER.Stop()


class HTTPDataStoreMixin(object):

  def setUp(self):
    super(HTTPDataStoreMixin, self).setUp()
    # These tests change the config so we preserve state.
    self.config_stubber = test_lib.PreserveConfig()
    self.config_stubber.Start()

  def tearDown(self):
    super(HTTPDataStoreMixin, self).tearDown()
    self.config_stubber.Stop()

  def InitDatastore(self):
    # Make sure that there are no rpc calls in progress. (Some Inithooks
    # create aff4 objects with sync=False)
    if data_store.DB:
      data_store.DB.Flush()

    # Hard reset of the sqlite directory trees.
    if HTTP_DB:
      try:
        HTTP_DB[0].cache.Flush()
        shutil.rmtree(HTTP_DB[0].cache.root_path)
      except (OSError, IOError):
        pass
      try:
        HTTP_DB[1].cache.Flush()
        shutil.rmtree(HTTP_DB[1].cache.root_path)
      except (OSError, IOError):
        pass


@unittest.skipUnless(platform.system() == "Linux",
                     "We only expect the datastore to work on Linux")
class HTTPDataStoreTest(HTTPDataStoreMixin, data_store_test._DataStoreTest):
  """Test the remote data store."""

  def __init__(self, *args):
    super(HTTPDataStoreTest, self).__init__(*args)

  def testDataStoreInit(self):
    # This just makes sure the datastore can actually initialize.
    pass


def main(args):
  test_lib.main(args)


if __name__ == "__main__":
  flags.StartMain(main)
