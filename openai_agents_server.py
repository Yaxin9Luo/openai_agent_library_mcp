from mcp.server.fastmcp import FastMCP
import httpx
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from typing import List, Dict, Optional, Union, Any
import json
import asyncio
import datetime

# Create an MCP server for OpenAI Agents SDK Documentation
mcp = FastMCP("OpenAI Agents SDK Documentation")

# Base URLs for OpenAI Agents documentation
DOCS_URL = "https://openai.github.io/openai-agents-python/"
GITHUB_URL = "https://github.com/openai/openai-agents-python"
RAW_GITHUB_URL = "https://raw.githubusercontent.com/openai/openai-agents-python/main/"

# Cache for documentation content
doc_cache = {}
github_cache = {}

# Helper function to fetch and parse documentation
async def fetch_doc_page(url: str) -> str:
    """Fetch and parse a documentation page."""
    if url in doc_cache:
        return doc_cache[url]
    
    full_url = url if url.startswith('http') else urljoin(DOCS_URL, url)
    
    async with httpx.AsyncClient() as client:
        response = await client.get(full_url)
        response.raise_for_status()
        
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract the main content
        main_content = soup.find('article') or soup.find('main') or soup.find('div', class_='markdown-body')
        if main_content:
            content = main_content.get_text(separator='\n', strip=True)
        else:
            content = soup.get_text(separator='\n', strip=True)
        
        # Cache the result
        doc_cache[url] = content
        return content

# Helper function to fetch GitHub files
async def fetch_github_file(path: str) -> str:
    """Fetch a file from the GitHub repository."""
    if path in github_cache:
        return github_cache[path]
    
    # Use raw GitHub URL for content
    url = urljoin(RAW_GITHUB_URL, path)
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.text
        
        # Cache the result
        github_cache[path] = content
        return content

# Helper function to get GitHub repository structure
async def get_github_structure() -> Dict:
    """Retrieve the structure of the GitHub repository."""
    try:
        # Get the main page of the repository to extract directory structure
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{GITHUB_URL}/tree/main", timeout=15.0)
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract files and directories from the GitHub page
            structure = {
                "files": [],
                "directories": []
            }
            
            # Try multiple selectors for GitHub's file explorer rows
            file_items = soup.select("div.Box-row") or soup.select("div[role='row']") or soup.select("tr.js-navigation-item")
            
            if not file_items:
                # If no files found, try different approach with more detailed logging
                print(f"No file items found using standard selectors. Trying alternative approach.")
                # Let's look for any links that might be file/directory links
                repo_content_area = soup.find("div", class_="repository-content") or soup.find("div", {"data-pjax": "#repo-content-pjax-container"})
                if repo_content_area:
                    links = repo_content_area.find_all("a")
                    for link in links:
                        href = link.get("href", "")
                        if "/blob/main/" in href or "/tree/main/" in href:
                            is_dir = "/tree/main/" in href
                            name = link.get_text(strip=True)
                            path = href.replace(f"/openai/openai-agents-python/tree/main/", "").replace(f"/openai/openai-agents-python/blob/main/", "")
                            
                            if is_dir and path and name:
                                structure["directories"].append({"name": name, "path": path})
                            elif path and name:
                                structure["files"].append({"name": name, "path": path})
            else:
                # Process items found using standard selectors
                for item in file_items:
                    try:
                        # Try multiple ways to detect directories vs files
                        svg = item.select_one("svg")
                        link = item.select_one("a[data-pjax]") or item.select_one("a[href*='/blob/main/']") or item.select_one("a[href*='/tree/main/']")
                        
                        if not link:
                            # Try any link in the item
                            link = item.select_one("a")
                        
                        if link:
                            href = link.get("href", "")
                            name = link.get_text(strip=True)
                            
                            # Determine if directory by SVG aria-label or href
                            is_dir = False
                            if svg and svg.get("aria-label"):
                                is_dir = "directory" in svg.get("aria-label", "").lower() or "dir" in svg.get("aria-label", "").lower()
                            elif href:
                                is_dir = "/tree/main/" in href
                            
                            # Extract path from href
                            path = ""
                            if "/blob/main/" in href:
                                path = href.replace(f"/openai/openai-agents-python/blob/main/", "")
                            elif "/tree/main/" in href:
                                path = href.replace(f"/openai/openai-agents-python/tree/main/", "")
                            
                            if path:
                                if is_dir:
                                    structure["directories"].append({"name": name, "path": path})
                                else:
                                    structure["files"].append({"name": name, "path": path})
                    except Exception as e:
                        print(f"Error processing item: {str(e)}")
            
            # If still empty, try to directly parse important directories
            if not structure["files"] and not structure["directories"]:
                default_dirs = ["examples", "src", "docs", "tests"]
                for dir_name in default_dirs:
                    structure["directories"].append({"name": dir_name, "path": dir_name})
                
                print(f"No files/directories found in GitHub response. Added default directories: {default_dirs}")
            
            return structure
    except Exception as e:
        print(f"Error retrieving GitHub structure: {str(e)}")
        return {"error": str(e), "files": [], "directories": []}

# Tool for searching documentation
@mcp.tool()
async def search_docs(query: str) -> str:
    """Search for a specific term across OpenAI Agents SDK documentation."""
    results = []
    
    # Clean the query
    query = query.strip().lower()
    if not query:
        return "Please provide a search query."
    
    # Break query into terms for more flexible matching
    query_terms = query.split()
    
    # Start with the main page
    try:
        content = await fetch_doc_page(DOCS_URL)
        soup = BeautifulSoup(content, 'html.parser')
        
        # Get links to other pages
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith(('http://', 'https://', '#', 'javascript:')):
                links.append(href)
        
        # Search main page for any of the terms
        if any(term in content.lower() for term in query_terms):
            # Find the context around the first matching term
            for term in query_terms:
                if term in content.lower():
                    index = content.lower().find(term)
                    start = max(0, index - 100)
                    end = min(len(content), index + len(term) + 100)
                    snippet = content[start:end]
                    
                    results.append({
                        "url": DOCS_URL,
                        "title": "Main Page",
                        "snippet": f"...{snippet}..."
                    })
                    break
        
        # Search more pages (increasing from 10 to 20 for better coverage)
        for link in links[:20]:
            try:
                page_url = urljoin(DOCS_URL, link)
                page_content = await fetch_doc_page(page_url)
                
                # Check for any of the terms
                if any(term in page_content.lower() for term in query_terms):
                    # Find the context around the first matching term
                    for term in query_terms:
                        if term in page_content.lower():
                            index = page_content.lower().find(term)
                            start = max(0, index - 100)
                            end = min(len(page_content), index + len(term) + 100)
                            snippet = page_content[start:end]
                            
                            results.append({
                                "url": page_url,
                                "title": link,
                                "snippet": f"...{snippet}..."
                            })
                            break
            except Exception as e:
                continue
        
        if not results:
            return f"No results found for your query: '{query}'. Try a different search term or check the documentation index."
        
        return json.dumps(results, indent=2)
    
    except Exception as e:
        return f"Error searching documentation: {str(e)}"

