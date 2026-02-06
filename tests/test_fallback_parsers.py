import os
import sys
from pathlib import Path
from sari.core.parsers.factory import ParserFactory

def test_js_arrow_functions():
    js_code = """
    class MyServer {
        doSomething() { }
    }
    const myArrow = (a, b) => { return a + b; };
    let asyncArrow = async () => { };
    var legacyFunc = function(x) { };
    """
    parser = ParserFactory.get_parser(".js")
    symbols, _ = parser.extract("test.js", js_code)
    
    names = [s[1] for s in symbols]
    assert "MyServer" in names
    assert "doSomething" in names
    assert "myArrow" in names
    assert "asyncArrow" in names
    assert "legacyFunc" in names

def test_rust_traits():
    rs_code = """
    struct Point { x: i32, y: i32 }
    trait Drawable { fn draw(&self); }
    impl Drawable for Point {
        fn draw(&self) { }
    }
    fn global_fn() { }
    """
    parser = ParserFactory.get_parser(".rs")
    symbols, _ = parser.extract("test.rs", rs_code)
    
    names = [s[1] for s in symbols]
    assert "Point" in names
    assert "Drawable" in names
    assert "draw" in names
    assert "global_fn" in names

def test_comment_stripping():
    code = """
    class RealClass {
        // class FakeInComment { }
        /* 
           fn fake_in_block() { }
        */
        void realMethod() { }
    }
    """
    parser = ParserFactory.get_parser(".java")
    symbols, _ = parser.extract("test.java", code)
    
    names = [s[1] for s in symbols]
    assert "RealClass" in names
    assert "realMethod" in names
    assert "FakeInComment" not in names
    assert "fake_in_block" not in names


def test_vue_script_symbols():
    vue_code = """
    <template><div>Hello</div></template>
    <script>
    export default {
      methods: {
        onClick() { return true; }
      }
    }
    const helper = () => 1;
    function boot() { return helper(); }
    </script>
    """
    parser = ParserFactory.get_parser(".vue")
    symbols, _ = parser.extract("Comp.vue", vue_code)
    names = [s[1] for s in symbols]
    assert "Comp" in names
    assert "onClick" in names
    assert "helper" in names
    assert "boot" in names


def test_java_annotation_without_group1_does_not_crash():
    java_code = """
    @RestController
    @Tag(name = "api")
    public class DemoController {
        @GetMapping("/demo")
        public String ping() { return "ok"; }
    }
    """
    parser = ParserFactory.get_parser(".java")
    symbols, _ = parser.extract("DemoController.java", java_code)
    names = [s[1] for s in symbols]
    assert "DemoController" in names
    assert "ping" in names

if __name__ == "__main__":
    test_js_arrow_functions()
    test_rust_traits()
    test_comment_stripping()
    print("All fallback accuracy tests PASSED!")
