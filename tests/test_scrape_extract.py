from tools.scrape_tool import _extract_body


def test_extract_body_prefers_main() -> None:
    html = """
    <html><body>
      <header>nav stuff</header>
      <main><h1>Title</h1><p>This is the main content block with enough text.</p></main>
      <footer>footer</footer>
    </body></html>
    """
    out = _extract_body(html)
    assert "main content block" in out
    assert "nav stuff" not in out


def test_extract_body_removes_scripts_and_styles() -> None:
    html = """
    <html><body>
      <script>var x = 1;</script>
      <style>.x{color:red}</style>
      <div>This is the content with enough text to pass the heuristic threshold. It is long enough.</div>
    </body></html>
    """
    out = _extract_body(html)
    assert "var x" not in out
    assert "color:red" not in out
    assert "content with enough text" in out