# Tool for searching GitHub repository
@mcp.tool()
async def search_github(query: str) -> str:
    """Search for a specific term across the GitHub repository."""
    results = []
    search_errors = []
    
    # Clean the query
    query = query.strip().lower()
    if not query:
        return "Please provide a search query."
    
    # Break query into terms for more flexible matching
    query_terms = query.split()
    
    # First get the repository structure
    try:
        structure = await get_github_structure()
        if "error" in structure:
            search_errors.append(f"Error getting repository structure: {structure.get('error')}")
            structure = {"files": [], "directories": []}
        
        # Check files in the root directory
        for file in structure.get("files", []):
            try:
                path = file.get("path", "")
                if not path:
                    continue
                
                file_content = await fetch_github_file(path)
                
                # Check for any query term
                if any(term in file_content.lower() for term in query_terms):
                    # Find matching term and context
                    for term in query_terms:
                        if term in file_content.lower():
                            index = file_content.lower().find(term)
                            start = max(0, index - 100)
                            end = min(len(file_content), index + len(term) + 100)
                            snippet = file_content[start:end]
                            
                            results.append({
                                "path": path,
                                "url": f"{GITHUB_URL}/blob/main/{path}",
                                "snippet": f"...{snippet}...",
                                "matched_term": term
                            })
                            break
            except Exception as e:
                search_errors.append(f"Error checking root file {file.get('name', 'unknown')}: {str(e)}")
        
        # Process directories concurrently
        async def search_directory(dir_path):
            dir_results = []
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{GITHUB_URL}/tree/main/{dir_path}", timeout=10.0)
                    if response.status_code == 404:
                        search_errors.append(f"Directory not found: {dir_path}")
                        return []  # Directory doesn't exist
                    
                    response.raise_for_status()
                    html = response.text
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract Python files
                    file_items = soup.select("div.Box-row")
                    for item in file_items:
                        link = item.select_one("a[data-pjax]")
                        if not link:
                            continue
                            
                        file_path = link.get("href", "").replace(f"/openai/openai-agents-python/blob/main/", "")
                        if file_path.endswith((".py", ".md")):
                            try:
                                file_content = await fetch_github_file(file_path)
                                
                                # Check for any query term
                                if any(term in file_content.lower() for term in query_terms):
                                    # Find matching term and context
                                    for term in query_terms:
                                        if term in file_content.lower():
                                            index = file_content.lower().find(term)
                                            start = max(0, index - 100)
                                            end = min(len(file_content), index + len(term) + 100)
                                            snippet = file_content[start:end]
                                            
                                            dir_results.append({
                                                "path": file_path,
                                                "url": f"{GITHUB_URL}/blob/main/{file_path}",
                                                "snippet": f"...{snippet}...",
                                                "matched_term": term
                                            })
                                            break
                            except Exception as e:
                                search_errors.append(f"Error processing file {file_path}: {str(e)}")
                return dir_results
            except Exception as e:
                search_errors.append(f"Error searching directory {dir_path}: {str(e)}")
                return []
        
        # Check key directories for Python files
        key_dirs = ["openai", "examples", "docs", "src", "src/agents", "tests"]
        search_tasks = []
        
        for dir_name in key_dirs:
            search_tasks.append(search_directory(dir_name))
        
        # Execute directory searches concurrently
        dir_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)
        
        # Process results
        for result in dir_results_list:
            if isinstance(result, list):
                results.extend(result)
            elif isinstance(result, Exception):
                search_errors.append(f"Error in directory search: {str(result)}")
        
        # Debug info
        debug_info = {
            "search_query": query,
            "search_terms": query_terms,
            "directories_searched": key_dirs,
            "errors": search_errors if search_errors else None
        }
        
        result = {
            "results": results,
            "debug_info": debug_info
        }
        
        if not results:
            return json.dumps({
                "error": f"No results found in the GitHub repository for query: '{query}'. Try different search terms.",
                "debug_info": debug_info
            }, indent=2)
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return f"Error searching GitHub repository: {str(e)}"

# Tool for getting specific sections
@mcp.tool()
async def get_section(page: str, section: str) -> str:
    """Get a specific section from a documentation page."""
    try:
        if not page or not section:
            return "Please provide both a page path and section name."
            
        full_url = page if page.startswith('http') else urljoin(DOCS_URL, page)
        if not full_url.endswith('.html'):
            full_url = f"{full_url}.html"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(full_url)
            if response.status_code == 404:
                return f"Documentation page not found: {page}"
                
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for headings that match the section
            heading_tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
            found_heading = None
            section_lower = section.lower()
            
            # First try exact match
            for tag in heading_tags:
                headings = soup.find_all(tag)
                for heading in headings:
                    heading_text = heading.get_text().lower()
                    if section_lower == heading_text or section_lower in heading_text:
                        found_heading = heading
                        break
                if found_heading:
                    break
            
            # If no exact match, try partial match
            if not found_heading:
                best_match = None
                best_match_score = 0
                
                for tag in heading_tags:
                    headings = soup.find_all(tag)
                    for heading in headings:
                        heading_text = heading.get_text().lower()
                        # Calculate how many words from the section are in the heading
                        section_words = section_lower.split()
                        match_score = sum(1 for word in section_words if word in heading_text)
                        
                        if match_score > best_match_score:
                            best_match_score = match_score
                            best_match = heading
                
                if best_match_score > 0:
                    found_heading = best_match
            
            if not found_heading:
                # Get all available sections to suggest alternatives
                all_sections = []
                for tag in heading_tags:
                    headings = soup.find_all(tag)
                    for heading in headings:
                        all_sections.append(heading.get_text().strip())
                
                return json.dumps({
                    "error": f"Section '{section}' not found in the documentation.",
                    "available_sections": all_sections[:15],  # Limit to 15 sections to avoid overwhelming response
                    "page_url": full_url
                }, indent=2)
            
            # Extract content following the heading
            content = []
            current = found_heading.next_sibling
            next_heading = None
            
            # Get all content until the next heading of same or higher level
            heading_level = int(found_heading.name[1])
            
            while current and not next_heading:
                if current.name and current.name[0] == 'h' and len(current.name) == 2:
                    current_level = int(current.name[1])
                    if current_level <= heading_level:
                        next_heading = current
                        break
                
                if current.name:
                    content.append(current.get_text(strip=True))
                elif isinstance(current, str) and current.strip():
                    content.append(current.strip())
                
                current = current.next_sibling
            
            if not content:
                # Extract content by looking at the entire div containing the heading
                parent_div = found_heading.find_parent('div', class_=['section', 'markdown-body', 'content'])
                if parent_div:
                    # Get text after the heading within the div
                    heading_index = -1
                    div_children = list(parent_div.children)
                    
                    for i, child in enumerate(div_children):
                        if child == found_heading:
                            heading_index = i
                            break
                    
                    if heading_index >= 0:
                        for child in div_children[heading_index+1:]:
                            if child.name and child.name[0] == 'h' and len(child.name) == 2:
                                current_level = int(child.name[1])
                                if current_level <= heading_level:
                                    break
                            
                            if child.name:
                                content.append(child.get_text(strip=True))
                            elif isinstance(child, str) and child.strip():
                                content.append(child.strip())
            
            if not content:
                return json.dumps({
                    "error": f"Found section '{section}' but couldn't extract content.",
                    "heading": found_heading.get_text(),
                    "page_url": full_url
                }, indent=2)
            
            section_content = "\n".join(content)
            
            # Look for code examples in the section
            code_blocks = soup.find_all('pre')
            section_code_examples = []
            
            for code_block in code_blocks:
                # Check if the code block appears after our section heading
                if code_block.sourceline > found_heading.sourceline:
                    # And before the next heading of same or higher level
                    if next_heading and code_block.sourceline < next_heading.sourceline:
                        section_code_examples.append(code_block.get_text())
            
            return json.dumps({
                "section": found_heading.get_text(),
                "content": section_content,
                "code_examples": section_code_examples,
                "page_url": full_url
            }, indent=2)
    
    except Exception as e:
        return f"Error retrieving section: {str(e)}"

