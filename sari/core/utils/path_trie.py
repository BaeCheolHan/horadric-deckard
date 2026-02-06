import os
from typing import List, Optional

class PathTrie:
    """
    A Trie (Prefix Tree) specialized for filesystem paths.
    Provides O(L) path lookup where L is the depth of the path.
    """
    def __init__(self):
        self.root = {}

    def insert(self, path: str):
        """Insert a normalized absolute path into the trie."""
        if not path: return
        parts = path.strip(os.sep).split(os.sep)
        node = self.root
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]
        node["__end__"] = True

    def find_most_specific_prefix(self, path: str) -> Optional[str]:
        """
        Finds the longest path in the trie that is a prefix of the given path.
        Returns the prefix path or None.
        """
        if not path: return None
        parts = path.strip(os.sep).split(os.sep)
        node = self.root
        prefix_parts = []
        last_found = None
        
        for part in parts:
            if part in node:
                prefix_parts.append(part)
                node = node[part]
                if "__end__" in node:
                    last_found = os.sep + os.sep.join(prefix_parts)
            else:
                break
        
        return last_found

    def has_child_workspace(self, parent_path: str) -> bool:
        """
        Checks if there are any paths in the trie that are children of parent_path.
        Used to detect if a directory scan should be delegated to a sub-workspace.
        """
        if not parent_path: return False
        parts = parent_path.strip(os.sep).split(os.sep)
        node = self.root
        
        # Traverse to the node representing parent_path
        for part in parts:
            if part in node:
                node = node[part]
            else:
                return False # Parent path not even in trie
        
        # If the node has any children other than __end__, it has sub-workspaces
        return len([k for k in node.keys() if k != "__end__"]) > 0

    def is_path_owned_by_sub_workspace(self, current_path: str, owner_root: str) -> bool:
        """
        Algorithm:
        1. Traverse the Trie with current_path.
        2. If we find an __end__ marker that is NOT the owner_root, 
           it means another workspace owns this path.
        """
        if not current_path: return False
        parts = current_path.strip(os.sep).split(os.sep)
        owner_parts = owner_root.strip(os.sep).split(os.sep)
        
        node = self.root
        current_traversed = []
        for part in parts:
            if part in node:
                current_traversed.append(part)
                node = node[part]
                if "__end__" in node:
                    # Found a workspace boundary
                    if len(current_traversed) > len(owner_parts):
                        # It's deeper than the current owner -> it's a sub-workspace
                        return True
            else:
                break
        return False
