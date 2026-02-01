from typing import Any, Dict
from app.db import LocalSearchDB

def execute_search_symbols(args: Dict[str, Any], db: LocalSearchDB) -> Dict[str, Any]:
    """
    Execute search_symbols tool.
    
    Args:
        args: {"query": str, "limit": int}
        db: LocalSearchDB instance
    """
    query = args.get("query", "")
    limit = args.get("limit", 20)
    
    results = db.search_symbols(query, limit=limit)
    
    if not results:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"No symbols found matching '{query}'"
                }
            ]
        }
        
    # Format output
    lines = []
    lines.append(f"Found {len(results)} symbols matching '{query}':\n")
    
    current_repo = None
    for r in results:
        if r["repo"] != current_repo:
            current_repo = r["repo"]
            lines.append(f"\n📁 Repository: {current_repo}")
            
        lines.append(f"- [{r['kind']}] {r['name']} ({r['path']}:{r['line']})")
        lines.append(f"  Snippet: {r['snippet']}")
        
    return {
        "content": [
            {
                "type": "text",
                "text": "\n".join(lines)
            }
        ]
    }