# Tool for searching files in the GitHub repository by name
@mcp.tool()
async def search_files(filename_pattern: str) -> str:
    """Search for files by name across the GitHub repository.
    
    Args:
        filename_pattern: Part of the filename to search for. Can be a full filename or a partial name.
    
    Returns:
        JSON array of matching files with their paths and URLs.
    """
    try:
        filename_pattern = filename_pattern.strip().lower()
        if not filename_pattern:
            return "Please provide a filename pattern to search for."
        
        matches = []
        search_errors = []
        
        # First get the structure of the repository for top-level directories
        try:
            structure = await get_github_structure()
            if "error" in structure:
                search_errors.append(f"Error getting repository structure: {structure.get('error')}")
                structure = {"files": [], "directories": []}
        except Exception as e:
            search_errors.append(f"Error getting repository structure: {str(e)}")
            structure = {"files": [], "directories": []}
        
        # Check files in the root directory
        for file in structure.get("files", []):
            try:
                name = file.get("name", "").lower()
                path = file.get("path", "")
                
                if filename_pattern in name:
                    matches.append({
                        "name": name,
                        "path": path,
                        "url": f"{GITHUB_URL}/blob/main/{path}"
                    })
            except Exception as e:
                search_errors.append(f"Error checking root file {file.get('name', 'unknown')}: {str(e)}")
        
        # Function to recursively search directories
        async def search_directory(dir_path):
            nonlocal matches, search_errors
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{GITHUB_URL}/tree/main/{dir_path}", timeout=10.0)
                    if response.status_code == 404:
                        search_errors.append(f"Directory not found: {dir_path}")
                        return  # Directory doesn't exist
                    
                    response.raise_for_status()
                    html = response.text
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract files and subdirectories
                    items = soup.select("div.Box-row")
                    subdirs = []
                    
                    for item in items:
                        try:
                            svg = item.select_one("svg")
                            link = item.select_one("a[data-pjax]")
                            
                            if not link:
                                continue
                            
                            name = link.get_text(strip=True)
                            is_dir = svg and "dir" in svg.get("aria-label", "").lower() if svg.get("aria-label") else False
                            
                            if is_dir:
                                # Add to list of subdirectories to search
                                subdir_path = f"{dir_path}/{name}"
                                subdirs.append(subdir_path)
                            else:
                                # Check if the file matches
                                if filename_pattern in name.lower():
                                    file_path = f"{dir_path}/{name}"
                                    matches.append({
                                        "name": name,
                                        "path": file_path,
                                        "url": f"{GITHUB_URL}/blob/main/{file_path}"
                                    })
                        except Exception as e:
                            search_errors.append(f"Error processing item in {dir_path}: {str(e)}")
                    
                    # Now search subdirectories (up to a certain depth to avoid infinite recursion)
                    for subdir in subdirs:
                        if len(subdir.split('/')) <= 3:  # Limit depth to 3 levels
                            await search_directory(subdir)
            except Exception as e:
                search_errors.append(f"Error searching directory {dir_path}: {str(e)}")
        
        # Search key directories where examples and code are likely to be
        key_dirs = ["examples", "src", "docs", "test", "tests"]
        
        # Get directory search tasks
        search_tasks = []
        for directory in key_dirs:
            if directory in [d.get("path") for d in structure.get("directories", [])]:
                search_tasks.append(search_directory(directory))
            else:
                # Try searching anyway - the structure might not be complete
                search_tasks.append(search_directory(directory))
        
        # Execute directory searches concurrently
        if search_tasks:
            await asyncio.gather(*search_tasks, return_exceptions=True)
        
        # If no matches found, make a direct attempt to find in specific locations
        if not matches:
            direct_paths = [
                "examples",
                "src/agents", 
                "docs",
                "test",
                "tests"
            ]
            
            for path in direct_paths:
                try:
                    await search_directory(path)
                except Exception as e:
                    search_errors.append(f"Error in direct search of {path}: {str(e)}")
        
        # Debug info to include in the response
        debug_info = {
            "search_pattern": filename_pattern,
            "directories_searched": key_dirs,
            "errors": search_errors if search_errors else None
        }
        
        result = {
            "matches": matches,
            "debug_info": debug_info
        }
        
        if not matches:
            # Try to provide more helpful error message
            if search_errors:
                return json.dumps({
                    "error": f"No files found matching '{filename_pattern}'. There were errors during search that might have affected results.",
                    "debug_info": debug_info
                }, indent=2)
            else:
                return json.dumps({
                    "error": f"No files found matching '{filename_pattern}'. Try a different search pattern.",
                    "debug_info": debug_info
                }, indent=2)
        
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error searching for files: {str(e)}"

