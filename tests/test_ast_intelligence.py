import pytest
import json
from sari.core.parsers.ast_engine import ASTEngine

def test_java_annotation_extraction():
    """
    Verify that the modernized AST engine extracts Spring annotations.
    """
    engine = ASTEngine()
    code = (
        "@RestController\n"
        "@RequestMapping(\"/api\")\n"
        "public class MyController {\n"
        "    @GetMapping(\"/hello\")\n"
        "    public String sayHello() {\n"
        "        return \"world\";\n"
        "    }\n"
    "}\n"
    )
    # --- FIX: UNPACK PROPERLY ---
    symbols, _ = engine.extract_symbols("MyController.java", "java", code)
    
    # 2. Verify Class Annotation
    # Find symbol by name substring to be more resilient
    cls_symbol = next((s for s in symbols if "MyController" in s[1]), None)
    assert cls_symbol is not None, f"MyController not found in {symbols}"
    
    metadata = json.loads(cls_symbol[7])
    assert "RestController" in metadata["annotations"]
    assert "RequestMapping" in metadata["annotations"]
    
    # 3. Verify Method Annotation
    func_symbol = next((s for s in symbols if "sayHello" in s[1]), None)
    assert func_symbol is not None, f"sayHello not found in {symbols}"
    
    func_meta = json.loads(func_symbol[7])
    assert "GetMapping" in func_meta["annotations"]

def test_python_decorator_extraction():
    """
    Verify that decorators in Python are also correctly captured.
    """
    engine = ASTEngine()
    code = (
        "@app.route(\"/\")\n"
        "@login_required\n"
        "def index():\n"
        "    pass\n"
    )
    # --- FIX: UNPACK PROPERLY ---
    symbols, _ = engine.extract_symbols("app.py", "python", code)
    
    # Priority Fix: Look for partial match if needed
    idx_symbol = next((s for s in symbols if "index" in s[1]), None)
    assert idx_symbol is not None
    
    metadata = json.loads(idx_symbol[7])
    # Note: PythonHandler might store decorators differently, checking all annotations
    assert any("login_required" in a for f in metadata.get("annotations", []) for a in (f if isinstance(f, list) else [f]))
    assert any("route" in a for f in metadata.get("annotations", []) for a in (f if isinstance(f, list) else [f]))