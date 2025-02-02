# -*- coding: utf-8 -*-


__all__ = ["public", "Service", "RequestError", "Client"]


from json import loads
from traceback import format_exc
from uuid import uuid4

import xbmc

from .tools import Logger, getAddonId, executeJSONRPC


# ------------------------------------------------------------------------------
# Monitor

class Monitor(xbmc.Monitor):

    @staticmethod
    def send(sender, message, data):
        executeJSONRPC(
            "JSONRPC.NotifyAll", sender=sender, message=message, data=data
        )


# public -----------------------------------------------------------------------

def public(func):
    func.__public__ = True
    return func


# ------------------------------------------------------------------------------
# Service

class Service(Monitor):

    @staticmethod
    def __methods__(value, key=None):
        for name in dir(value):
            if (
                (not name.startswith("_")) and
                (callable(method := getattr(value, name))) and
                (getattr(method, "__public__", False))
            ):
                yield f"{key}.{name}" if key else name, method

    def __init__(self, id=None):
        self.id = id or getAddonId()
        self.logger = Logger(self.id, component="service")
        self.methods = {}

    def serve_forever(self, timeout):
        while not self.waitForAbort(timeout):
            pass

    def serve(self, timeout=-1, **kwargs):
        self.methods.update(self.__methods__(self))
        for key, value in kwargs.items():
            self.methods.update(self.__methods__(value, key))
        try:
            self.serve_forever(timeout)
        finally:
            self.methods.clear() # clear possible circular references

    def execute(self, request):
        try:
            name, args, kwargs = loads(request)
            try:
                method = self.methods[name]
            except KeyError:
                raise AttributeError(f"no method '{name}'") from None
            return {"result": method(*args, **kwargs)}
        except Exception:
            error = format_exc().strip()
            self.logger.error(f"error processing request\n{error}")
            return {"error": error}

    def onNotification(self, sender, method, data):
        if sender == self.id:
            self.send(method.split(".", 1)[1], sender, self.execute(data))


# ------------------------------------------------------------------------------
# Client

class RequestError(Exception):

    def __init__(self, message="unknown request error"):
        super(RequestError, self).__init__(message)


class Request(Monitor):

    def __init__(self, id):
        self.id = id
        self.message = uuid4().hex
        self.response = RequestError()
        self.ready = False

    def execute(self, request):
        self.send(self.id, self.message, request)
        while not self.ready:
            if self.waitForAbort(0.1):
                self.response = RequestError("request aborted")
                break
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def handle(self, response):
        try:
            response = loads(response)
            try:
                self.response = response["result"]
            except KeyError:
                self.response = RequestError(
                    f"remote error\n{response['error']}"
                )
        except Exception as error:
            self.response = error
        finally:
            self.ready = True

    def onNotification(self, sender, method, data):
        if sender == self.message and method.split(".", 1)[1] == self.id:
            self.handle(data)


class Attribute(object):

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __getattr__(self, name):
        return Attribute(self.id, f"{self.name}.{name}")

    def __call__(self, *args, **kwargs):
        return Request(self.id).execute((self.name, args, kwargs))


class Client(object):

    def __init__(self, id=None):
        self.id = id or getAddonId()

    def __getattr__(self, name):
        return Attribute(self.id, name)

