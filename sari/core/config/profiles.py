from typing import Dict, List, Set, Any
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Profile:
    name: str
    extensions: Set[str] = field(default_factory=set)
    filenames: Set[str] = field(default_factory=set)
    globs: List[str] = field(default_factory=list)
    detect_files: List[str] = field(default_factory=list)

PROFILES: Dict[str, Profile] = {
    "core": Profile(
        name="core",
        extensions={".md", ".mdx", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties"},
        filenames={".env", "Makefile", "Dockerfile"},
        globs=[".env.*"]
    ),
    "web": Profile(
        name="web",
        extensions={".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".less", ".vue", ".svelte", ".astro", ".graphql", ".gql"},
        filenames={"package.json", "tsconfig.json", "webpack.config.js", "next.config.js"},
        detect_files=["package.json", "tsconfig.json", "vite.config.*", "webpack.config.*"]
    ),
    "python": Profile(
        name="python",
        extensions={".py", ".pyi", ".ipynb"},
        filenames={"pyproject.toml", "requirements.txt", "Pipfile", "setup.py"},
        detect_files=["pyproject.toml", "requirements.txt", "Pipfile", "setup.py"]
    ),
    "java": Profile(
        name="java",
        extensions={".java", ".kt", ".kts", ".gradle", ".xml"},
        filenames={"pom.xml", "build.gradle", "settings.gradle", "gradle.properties"},
        detect_files=["pom.xml", "build.gradle", "settings.gradle"]
    ),
    "go": Profile(
        name="go",
        extensions={".go"},
        filenames={"go.mod", "go.sum"},
        detect_files=["go.mod"]
    ),
    "rust": Profile(
        name="rust",
        extensions={".rs"},
        filenames={"Cargo.toml", "Cargo.lock"},
        detect_files=["Cargo.toml"]
    ),
    "cpp": Profile(
        name="cpp",
        extensions={".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx"},
        filenames={"CMakeLists.txt"},
        detect_files=["CMakeLists.txt", "meson.build"]
    ),
    "infra": Profile(
        name="infra",
        extensions={".tf", ".tfvars", ".hcl", ".yaml", ".yml"},
        filenames={"Dockerfile", "docker-compose.yml"},
        detect_files=["Dockerfile", "docker-compose.yml", "*.tf", "*.tfvars"]
    ),
    # Add more as per docs/reference/ARCHITECTURE.md...
}
