# rag_search.py
import os
from tavily import TavilyClient

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web using Tavily and return formatted text for LLM
    """
    try:
        response = tavily.search(
            query=query,
            max_results=max_results,
            search_depth="basic"
        )

        if not response.get("results"):
            return "No relevant web results found."

        formatted = "Web search results:\n"
        for i, result in enumerate(response["results"], 1):
            formatted += f"{i}. {result['title']}\n"
            formatted += f"   {result['content']}\n"

        return formatted

    except Exception as e:
        return f"Web search failed: {str(e)}"
