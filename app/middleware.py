from blackfire import apm, profiler
from blackfire.hooks.utils import try_enable_probe, try_end_probe


# TODO: Rename and move to utils
def bytes_to_str(str_or_bytes):
    return str_or_bytes.decode(
    ) if isinstance(str_or_bytes, bytes) else str_or_bytes


# TODO: Rename
def _extract_headers(d):
    headers = d.get("headers")
    if headers:
        return dict((bytes_to_str(k), bytes_to_str(v)) for (k, v) in headers)
    return {}


_FRAMEWORK = 'FastAPI'

class BlackfireFastAPIMiddleware:

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # TODO: Add logs

        method = scope.get("method")
        path = scope.get('path')
        transaction = None
        scheme = scope.get('scheme')
        server = scope.get('server')
        probe_err = probe = None
        request_headers = _extract_headers(scope)

        if 'x-blackfire-query' in request_headers:
            probe_err, probe = try_enable_probe(
                request_headers['x-blackfire-query']
            )
        elif apm.trigger_trace():
            # TODO: We don't use _start_transaction() as there are checks to see
            # if there are outstanding transactions in a TLS value
            transaction = apm.ApmTransaction(extended=False)
            #transaction = apm._start_transaction(extended=apm.trigger_extended_trace())

        content_length = status_code = None
        async def wrapped_send(response):
            if response.get("type") == "http.response.start":
                response_headers = {}
                if "status" in response:
                    status_code = response["status"]
                if "headers" in response:
                    response_headers = _extract_headers(response)
                content_length = response_headers.get('content-length', None)

                if probe:
                    if probe_err:
                        pass  # TODO: Add response header
                    else:
                        # TODO:
                        # add_probe_response_header(response.headers, probe_resp)
                        response['headers'].append(
                            [
                                b'X-Blackfire-Response',
                                bytes(probe.get_agent_prolog_response().status_val, 'ascii')
                            ]
                        )
                elif transaction:
                    #apm._stop_and_queue_transaction(
                    transaction.stop()
                    apm._queue_trace(
                        transaction,
                        controller_name=transaction.name,  # TODO:
                        uri=path,
                        framework=_FRAMEWORK,
                        http_host='http_host',  # TODO:
                        method=method,
                        response_code=status_code if status_code else 500,
                        stdout=content_length if content_length else 0,
                    )
            return await send(response)

        r = await self.app(scope, receive, wrapped_send)

        try_end_probe(
            probe,
            response_status_code=status_code,
            response_len=content_length,
            controller_name='endpoint',  # TODO
            framework=_FRAMEWORK,
            http_method=method,
            http_uri=path,
            https='1' if scheme == 'https' else '',
            http_server_addr=server[0] if server else '',
            http_server_software='',  # TODO
            http_server_port=server[1] if server else '',
            http_header_host=request_headers.get('host'),
            http_header_user_agent=request_headers
            .get('user-agent'),
            http_header_x_forwarded_host='',  # TODO
            http_header_x_forwarded_proto='',  # TODO
            http_header_x_forwarded_port='',  # TODO
            http_header_forwarded='',  # TODO
        )
        return r