# Tool for getting code examples
@mcp.tool()
async def get_code_examples(topic: str) -> str:
    """Get code examples related to a specific OpenAI Agents SDK topic."""
    try:
        examples = []
        search_errors = []
        topic = topic.strip().lower()
        
        if not topic:
            return "Please provide a topic to search for code examples."
        
        # Break topic into terms for more flexible matching
        topic_terms = topic.split()
        
        # First search using the search_files tool for matching filenames
        try:
            # Try to directly match files with these terms in their names
            for term in topic_terms:
                if len(term) >= 3:  # Only search for terms that are at least 3 characters
                    search_files_result = await search_files(term)
                    try:
                        result_data = json.loads(search_files_result)
                        if "matches" in result_data:
                            for file_match in result_data.get("matches", []):
                                path = file_match.get("path", "")
                                if path.endswith((".py", ".md", ".ipynb")) and path not in [ex.get("path") for ex in examples]:
                                    try:
                                        content = await fetch_github_file(path)
                                        examples.append({
                                            "path": path,
                                            "url": f"{GITHUB_URL}/blob/main/{path}",
                                            "content": content[:1500] + ("..." if len(content) > 1500 else ""),
                                            "matched_by": f"filename contains '{term}'"
                                        })
                                    except Exception as e:
                                        search_errors.append(f"Error fetching file {path}: {str(e)}")
                    except json.JSONDecodeError:
                        search_errors.append(f"Error parsing search_files result for term '{term}'")
        except Exception as e:
            search_errors.append(f"Error using search_files: {str(e)}")
        
        # Directly try common example file patterns
        common_example_files = [
            f"examples/{topic}.py",
            f"examples/{topic}_example.py",
            f"examples/{topic.replace('-', '_')}.py",
            f"examples/{topic.replace('_', '-')}.py",
            f"src/agents/examples/{topic}.py",
            f"docs/examples/{topic}.py"
        ]
        
        for path in common_example_files:
            try:
                content = await fetch_github_file(path)
                if not any(ex.get("path") == path for ex in examples):
                    examples.append({
                        "path": path,
                        "url": f"{GITHUB_URL}/blob/main/{path}",
                        "content": content[:1500] + ("..." if len(content) > 1500 else ""),
                        "matched_by": "direct path match"
                    })
            except Exception:
                pass  # Expected to fail for many paths
        
        # Specifically check for examples directory files
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{GITHUB_URL}/tree/main/examples", timeout=10.0)
                response.raise_for_status()
                
                html = response.text
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract Python files
                file_items = soup.select("div.Box-row")
                for item in file_items:
                    try:
                        link = item.select_one("a[data-pjax]")
                        if not link:
                            continue
                            
                        file_name = link.get_text(strip=True).lower()
                        file_path = link.get("href", "").replace(f"/openai/openai-agents-python/blob/main/", "")
                        
                        # Check both the filename and content for matches
                        if any(term in file_name for term in topic_terms) and file_path.endswith((".py", ".md")):
                            file_content = await fetch_github_file(file_path)
                            # Only add if not already added
                            if not any(ex.get("path") == file_path for ex in examples):
                                examples.append({
                                    "path": file_path,
                                    "url": f"{GITHUB_URL}/blob/main/{file_path}",
                                    "content": file_content[:1500] + ("..." if len(file_content) > 1500 else ""),
                                    "matched_by": f"filename in examples directory contains topic term"
                                })
                        # Even if filename doesn't match, check content for all examples
                        elif file_path.endswith((".py", ".md")):
                            file_content = await fetch_github_file(file_path)
                            if any(term in file_content.lower() for term in topic_terms):
                                # Only add if not already added
                                if not any(ex.get("path") == file_path for ex in examples):
                                    examples.append({
                                        "path": file_path,
                                        "url": f"{GITHUB_URL}/blob/main/{file_path}",
                                        "content": file_content[:1500] + ("..." if len(file_content) > 1500 else ""),
                                        "matched_by": f"content in examples directory contains topic term"
                                    })
                    except Exception as e:
                        search_errors.append(f"Error processing example file: {str(e)}")
        except Exception as e:
            search_errors.append(f"Error accessing examples directory: {str(e)}")
        
        # Also check additional directories where examples might exist
        additional_example_dirs = ["src/agents/examples", "docs/examples", "tests"]
        for dir_path in additional_example_dirs:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{GITHUB_URL}/tree/main/{dir_path}", timeout=10.0)
                    if response.status_code == 404:
                        continue  # Directory doesn't exist
                    
                    response.raise_for_status()
                    html = response.text
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract Python files
                    file_items = soup.select("div.Box-row")
                    for item in file_items:
                        try:
                            link = item.select_one("a[data-pjax]")
                            if not link:
                                continue
                                
                            file_name = link.get_text(strip=True).lower()
                            file_path = link.get("href", "").replace(f"/openai/openai-agents-python/blob/main/", "")
                            
                            if file_path.endswith((".py", ".md")):
                                try:
                                    file_content = await fetch_github_file(file_path)
                                    
                                    # Check both filename and content
                                    matched = False
                                    match_reason = ""
                                    
                                    # Check filename
                                    if any(term in file_name for term in topic_terms):
                                        matched = True
                                        match_reason = f"filename in {dir_path} contains topic term"
                                    
                                    # Check content
                                    if not matched and any(term in file_content.lower() for term in topic_terms):
                                        matched = True
                                        match_reason = f"content in {dir_path} contains topic term"
                                    
                                    if matched:
                                        # Only add if not already added
                                        if not any(ex.get("path") == file_path for ex in examples):
                                            examples.append({
                                                "path": file_path,
                                                "url": f"{GITHUB_URL}/blob/main/{file_path}",
                                                "content": file_content[:1500] + ("..." if len(file_content) > 1500 else ""),
                                                "matched_by": match_reason
                                            })
                                except Exception as e:
                                    search_errors.append(f"Error fetching/processing file {file_path}: {str(e)}")
                        except Exception as e:
                            search_errors.append(f"Error processing file in {dir_path}: {str(e)}")
            except Exception as e:
                search_errors.append(f"Error accessing directory {dir_path}: {str(e)}")
        
        # Always search src/agents directory as it's likely to contain relevant code
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{GITHUB_URL}/tree/main/src/agents", timeout=10.0)
                if response.status_code != 404:
                    response.raise_for_status()
                    html = response.text
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract Python files
                    file_items = soup.select("div.Box-row")
                    for item in file_items:
                        try:
                            link = item.select_one("a[data-pjax]")
                            if not link:
                                continue
                                
                            file_path = link.get("href", "").replace(f"/openai/openai-agents-python/blob/main/", "")
                            if file_path.endswith(".py"):
                                try:
                                    file_content = await fetch_github_file(file_path)
                                    
                                    # For core files, focus on content matches
                                    if any(term in file_content.lower() for term in topic_terms):
                                        # Only add if not already added
                                        if not any(ex.get("path") == file_path for ex in examples):
                                            examples.append({
                                                "path": file_path,
                                                "url": f"{GITHUB_URL}/blob/main/{file_path}",
                                                "content": file_content[:1500] + ("..." if len(file_content) > 1500 else ""),
                                                "matched_by": "content match in core source file"
                                            })
                                except Exception as e:
                                    search_errors.append(f"Error fetching/processing file {file_path}: {str(e)}")
                        except Exception as e:
                            search_errors.append(f"Error processing file in src/agents: {str(e)}")
        except Exception as e:
            search_errors.append(f"Error accessing src/agents directory: {str(e)}")
        
        # Specific search for handoff examples (as mentioned in your error case)
        if "handoff" in topic.lower():
            specific_handoff_files = [
                "examples/agent_patterns/agents_with_handoffs.py",
                "examples/handoffs.py",
                "src/agents/handoffs.py",
                "examples/agent_patterns/triage.py"  # Likely contains handoff examples
            ]
            
            for path in specific_handoff_files:
                try:
                    content = await fetch_github_file(path)
                    if not any(ex.get("path") == path for ex in examples):
                        examples.append({
                            "path": path,
                            "url": f"{GITHUB_URL}/blob/main/{path}",
                            "content": content[:1500] + ("..." if len(content) > 1500 else ""),
                            "matched_by": "direct handoff file match"
                        })
                except Exception:
                    pass
        
        # Debug info
        debug_info = {
            "search_topic": topic,
            "search_terms": topic_terms,
            "errors": search_errors if search_errors else None
        }
        
        result = {
            "examples": examples,
            "debug_info": debug_info
        }
        
        if not examples:
            return json.dumps({
                "error": f"No code examples found for '{topic}'. Try a different search term or check the documentation and GitHub repository directly.",
                "debug_info": debug_info
            }, indent=2)
        
        return json.dumps(result, indent=2)
    
    except Exception as e:
        return f"Error retrieving code examples: {str(e)}"

