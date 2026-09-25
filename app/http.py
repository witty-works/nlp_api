import aiohttp
from logging import Logger
from app.settings import Settings


class Http:
    settings: Settings
    logger: Logger
    session: aiohttp.ClientSession
    ssl_session: aiohttp.ClientSession

    def __init__(self, settings: Settings, logger: Logger):
        self.settings = settings
        self.logger = logger

        self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
        self.ssl_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=True)
        )

    async def close(self) -> None:
        """Close all HTTP client sessions."""
        await self.session.close()
        await self.ssl_session.close()

    async def handle_response(
        self, r: aiohttp.ClientResponse, name: str, json: bool = True
    ):
        """Handle HTTP response with error logging.

        Args:
            r: aiohttp response object
            name: Service name for error messages
            json: If True, parse as JSON; otherwise return text

        Returns:
            Parsed JSON dict or text string

        Raises:
            Exception: If response status is not 200 or client error occurs
        """
        try:
            if r.status != 200:  # pragma: no cover
                result = await r.text()
                self.logger.error(result)
                raise Exception(result)

            return await r.json() if json else await r.text()

        except aiohttp.ClientError as err:  # pragma: no cover
            error_parts = [f"Problem communicating with {name}"]

            if r.status >= 500:
                try:
                    response = await r.text()
                    error_parts.append(response)
                except aiohttp.ClientError as err:
                    error_parts.append(str(err))
            else:
                error_parts.append(str(err))

            result = ": ".join(error_parts)
            self.logger.error(result)

        return result

    async def fetch_json_get(
        self,
        url: str,
        payload: any,
        headers: any,
        name: str,
        ssl: bool = True,
        json: bool = True,
    ) -> any:
        if ssl:
            async with self.ssl_session.get(url, params=payload, headers=headers) as r:
                return await self.handle_response(r, name, json)

        async with self.session.get(url, params=payload, headers=headers) as r:
            return await self.handle_response(r, name, json)

    async def fetch_json_post(
        self,
        url: str,
        payload: any,
        headers: any,
        name: str,
        ssl: bool = True,
        json: bool = True,
    ) -> any:
        if ssl:
            async with self.ssl_session.post(url, data=payload, headers=headers) as r:
                return await self.handle_response(r, name, json)

        async with self.session.post(url, data=payload, headers=headers) as r:
            return await self.handle_response(r, name, json)
