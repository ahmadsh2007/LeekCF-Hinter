import re
from bs4 import Comment, NavigableString, Tag

# Elements that start a new paragraph. Everything else (spans, <i>, <b>, <a>, <code>, ...) stays inside its sentence.
BLOCK_TAGS = {"p", "div", "center", "table", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
LIST_TAGS = {"ul", "ol"}
SKIPPED_TAGS = {"script", "style"}

WHITESPACE_RUNS = re.compile(r"\s+")

def scriptText(element: Tag, marker: str) -> str:
    text = renderChildren(element).strip()
    return f"{marker}{{{text}}}" if len(text) > 1 else f"{marker}{text}"

def renderChildren(element: Tag) -> str:
    return "".join(renderInline(child) for child in element.children)

def renderInline(node) -> str:
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        # Line breaks in the HTML source are just spaces; only <br> starts a new line.
        return WHITESPACE_RUNS.sub(" ", str(node))
    if node.name in SKIPPED_TAGS:
        return ""
    if node.name == "br":
        return "\n"
    if node.name == "sub":
        return scriptText(node, "_")
    if node.name == "sup":
        return scriptText(node, "^")

    inner = renderChildren(node)
    if "tex-span" in node.get("class", []):
        return f"$$${inner.strip()}$$$"
    return inner

def tidyParagraph(text: str) -> str:
    # A run that contains <br> line breaks keeps them (at most one blank line); any other run is one space.
    text = WHITESPACE_RUNS.sub(lambda run: "\n" * min(run.group().count("\n"), 2) or " ", text)
    return text.strip()

def renderList(listElement: Tag) -> str:
    lines = []
    for position, item in enumerate(listElement.find_all("li", recursive=False), start=1):
        bullet = f"{position}." if listElement.name == "ol" else "-"
        lines.append(f"{bullet} {tidyParagraph(renderInline(item))}")
    return "\n".join(lines)

def renderBlocks(element: Tag) -> list[str]:
    blocks: list[str] = []
    pendingInline: list[str] = []

    def flushInline():
        text = tidyParagraph("".join(pendingInline))
        pendingInline.clear()
        if text:
            blocks.append(text)

    for child in element.children:
        if isinstance(child, Tag) and child.name in LIST_TAGS:
            flushInline()
            blocks.append(renderList(child))
        elif isinstance(child, Tag) and child.name == "pre":
            flushInline()
            blocks.append(child.get_text().strip("\n"))
        elif isinstance(child, Tag) and child.name in BLOCK_TAGS:
            flushInline()
            blocks.extend(renderBlocks(child))
        else:
            pendingInline.append(renderInline(child))

    flushInline()
    return [block for block in blocks if block.strip()]

def extractText(element: Tag) -> str:
    """
    Plain text of a statement section. Paragraphs are separated by a blank line, list items get a bullet or
    number, and inline markup never splits a sentence. Math is kept as LaTeX: modern pages already contain
    $$$...$$$ in their text, and old pages that render math as HTML spans are rewritten into the same form.
    """
    return "\n\n".join(renderBlocks(element))