# Tool for getting API documentation
@mcp.tool()
async def get_api_docs(class_or_function: str) -> str:
    """Get API documentation for a specific class or function in the OpenAI Agents SDK."""
    try:
        # Validate input
        class_or_function = class_or_function.strip()
        if not class_or_function:
            return "Please provide a class or function name to look up."
            
        # Clean the query and prepare for flexible matching
        query = class_or_function.lower()
        query_terms = query.split()
        
        results = {
            "query": class_or_function,
            "matches": []
        }
        
        # First check the API reference page
        api_doc_url = urljoin(DOCS_URL, "api_reference.html")
        async with httpx.AsyncClient() as client:
            response = await client.get(api_doc_url, timeout=10.0)
            if response.status_code == 404:
                return json.dumps({
                    "error": "API reference page not found. The documentation structure might have changed.",
                    "query": class_or_function
                }, indent=2)
                
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for the class or function in the API reference
            # First look for headings
            found_elements = []
            
            # Look for headings that might contain the class or function name
            heading_tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
            for tag in heading_tags:
                headings = soup.find_all(tag)
                for heading in headings:
                    heading_text = heading.get_text().strip().lower()
                    
                    # Check for exact or partial matches
                    if query in heading_text or any(term in heading_text for term in query_terms):
                        found_elements.append({
                            "heading": heading.get_text().strip(),
                            "level": int(tag[1]),
                            "element": heading
                        })
            
            # For each found heading, extract its content
            for element_info in found_elements:
                heading = element_info["element"]
                heading_level = element_info["level"]
                
                # Extract content until the next heading of same or higher level
                content = []
                code_examples = []
                current = heading.next_sibling
                
                while current:
                    if current.name and current.name in heading_tags:
                        current_level = int(current.name[1])
                        if current_level <= heading_level:
                            break
                    
                    # Extract code examples separately
                    if current.name == 'pre' or current.name == 'code':
                        code_examples.append(current.get_text(strip=True))
                    elif current.name:
                        content.append(current.get_text(strip=True))
                    elif isinstance(current, str) and current.strip():
                        content.append(current.strip())
                    
                    current = current.next_sibling
                
                # If content extraction didn't work well, try to find the parent section
                if not content:
                    parent_div = heading.find_parent('div', class_=['section', 'markdown-body', 'content'])
                    if parent_div:
                        # Get all content after the heading within this div
                        heading_index = -1
                        div_children = list(parent_div.children)
                        
                        for i, child in enumerate(div_children):
                            if child == heading:
                                heading_index = i
                                break
                        
                        if heading_index >= 0:
                            for child in div_children[heading_index+1:]:
                                if child.name in heading_tags:
                                    current_level = int(child.name[1])
                                    if current_level <= heading_level:
                                        break
                                
                                if child.name == 'pre' or child.name == 'code':
                                    code_examples.append(child.get_text(strip=True))
                                elif child.name:
                                    content.append(child.get_text(strip=True))
                                elif isinstance(child, str) and child.strip():
                                    content.append(child.strip())
                
                # Add the extracted content to results
                if content or code_examples:
                    results["matches"].append({
                        "heading": element_info["heading"],
                        "content": "\n".join(content),
                        "code_examples": code_examples,
                        "url": f"{api_doc_url}#{heading.get('id', '')}"
                    })
            
            # Check if we found any matches in the API reference
            if not results["matches"]:
                # Look for any element containing the class or function name
                for element in soup.find_all(['p', 'div', 'span', 'a']):
                    text = element.get_text().lower()
                    if query in text:
                        context_elements = []
                        
                        # Get some surrounding context
                        current = element.previous_sibling
                        for _ in range(3):  # Get up to 3 previous siblings
                            if current:
                                if current.name and current.get_text().strip():
                                    context_elements.insert(0, current.get_text().strip())
                                current = current.previous_sibling
                            else:
                                break
                        
                        # Add the matching element
                        context_elements.append(element.get_text().strip())
                        
                        # Get some following siblings
                        current = element.next_sibling
                        for _ in range(3):  # Get up to 3 next siblings
                            if current:
                                if current.name and current.get_text().strip():
                                    context_elements.append(current.get_text().strip())
                                current = current.next_sibling
                            else:
                                break
                        
                        if context_elements:
                            results["matches"].append({
                                "content": "\n".join(context_elements),
                                "url": api_doc_url,
                                "note": "Found in content but not as a specific API item"
                            })
                            break  # Just get the first meaningful match
            
            # Also check source code files in repository for the definition
            try:
                # Check key directories where API code is likely to be defined
                source_results = []
                api_source_dirs = ["src/agents", "src", "openai"]
                
                for dir_path in api_source_dirs:
                    try:
                        async with httpx.AsyncClient() as source_client:
                            response = await source_client.get(f"{GITHUB_URL}/tree/main/{dir_path}", timeout=10.0)
                            if response.status_code != 404:
                                response.raise_for_status()
                                
                                soup = BeautifulSoup(response.text, 'html.parser')
                                file_items = soup.select("div.Box-row")
                                
                                for item in file_items:
                                    link = item.select_one("a[data-pjax]")
                                    if not link:
                                        continue
                                        
                                    file_path = link.get("href", "").replace(f"/openai/openai-agents-python/blob/main/", "")
                                    if file_path.endswith(".py"):
                                        try:
                                            file_content = await fetch_github_file(file_path)
                                            
                                            # Look for class or function definition
                                            if f"class {class_or_function}" in file_content or f"def {class_or_function}" in file_content:
                                                # Process the file to extract just the relevant class/function definition
                                                lines = file_content.split('\n')
                                                definition_start = -1
                                                definition_end = -1
                                                
                                                # Find where the definition starts
                                                for i, line in enumerate(lines):
                                                    if f"class {class_or_function}" in line or f"def {class_or_function}" in line:
                                                        definition_start = i
                                                        break
                                                
                                                if definition_start >= 0:
                                                    # Extract definition and docstring
                                                    definition_content = []
                                                    indentation = len(lines[definition_start]) - len(lines[definition_start].lstrip())
                                                    
                                                    # Add the definition line
                                                    definition_content.append(lines[definition_start])
                                                    
                                                    # Add subsequent lines that are part of the definition (with deeper indentation)
                                                    i = definition_start + 1
                                                    while i < len(lines):
                                                        if lines[i].strip() == "" or len(lines[i]) - len(lines[i].lstrip()) > indentation:
                                                            definition_content.append(lines[i])
                                                            i += 1
                                                        else:
                                                            break
                                                    
                                                    source_results.append({
                                                        "source_file": file_path,
                                                        "url": f"{GITHUB_URL}/blob/main/{file_path}#L{definition_start+1}",
                                                        "definition": "\n".join(definition_content)
                                                    })
                                        except Exception:
                                            pass  # Skip files with errors
                    except Exception:
                        pass  # Skip directories with errors
                
                # Add source results to the main results
                if source_results:
                    results["source_code"] = source_results
                
            except Exception as e:
                results["source_error"] = str(e)
            
            # If we still didn't find anything, try searching documentation
            if not results["matches"] and "source_code" not in results:
                search_results = await search_docs(class_or_function)
                try:
                    doc_results = json.loads(search_results)
                    if not isinstance(doc_results, dict) or "error" not in doc_results:
                        results["documentation_search"] = doc_results
                except json.JSONDecodeError:
                    # If it's not JSON, just add the raw result
                    results["documentation_search"] = search_results
            
            # Return results
            if not results["matches"] and "source_code" not in results and "documentation_search" not in results:
                return json.dumps({
                    "error": f"Could not find API documentation for '{class_or_function}'. Try checking the full documentation or using a different search term.",
                    "query": class_or_function
                }, indent=2)
            
            return json.dumps(results, indent=2)
    
    except Exception as e:
        return f"Error retrieving API documentation: {str(e)}"

