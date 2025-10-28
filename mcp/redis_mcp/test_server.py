import asyncio

from fastmcp import Client

MCP_URL="https://redis-mcp.fly.dev/mcp"
# MCP_URL="http://localhost:8080/mcp"

async def test_server():
    async with Client(MCP_URL) as client:
        tools = await client.list_tools()
        for tool in tools:
            print(f"--- 🛠️  Tool found: {tool.name} ---")
        # use redis set tool to set a test key, add a json value {"name": "test_name", "age": 30}
        result = await client.call_tool("redis_set", {"key": "test_key", "value": {"name": "test_name", "age": 30}, "expire_seconds": 10})
        print(f"--- ✅  Success: {result.content[0].text} ---")
        # use redis get tool to get the test key
        result = await client.call_tool("redis_get", {"key": "test_key"})
        print(f"--- ✅  Success: {result.content[0].text} ---")
        # use redis delete tool to delete the test key
        result = await client.call_tool("redis_delete", {"key": "test_key"})
        print(f"--- ✅  Success: {result.content[0].text} ---")

if __name__ == "__main__":
    asyncio.run(test_server())