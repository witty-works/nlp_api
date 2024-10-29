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

    async def close(self):
        await self.session.close()
        await self.ssl_session.close()

    async def handle_response(
        self, r: aiohttp.ClientResponse, name: str, json: bool = True
    ) -> any:
        try:
            if r.status != 200:  # pragma: no cover
                result = await r.text()

                self.logger.error(result)

                raise Exception(result)

            if json:
                return await r.json()

            return await r.text()
        except aiohttp.ClientError as err:  # pragma: no cover
            result = "Problem communicating with " + name
            if r.status >= 500:
                try:
                    response = await r.text()
                    result += ": " + response
                except aiohttp.ClientError as err:
                    result += ": " + str(err)
            else:
                result += ": " + str(err)

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