# Tool for getting GitHub file content
@mcp.tool()
async def get_github_file(path: str) -> str:
    """Get content of a specific file from the GitHub repository."""
    try:
        content = await fetch_github_file(path)
        return content
    except Exception as e:
        return f"Error retrieving GitHub file: {str(e)}"

# Tool for getting the index of documentation pages
@mcp.tool()
async def get_doc_index() -> str:
    """Get the index of all OpenAI Agents SDK documentation pages."""
    try:
        content = await fetch_doc_page(DOCS_URL)
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract links to documentation pages
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith(('http://', 'https://', '#', 'javascript:')):
                links.append({
                    'title': a.get_text(strip=True) or href,
                    'href': href
                })
        
        return json.dumps(links, indent=2)
    except Exception as e:
        return f"Error retrieving documentation index: {str(e)}"

# Tool for getting documentation content
@mcp.tool()
async def get_doc(path: str) -> str:
    """Get content of a specific documentation page."""
    try:
        if not path:
            return "Please provide a documentation page path."
            
        url = path if path.startswith('http') else urljoin(DOCS_URL, path)
        if not url.endswith('.html'):
            url = f"{url}.html"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 404:
                # Try to suggest alternative pages
                index_response = await client.get(DOCS_URL)
                index_response.raise_for_status()
                
                soup = BeautifulSoup(index_response.text, 'html.parser')
                available_pages = []
                
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if not href.startswith(('http://', 'https://', '#', 'javascript:')):
                        available_pages.append({
                            'title': a.get_text(strip=True) or href,
                            'href': href
                        })
                
                return json.dumps({
                    "error": f"Documentation page not found: {path}",
                    "available_pages": available_pages[:20]  # Limit to 20 suggestions
                }, indent=2)
                
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract the page title
            title = soup.find('title')
            page_title = title.get_text() if title else "Unknown Title"
            
            # Extract the main content
            main_content = soup.find('article') or soup.find('main') or soup.find('div', class_='markdown-body')
            if main_content:
                # Extract text content
                content = main_content.get_text(separator='\n', strip=True)
                
                # Find headings to provide structure information
                headings = []
                for tag in ['h1', 'h2', 'h3', 'h4']:
                    for heading in main_content.find_all(tag):
                        headings.append({
                            'level': int(tag[1]),
                            'text': heading.get_text(strip=True)
                        })
                
                # Extract code examples
                code_blocks = main_content.find_all('pre')
                code_examples = [block.get_text() for block in code_blocks]
                
                return json.dumps({
                    "title": page_title,
                    "url": url,
                    "content": content,
                    "structure": headings,
                    "code_examples": code_examples
                }, indent=2)
            else:
                content = soup.get_text(separator='\n', strip=True)
                return json.dumps({
                    "title": page_title,
                    "url": url,
                    "content": content,
                    "note": "Could not identify main content area, returning full page text."
                }, indent=2)
    except Exception as e:
        return f"Error retrieving documentation: {str(e)}"

