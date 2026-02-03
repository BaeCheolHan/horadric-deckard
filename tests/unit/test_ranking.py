import time

from app import ranking


def test_glob_to_like():
    assert ranking.glob_to_like("") == "%"
    assert ranking.glob_to_like("foo") == "%foo%"
    assert ranking.glob_to_like("**/*.py").startswith("%")
    assert ranking.glob_to_like("src/**").endswith("%")


def test_get_file_extension():
    assert ranking.get_file_extension("a/b/c.py") == "py"
    assert ranking.get_file_extension("a/b/c") == ""


def test_calculate_recency_score():
    now = time.time()
    assert ranking.calculate_recency_score(now - 3600, 1.0) > 1.0
    assert ranking.calculate_recency_score(now - 10 * 86400, 1.0) > 1.0
    assert ranking.calculate_recency_score(now - 40 * 86400, 1.0) >= 1.0


def test_extract_terms():
    q = '"Hello World" author:Bob AND foo'
    terms = ranking.extract_terms(q)
    assert "Hello World" in terms
    assert "Bob" in terms
    assert "foo" in terms


def test_count_matches():
    content = "Hello HELLO hello"
    assert ranking.count_matches(content, "hello", use_regex=False, case_sensitive=False) == 3
    assert ranking.count_matches(content, "HELLO", use_regex=False, case_sensitive=True) == 1
    assert ranking.count_matches(content, "(hello", use_regex=True, case_sensitive=False) == 0


def test_snippet_around():
    content = "one\nTwo\nthree\nfour"
    snippet = ranking.snippet_around(content, ["two"], max_lines=2)
    assert "L2:" in snippet

    snippet = ranking.snippet_around(content, [], max_lines=2)
    assert snippet.startswith("L1:")

    snippet = ranking.snippet_around("", ["x"], max_lines=2)
    assert snippet == ""
