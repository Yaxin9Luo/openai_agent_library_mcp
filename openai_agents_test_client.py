import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="python",
    args=["openai_agents_server.py"],
    env=None,
)

# Define constants for testing
DOCS_URL = "https://openai.github.io/openai-agents-python/"

async def run_test():
    print("Starting OpenAI Agents SDK MCP client test...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()
            
            print("\n=== Testing server initialization ===")
            
            # List available tools
            print("\n=== Available Tools ===")
            tools = await session.list_tools()
            for tool in tools:
                print(f"- {tool.name}: {tool.description}")
            
            # List available prompts
            print("\n=== Available Prompts ===")
            prompts = await session.list_prompts()
            for prompt in prompts:
                print(f"- {prompt.name}: {prompt.description}")
            
            # Test searching for documentation
            print("\n=== Testing search_docs tool ===")
            search_result = await session.call_tool("search_docs", arguments={"query": "agent"})
            print(f"Search results: {search_result}")
            
            # Test searching GitHub repository
            print("\n=== Testing search_github tool ===")
            github_search_result = await session.call_tool("search_github", arguments={"query": "Agent"})
            print(f"GitHub search results: {github_search_result}")
            
            # Test getting documentation content
            print("\n=== Testing get_doc tool ===")
            try:
                doc_content = await session.call_tool("get_doc", arguments={"path": "index"})
                print(f"Documentation content (first 100 chars): {doc_content[:100]}...")
            except Exception as e:
                print(f"Error retrieving documentation: {e}")
            
            # Test getting GitHub repository structure
            print("\n=== Testing list_github_structure tool ===")
            try:
                structure = await session.call_tool("list_github_structure")
                print(f"GitHub structure: {structure[:100]}...")
            except Exception as e:
                print(f"Error retrieving GitHub structure: {e}")
            
            # Test getting a GitHub file
            print("\n=== Testing get_github_file tool ===")
            try:
                github_file = await session.call_tool("get_github_file", arguments={"path": "README.md"})
                print(f"GitHub file content (first 100 chars): {github_file[:100]}...")
            except Exception as e:
                print(f"Error retrieving GitHub file: {e}")
            
            # Test getting a section
            print("\n=== Testing get_section tool ===")
            section_result = await session.call_tool(
                "get_section", 
                arguments={
                    "page": DOCS_URL, 
                    "section": "installation"
                }
            )
            print(f"Section content (first 100 chars): {section_result[:100]}...")
            
            # Test getting code examples
            print("\n=== Testing get_code_examples tool ===")
            examples_result = await session.call_tool("get_code_examples", arguments={"topic": "agent"})
            print(f"Code examples result: {examples_result[:100]}...")
            
            # Test getting API documentation
            print("\n=== Testing get_api_docs tool ===")
            api_docs_result = await session.call_tool("get_api_docs", arguments={"class_or_function": "Agent"})
            print(f"API docs result: {api_docs_result[:100]}...")
            
            # Test getting documentation index
            print("\n=== Testing get_doc_index tool ===")
            doc_index_result = await session.call_tool("get_doc_index")
            print(f"Documentation index result: {doc_index_result[:100]}...")

if __name__ == "__main__":
    asyncio.run(run_test()) 