# Tool for listing GitHub repository structure
@mcp.tool()
async def list_github_structure() -> str:
    """List the structure of the GitHub repository."""
    try:
        # Get the root structure
        root_structure = await get_github_structure()
        if "error" in root_structure:
            print(f"Error in root structure: {root_structure.get('error')}")
            
            # Even if there's an error, try default directories
            root_structure = {
                "files": [],
                "directories": [
                    {"name": "examples", "path": "examples"},
                    {"name": "src", "path": "src"},
                    {"name": "docs", "path": "docs"},
                    {"name": "tests", "path": "tests"}
                ]
            }
        
        full_structure = {
            "repository": "openai/openai-agents-python",
            "url": GITHUB_URL,
            "root": root_structure
        }
        
        # Check key directories to provide a more comprehensive view
        key_dirs = ["examples", "src", "docs", "tests"]
        dir_structures = {}
        errors = []
        
        # Process directories concurrently
        async def process_directory(dir_path, max_depth=2):
            try:
                if max_depth <= 0:
                    return {"note": "Max depth reached"}
                    
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{GITHUB_URL}/tree/main/{dir_path}", timeout=15.0)
                    if response.status_code == 404:
                        print(f"Directory not found: {dir_path}")
                        return {"error": f"Directory not found: {dir_path}"}
                    
                    response.raise_for_status()
                    html = response.text
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    structure = {
                        "files": [],
                        "directories": [],
                        "path": dir_path
                    }
                    
                    # Try multiple selectors for GitHub's file explorer rows
                    file_items = soup.select("div.Box-row") or soup.select("div[role='row']") or soup.select("tr.js-navigation-item")
                    subdirs = []
                    
                    if not file_items:
                        print(f"No file items found for {dir_path} using standard selectors. Trying alternative approach.")
                        # Let's look for any links that might be file/directory links
                        repo_content_area = soup.find("div", class_="repository-content") or soup.find("div", {"data-pjax": "#repo-content-pjax-container"})
                        if repo_content_area:
                            links = repo_content_area.find_all("a")
                            for link in links:
                                href = link.get("href", "")
                                if "/blob/main/" in href or "/tree/main/" in href:
                                    # Make sure the href is related to the current directory
                                    if f"/tree/main/{dir_path}/" in href or f"/blob/main/{dir_path}/" in href:
                                        is_dir = "/tree/main/" in href
                                        name = link.get_text(strip=True)
                                        
                                        # Extract the part after the current directory
                                        if is_dir:
                                            path = href.replace(f"/openai/openai-agents-python/tree/main/{dir_path}/", "")
                                            if path and "/" not in path:  # Only direct children
                                                full_path = f"{dir_path}/{path}"
                                                structure["directories"].append({"name": path, "path": full_path})
                                                subdirs.append(full_path)
                                        else:
                                            path = href.replace(f"/openai/openai-agents-python/blob/main/{dir_path}/", "")
                                            if path and "/" not in path:  # Only direct children
                                                full_path = f"{dir_path}/{path}"
                                                extension = path.split('.')[-1] if '.' in path else ""
                                                structure["files"].append({
                                                    "name": path,
                                                    "path": full_path,
                                                    "extension": extension,
                                                    "url": f"{GITHUB_URL}/blob/main/{full_path}"
                                                })
                    else:
                        # Process items found using standard selectors
                        for item in file_items:
                            try:
                                # Try multiple ways to detect directories vs files
                                svg = item.select_one("svg")
                                link = item.select_one("a[data-pjax]") or item.select_one("a[href*='/blob/main/']") or item.select_one("a[href*='/tree/main/']")
                                
                                if not link:
                                    # Try any link in the item
                                    link = item.select_one("a")
                                
                                if link:
                                    href = link.get("href", "")
                                    name = link.get_text(strip=True)
                                    
                                    # Determine if directory by SVG aria-label or href
                                    is_dir = False
                                    if svg and svg.get("aria-label"):
                                        is_dir = "directory" in svg.get("aria-label", "").lower() or "dir" in svg.get("aria-label", "").lower()
                                    elif href:
                                        is_dir = "/tree/main/" in href
                                    
                                    # Extract path properly for blob or tree
                                    item_path = ""
                                    if is_dir:
                                        # Directory - get path after the current directory
                                        item_path = href.replace(f"/openai/openai-agents-python/tree/main/", "")
                                    else:
                                        # File - get path after the current directory
                                        item_path = href.replace(f"/openai/openai-agents-python/blob/main/", "")
                                    
                                    # Make sure it's in the current directory
                                    if item_path.startswith(dir_path + "/"):
                                        rel_path = item_path.replace(dir_path + "/", "")
                                        if "/" not in rel_path:  # Only direct children
                                            if is_dir:
                                                structure["directories"].append({
                                                    "name": name,
                                                    "path": item_path
                                                })
                                                subdirs.append(item_path)
                                            else:
                                                # For files, include additional info like extension
                                                extension = name.split('.')[-1] if '.' in name else ""
                                                structure["files"].append({
                                                    "name": name,
                                                    "path": item_path,
                                                    "extension": extension,
                                                    "url": f"{GITHUB_URL}/blob/main/{item_path}"
                                                })
                            except Exception as e:
                                errors.append(f"Error processing item in {dir_path}: {str(e)}")
                    
                    # If we still don't have anything, add some default files for well-known directories
                    if not structure["files"] and not structure["directories"]:
                        if dir_path == "examples":
                            defaults = [
                                {"name": "basic_agent.py", "path": "examples/basic_agent.py", "extension": "py"},
                                {"name": "handoffs.py", "path": "examples/handoffs.py", "extension": "py"}
                            ]
                            structure["files"] = defaults
                            print(f"No files found in {dir_path}, adding default examples")
                        elif dir_path == "src":
                            structure["directories"] = [{"name": "agents", "path": "src/agents"}]
                            print(f"No files found in {dir_path}, adding default src structure")
                    
                    # Recursively process subdirectories up to max_depth
                    if max_depth > 1 and subdirs:
                        subdir_tasks = []
                        for subdir in subdirs:
                            subdir_tasks.append(process_directory(subdir, max_depth - 1))
                        
                        if subdir_tasks:
                            subdir_results = await asyncio.gather(*subdir_tasks, return_exceptions=True)
                            
                            # Process results
                            for i, result in enumerate(subdir_results):
                                if isinstance(result, dict):
                                    subdir_name = subdirs[i].split('/')[-1]
                                    # Find the directory in our structure and add the substructure
                                    for dir_info in structure["directories"]:
                                        if dir_info["name"] == subdir_name or dir_info["path"] == subdirs[i]:
                                            dir_info["contents"] = result
                                            break
                                elif isinstance(result, Exception):
                                    errors.append(f"Error processing subdirectory {subdirs[i]}: {str(result)}")
                    
                    return structure
            except Exception as e:
                print(f"Error processing directory {dir_path}: {str(e)}")
                return {"error": f"Error processing directory {dir_path}: {str(e)}"}
        
        # Process key directories concurrently
        tasks = []
        for dir_name in key_dirs:
            # Check if directory is in root, but process it anyway even if not found
            tasks.append(process_directory(dir_name))
        
        if tasks:
            dir_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for i, result in enumerate(dir_results):
                if isinstance(result, dict):
                    dir_structures[key_dirs[i]] = result
                elif isinstance(result, Exception):
                    errors.append(f"Error processing directory {key_dirs[i]}: {str(result)}")
        
        # Add directory structures to the full structure
        full_structure["directories"] = dir_structures
        
        if errors:
            full_structure["errors"] = errors
        
        # Include summary information
        summary = {
            "total_root_files": len(root_structure.get("files", [])),
            "total_root_directories": len(root_structure.get("directories", [])),
            "explored_directories": list(dir_structures.keys())
        }
        full_structure["summary"] = summary
        
        return json.dumps(full_structure, indent=2)
    except Exception as e:
        print(f"Error in list_github_structure: {str(e)}")
        return f"Error retrieving GitHub repository structure: {str(e)}"

