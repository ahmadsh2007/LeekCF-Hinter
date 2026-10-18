import re
from bs4 import BeautifulSoup, NavigableString, Tag
from src.utils.htmlText import extractText

BASE_URL = "https://codeforces.com"
# A section shorter than this (after credits are dropped) is a pointer or a credit line, not a tutorial.
MIN_TUTORIAL_CHARS = 80
MAX_CREDIT_LINE_CHARS = 160

BLOG_ENTRY_LINK = re.compile(r"/blog/entry/(\d+)")
TUTORIAL_LABEL = re.compile(r"tutorial|editorial", re.IGNORECASE)
PROBLEM_LINK = re.compile(r"/(?:contest|problemset/problem)/(\d+)/(?:problem/)?([A-Za-z]\d{0,2})/?(?:[?#].*)?$")
PROBLEM_CODE = re.compile(r"^(\d+)([A-Za-z]\d{0,2})$")
CREDIT_LINE = re.compile(r"^(?:problem\s+)?(?:ideas?|authors?|preparation|prepared(?:\s+by)?|developed(?:\s+by)?|editorial)\s*[:：]", re.IGNORECASE)
WHITESPACE_RUNS = re.compile(r"\s+")

def collapse(text: str) -> str:
    return WHITESPACE_RUNS.sub(" ", text).strip()

def findTutorialLinks(contestPage: BeautifulSoup) -> list[str]:
    """Tutorial/Editorial links of a contest page's "Contest materials" box, English first, then page order."""
    found: list[tuple[int, int, str]] = []
    position = 0
    for box in contestPage.select(".roundbox"):
        caption = box.select_one(".caption")
        if not caption or "Contest materials" not in caption.get_text():
            continue
        for anchor in box.find_all("a", href=True):
            entry = BLOG_ENTRY_LINK.search(anchor["href"])
            label = collapse(anchor.get_text())
            if entry and TUTORIAL_LABEL.search(label):
                notEnglish = 0 if "(en)" in label.lower() else 1
                found.append((notEnglish, position, f"{BASE_URL}/blog/entry/{entry.group(1)}"))
                position += 1

    urls: list[str] = []
    for _, _, url in sorted(found):
        if url not in urls:
            urls.append(url)
    return urls

def problemKeyFromHref(href: str) -> str | None:
    """'/contest/1944/problem/A' -> '1944_A' (the id format of the problems table)."""
    match = PROBLEM_LINK.search(href)
    return f"{match.group(1)}_{match.group(2).upper()}" if match else None

def findCsrfToken(page: BeautifulSoup) -> str | None:
    meta = page.select_one('meta[name="X-Csrf-Token"]')
    return meta["content"] if meta and meta.get("content") else None

def findPostBody(blogPage: BeautifulSoup) -> Tag | None:
    return blogPage.select_one(".topic .content .ttypography")

def findDynamicTutorials(blogPage: BeautifulSoup) -> dict[str, str]:
    """Placeholders Codeforces fills in with a script: problem key -> the problem code to ask the data endpoint for."""
    body = findPostBody(blogPage)
    dynamic: dict[str, str] = {}
    for placeholder in (body.select(".problemTutorial") if body else []):
        code = placeholder.get("problemcode", "")
        match = PROBLEM_CODE.match(code)
        if match:
            dynamic[f"{match.group(1)}_{match.group(2).upper()}"] = code
    return dynamic

def withoutCode(root: Tag) -> None:
    """Drops what hints do not need (code listings, scripts, the dynamic placeholders) and any spoiler left empty."""
    for tag in root.find_all(["pre", "script", "style"]):
        tag.decompose()
    for tag in root.select(".problemTutorial"):
        tag.decompose()
    for title in root.select(".spoiler-title"):
        if not title.get_text().rstrip().endswith(":"):
            title.append(NavigableString(":"))
    # Children first, so a decomposed parent never has to be revisited.
    for spoiler in reversed(root.select(".spoiler")):
        content = spoiler.select_one(".spoiler-content")
        if content is None or not content.get_text(strip=True):
            spoiler.decompose()

def headerKey(block: Tag) -> str | None:
    """A block opens a problem's section when it *starts* with the link to that problem."""
    if block.name in ("ul", "ol") or "spoiler" in block.get("class", []):
        return None
    for anchor in block.find_all("a", href=True):
        key = problemKeyFromHref(anchor["href"])
        if key:
            anchorText = collapse(anchor.get_text())
            return key if anchorText and collapse(block.get_text()).startswith(anchorText) else None
    return None

def renderBlocks(blocks: list[Tag]) -> str:
    wrapper = BeautifulSoup("<div></div>", "html.parser").div
    for block in blocks:
        wrapper.append(block.extract())
    return extractText(wrapper)

def isCreditLine(block: Tag) -> bool:
    text = collapse(block.get_text())
    return len(text) <= MAX_CREDIT_LINE_CHARS and bool(CREDIT_LINE.match(text))

def splitBlogIntoSections(blogPage: BeautifulSoup) -> dict[str, str]:
    """Problem key -> tutorial text, for the sections of a post that are written out in the page itself."""
    original = findPostBody(blogPage)
    if original is None:
        return {}
    body = BeautifulSoup(str(original), "html.parser")
    withoutCode(body)

    sectionBlocks: dict[str, list[list[Tag]]] = {}
    currentKey: str | None = None
    current: list[Tag] = []
    for block in [child for child in body.find("div").children if isinstance(child, Tag)]:
        key = headerKey(block)
        if key:
            currentKey = key
            current = []
            sectionBlocks.setdefault(key, []).append(current)
        elif currentKey:
            current.append(block)

    sections: dict[str, str] = {}
    for key, parts in sectionBlocks.items():
        texts = []
        for blocks in parts:
            while blocks and isCreditLine(blocks[0]):
                blocks.pop(0)
            text = renderBlocks(blocks)
            if text:
                texts.append(text)
        joined = "\n\n".join(texts)
        if len(joined) >= MIN_TUTORIAL_CHARS:
            sections[key] = joined
    return sections

def parseDynamicTutorial(htmlFragment: str) -> str:
    """Text of what the data endpoint returns for one problem (a title plus the tutorial body)."""
    fragment = BeautifulSoup(htmlFragment, "html.parser")
    for title in fragment.find_all("h3"):
        title.decompose()
    withoutCode(fragment)
    return extractText(fragment)
