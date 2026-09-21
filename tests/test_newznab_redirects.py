import asyncio

import httpx

from scarletx.newznab import NewznabClient, NewznabIndexer


def test_newznab_capability_check_follows_indexer_endpoint_redirect():
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/":
            return httpx.Response(302, headers={"location": "/api"}, request=request)
        return httpx.Response(200, text="<caps/>", request=request)

    indexer = NewznabIndexer(name="Redirected", url="https://indexer.example", api_key="key")

    async def check():
        async with NewznabClient(indexer, transport=httpx.MockTransport(respond)) as client:
            return await client.caps()

    assert asyncio.run(check()) is True
    assert requests == ["/", "/api"]


def test_newznab_capability_check_preserves_the_configured_api_path():
    paths = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, text="<caps/>", request=request)

    indexer = NewznabIndexer(name="Exact path", url="https://indexer.example/api", api_key="key")

    async def check():
        async with NewznabClient(indexer, transport=httpx.MockTransport(respond)) as client:
            return await client.caps()

    assert asyncio.run(check()) is True
    assert paths == ["/api"]
