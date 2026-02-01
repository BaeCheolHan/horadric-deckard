from typing import Any, Dict
from app.db import LocalSearchDB

def execute_read_file(args: Dict[str, Any], db: LocalSearchDB) -> Dict[str, Any]:
    """
    Execute read_file tool.
    
    Args:
        args: {"path": str}
        db: LocalSearchDB instance
    """
    path = args.get("path")
    if not path:
        return {"content": [{"type": "text", "text": "Error: 'path' is required"}]}
        
    content = db.read_file(path)
    if content is None:
        return {"content": [{"type": "text", "text": f"Error: File not found or not indexed: {path}"}]}
        
    return {
        "content": [
            {
                "type": "text", 
                "text": content
            }
        ]
    }
