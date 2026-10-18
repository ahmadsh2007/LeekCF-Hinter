"""Hand-written HTML shaped like a Codeforces problem page, for offline tests."""
from bs4 import BeautifulSoup

DEFAULT_SAMPLES = """
<div class="sample-tests">
  <div class="section-title">Examples</div>
  <div class="sample-test">
    <div class="input"><div class="title">Input</div><pre>1
2</pre></div>
    <div class="output"><div class="title">Output</div><pre>3</pre></div>
  </div>
</div>
"""

def buildPage(
    timeLimit="2 seconds",
    memoryLimit="256 megabytes",
    statementDiv='<div><p>You are given $$$n$$$ integers.</p><p>Second paragraph.</p></div>',
    inputSection='<div class="input-specification"><div class="section-title">Input</div><p>The first line contains $$$n$$$.</p></div>',
    outputSection='<div class="output-specification"><div class="section-title">Output</div><p>Print the answer.</p></div>',
    interactionSection="",
    samples=DEFAULT_SAMPLES,
    note='<div class="note"><div class="section-title">Note</div><p>In the first sample, ...</p></div>',
    header=None,
    outside="",
) -> BeautifulSoup:
    if header is None:
        header = f"""
        <div class="header">
          <div class="title">A. Foo</div>
          <div class="time-limit"><div class="property-title">time limit per test</div>{timeLimit}</div>
          <div class="memory-limit"><div class="property-title">memory limit per test</div>{memoryLimit}</div>
        </div>"""
    html = f"""
    <html><body>
      <div class="problem-statement">
        {header}
        {statementDiv}
        {inputSection}
        {outputSection}
        {interactionSection}
        {samples}
        {note}
      </div>
      {outside}
    </body></html>"""
    return BeautifulSoup(html, "html.parser")