# Prompt for exploring documentation
@mcp.prompt()
def explore_docs(topic: Optional[str] = None) -> str:
    """Create a prompt for exploring OpenAI Agents SDK documentation."""
    if topic:
        return f"Explore the OpenAI Agents SDK documentation for information about {topic}."
    else:
        return "Explore the OpenAI Agents SDK documentation. What would you like to learn about?"

# Add a new diagnostic tool to check the health of resources
@mcp.tool()
async def run_diagnostics() -> str:
    """Run diagnostics to check the health of the OpenAI Agents SDK documentation and GitHub repository."""
    try:
        results = {
            "diagnostics_run_at": str(datetime.datetime.now()),
            "documentation": {},
            "github": {},
            "cache": {},
            "overall_health": "unknown"
        }
        errors = []
        
        # Check documentation availability
        try:
            async with httpx.AsyncClient() as client:
                doc_response = await client.get(DOCS_URL, timeout=10.0)
                
                results["documentation"]["main_page"] = {
                    "status_code": doc_response.status_code,
                    "available": doc_response.status_code == 200,
                    "url": DOCS_URL
                }
                
                # Check key documentation pages
                key_pages = ["index.html", "api_reference.html", "get_started.html", "concepts.html"]
                page_results = []
                
                for page in key_pages:
                    try:
                        page_url = urljoin(DOCS_URL, page)
                        page_response = await client.get(page_url, timeout=10.0)
                        page_results.append({
                            "page": page,
                            "url": page_url,
                            "status_code": page_response.status_code,
                            "available": page_response.status_code == 200
                        })
                    except Exception as e:
                        page_results.append({
                            "page": page,
                            "url": urljoin(DOCS_URL, page),
                            "error": str(e),
                            "available": False
                        })
                
                results["documentation"]["key_pages"] = page_results
                
                # Calculate documentation health
                available_pages = sum(1 for page in page_results if page.get("available", False))
                results["documentation"]["health"] = {
                    "available_pages": available_pages,
                    "total_checked": len(key_pages),
                    "status": "good" if available_pages == len(key_pages) else 
                              "degraded" if available_pages > 0 else "down"
                }
        except Exception as e:
            results["documentation"]["error"] = str(e)
            results["documentation"]["health"] = {"status": "unknown", "error": str(e)}
            errors.append(f"Documentation check error: {str(e)}")
        
        # Check GitHub repository availability
        try:
            async with httpx.AsyncClient() as client:
                github_response = await client.get(GITHUB_URL, timeout=10.0)
                
                results["github"]["main_page"] = {
                    "status_code": github_response.status_code,
                    "available": github_response.status_code == 200,
                    "url": GITHUB_URL
                }
                
                # Check key repository sections
                key_sections = ["tree/main/examples", "tree/main/src", "tree/main/docs"]
                section_results = []
                
                for section in key_sections:
                    try:
                        section_url = f"{GITHUB_URL}/{section}"
                        section_response = await client.get(section_url, timeout=10.0)
                        section_results.append({
                            "section": section,
                            "url": section_url,
                            "status_code": section_response.status_code,
                            "available": section_response.status_code == 200
                        })
                    except Exception as e:
                        section_results.append({
                            "section": section,
                            "url": f"{GITHUB_URL}/{section}",
                            "error": str(e),
                            "available": False
                        })
                
                results["github"]["key_sections"] = section_results
                
                # Calculate GitHub health
                available_sections = sum(1 for section in section_results if section.get("available", False))
                results["github"]["health"] = {
                    "available_sections": available_sections,
                    "total_checked": len(key_sections),
                    "status": "good" if available_sections == len(key_sections) else 
                              "degraded" if available_sections > 0 else "down"
                }
                
                # Check raw GitHub access
                try:
                    raw_response = await client.get(f"{RAW_GITHUB_URL}README.md", timeout=10.0)
                    results["github"]["raw_access"] = {
                        "status_code": raw_response.status_code,
                        "available": raw_response.status_code == 200,
                        "url": f"{RAW_GITHUB_URL}README.md"
                    }
                except Exception as e:
                    results["github"]["raw_access"] = {
                        "error": str(e),
                        "available": False,
                        "url": f"{RAW_GITHUB_URL}README.md"
                    }
        except Exception as e:
            results["github"]["error"] = str(e)
            results["github"]["health"] = {"status": "unknown", "error": str(e)}
            errors.append(f"GitHub check error: {str(e)}")
        
        # Check cache status
        results["cache"] = {
            "doc_cache_entries": len(doc_cache),
            "github_cache_entries": len(github_cache)
        }
        
        # Determine overall health
        doc_status = results["documentation"].get("health", {}).get("status", "unknown")
        github_status = results["github"].get("health", {}).get("status", "unknown")
        
        if doc_status == "good" and github_status == "good":
            overall_health = "good"
        elif doc_status == "down" and github_status == "down":
            overall_health = "down"
        elif doc_status == "unknown" and github_status == "unknown":
            overall_health = "unknown"
        else:
            overall_health = "degraded"
        
        results["overall_health"] = overall_health
        
        if errors:
            results["errors"] = errors
        
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error running diagnostics: {str(e)}"

# Run the server
if __name__ == "__main__":
    # Initialize and run the server
    mcp.run()