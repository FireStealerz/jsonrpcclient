"""Abstract base class for various clients."""
import json
from abc import ABCMeta, abstractmethod
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

import logging  # type: ignore
from apply_defaults import apply_config, apply_self  # type: ignore

from .config import config
from .log import log_
from .parse import parse
from .request import Notification, Request
from .response import Response

request_log = logging.getLogger(__name__ + ".request")
response_log = logging.getLogger(__name__ + ".response")


class Client(metaclass=ABCMeta):
    """
    Protocol-agnostic base class for clients.

    Subclasses should inherit and override `send_message`.
    """

    DEFAULT_REQUEST_LOG_FORMAT = "--> %(message)s"
    DEFAULT_RESPONSE_LOG_FORMAT = "<-- %(message)s"

    @apply_config(config, converters={"id_generator": "getcallable"})
    def __init__(
        self,
        trim_log_values: bool = False,
        validate_against_schema: bool = True,
        id_generator: Optional[Iterator] = None,
        basic_logging: bool = False
    ) -> None:
        """
        :param config: Log abbreviated versions of requests and responses.
        """
        self.trim_log_values = trim_log_values
        self.validate_against_schema = validate_against_schema
        self.id_generator = id_generator
        if basic_logging:
            self.basic_logging()

    @apply_self
    def log_request(
        self, request: str, trim_log_values: bool = False, **kwargs: Any
    ) -> None:
        """
        Log a request.

        :param request: The JSON-RPC request string.
        """
        return log_(request, request_log, "info", trim=trim_log_values, **kwargs)

    @apply_self
    def log_response(
        self, response: Response, trim_log_values: bool = False, **kwargs: Any
    ) -> None:
        """
        Log a response.

        Note this is different to log_request, in that it takes a Response object, not a
        string.

        :param response: Response object.
        """
        return log_(response.text, response_log, "info", trim=trim_log_values, **kwargs)

    def basic_logging(self) -> None:
        # Request handler
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt=self.DEFAULT_REQUEST_LOG_FORMAT))
        request_log.addHandler(handler)
        request_log.setLevel(logging.INFO)
        # Response handler
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt=self.DEFAULT_RESPONSE_LOG_FORMAT))
        response_log.addHandler(handler)
        response_log.setLevel(logging.INFO)

    @abstractmethod
    def send_message(self, request: str, **kwargs: Any) -> Response:
        """
        Transport the request to the server.

        Override this method in the protocol-specific subclasses.

        :param request: A JSON-RPC request.
        :returns: Response object.
        """

    def validate_response(self, response: Response) -> None:
        """
        Can be overridden for custom validation of the response.

        Raise an exception to fail validation.
        """
        pass

    @apply_self
    def send(
        self,
        request: Union[str, Dict, List],
        trim_log_values: bool = False,
        validate_against_schema: bool = True,
        **kwargs: Any
    ) -> Response:
        """
        Send a request, passing the whole JSON-RPC request object.

        After sending, logs, validates and parses.

        >>> client.send('{"jsonrpc": "2.0", "method": "ping", "id": 1}')
        --> {"jsonrpc": "2.0", "method": "ping", "id": 1}
        <-- {"jsonrpc": "2.0", "result": "pong", "id": 1}

        :param request: The JSON-RPC request.
        :type request: Either a JSON-encoded string or a Request/Notification object.
        :param kwargs: Clients can use these to configure an single request (separate to
            configuration of the whole session). For example, HTTPClient passes them on
            to `requests.Session.send()`.
        :returns: A Response object, (or ``None`` in the case of a Notification).
        :rtype: A `JSON-decoded object
            <https://docs.python.org/library/json.html#json-to-py-table>`_, or NoneType
            in the case of a Notification.
        """
        # Convert the request to a string if it's not already.
        request_text = request if isinstance(request, str) else json.dumps(request)
        self.log_request(request_text, trim_log_values=trim_log_values)
        response = self.send_message(request_text, **kwargs)
        self.log_response(response, trim_log_values=trim_log_values)
        self.validate_response(response)
        response.data = parse(
            response.text, validate_against_schema=validate_against_schema
        )
        return response

    @apply_self
    def notify(
        self,
        method_name: str,
        *args: Any,
        trim_log_values: Optional[bool] = None,
        validate_against_schema: Optional[bool] = None,
        **kwargs: Any
    ) -> Response:
        """
        Send a JSON-RPC request, without expecting a response.

        :param method_name: The remote procedure's method name.
        :param args: Positional arguments passed to the remote procedure.
        :param kwargs: Keyword arguments passed to the remote procedure.
        :return: The payload (i.e. the ``result`` part of the response).
        """
        return self.send(
            Notification(method_name, *args, **kwargs),
            trim_log_values=trim_log_values,
            validate_against_schema=validate_against_schema,
        )

    @apply_self
    def request(
        self,
        method_name: str,
        *args: Any,
        trim_log_values: bool = False,
        validate_against_schema: bool = True,
        id_generator: Optional[Iterator] = None,
        **kwargs: Any
    ) -> Response:
        """
        Send a request by passing the method and arguments.

        >>> client.request("cat", name="Yoko")
        --> {"jsonrpc": "2.0", "method": "cat", "params": {"name": "Yoko"}, "id": 1}
        <-- {"jsonrpc": "2.0", "result": "meow", "id": 1}
        'meow'

        :param method_name: The remote procedure's method name.
        :param args: Positional arguments passed to the remote procedure.
        :param kwargs: Keyword arguments passed to the remote procedure.
        :return: The payload (i.e. the ``result`` part of the response).
        """
        return self.send(
            Request(method_name, id_generator=id_generator, *args, **kwargs),
            trim_log_values=trim_log_values,
            validate_against_schema=validate_against_schema,
        )

    def __getattr__(self, name: str) -> Callable:
        """
        This gives us an alternate way to make a request::

            >>> client.cube(3)
            27

        That's the same as saying ``client.request("cube", 3)``.
        """

        def attr_handler(*args: Any, **kwargs: Any) -> Response:
            """Call self.request from here"""
            return self.request(name, *args, **kwargs)

        return attr_handler
