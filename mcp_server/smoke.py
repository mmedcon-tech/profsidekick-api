import asyncio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    p = StdioServerParameters(command=sys.executable, args=["/srv/server.py"], env=dict(os.environ))
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("tools:", sorted(t.name for t in (await s.list_tools()).tools))
            for t in ("get_my_preferences", "list_my_conversations"):
                res = await s.call_tool(t, {})
                print(t, "->", res.content[0].text[:200])
asyncio.run(main())
