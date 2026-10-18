import unittest

from bs4 import BeautifulSoup

from src.workers.tutorial_finder.tutorialParser import (
    MIN_TUTORIAL_CHARS,
    findCsrfToken,
    findDynamicTutorials,
    findTutorialLinks,
    parseDynamicTutorial,
    problemKeyFromHref,
    splitBlogIntoSections,
)

def soupOf(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")

def materialsBox(*links: tuple[str, str, str]) -> str:
    items = "".join(
        f'<li><span><a href="{href}" target="_blank">{label}'
        + (f' <span class="resource-locale">({locale})</span>' if locale else "")
        + "</a></span></li>"
        for href, label, locale in links
    )
    return f'<div class="roundbox sidebox"><div class="caption titled">→ Contest materials <div class="top-links"></div></div><ul>{items}</ul></div>'


class TutorialLinkTests(unittest.TestCase):
    def test_finds_the_tutorial_and_ignores_the_announcement(self):
        page = soupOf(materialsBox(("/blog/entry/10", "Announcement", "en"), ("/blog/entry/11", "Tutorial", "en")))
        self.assertEqual(findTutorialLinks(page), ["https://codeforces.com/blog/entry/11"])

    def test_editorial_wording_counts_too(self):
        page = soupOf(materialsBox(("/blog/entry/12", "Editorial", "")))
        self.assertEqual(findTutorialLinks(page), ["https://codeforces.com/blog/entry/12"])

    def test_english_links_come_first_then_page_order(self):
        page = soupOf(materialsBox(
            ("/blog/entry/21", "Tutorial", "ru"),
            ("/blog/entry/22", "Tutorial", "en"),
            ("/blog/entry/23", "Tutorial", ""),
        ))
        self.assertEqual(findTutorialLinks(page), [
            "https://codeforces.com/blog/entry/22",
            "https://codeforces.com/blog/entry/21",
            "https://codeforces.com/blog/entry/23",
        ])

    def test_the_same_post_linked_twice_is_returned_once(self):
        page = soupOf(materialsBox(("/blog/entry/31", "Tutorial", "en"), ("/blog/entry/31", "Tutorial", "")))
        self.assertEqual(findTutorialLinks(page), ["https://codeforces.com/blog/entry/31"])

    def test_only_the_contest_materials_box_is_read(self):
        other = ('<div class="roundbox"><div class="caption">→ Recent actions</div>'
                 '<a href="/blog/entry/99">Tutorial for something else</a></div>')
        self.assertEqual(findTutorialLinks(soupOf(other)), [])

    def test_no_tutorial_yet(self):
        page = soupOf(materialsBox(("/blog/entry/10", "Announcement", "en")))
        self.assertEqual(findTutorialLinks(page), [])


class ProblemKeyTests(unittest.TestCase):
    def test_contest_style_links(self):
        self.assertEqual(problemKeyFromHref("/contest/1944/problem/A"), "1944_A")
        self.assertEqual(problemKeyFromHref("https://codeforces.com/contest/1943/problem/D1"), "1943_D1")

    def test_problemset_style_links(self):
        self.assertEqual(problemKeyFromHref("/problemset/problem/1800/C2"), "1800_C2")

    def test_other_links_are_not_problems(self):
        for href in ("/profile/someone", "/blog/entry/5", "/gym/100/problem/A", "/contest/1944", "/contest/1944/standings"):
            self.assertIsNone(problemKeyFromHref(href), href)


FILLER = " This explanation is long enough to count as real content for the section filter."

def blog(inner: str) -> BeautifulSoup:
    return soupOf(f'<html><body><div class="topic"><div class="content"><div class="ttypography">{inner}</div></div></div></body></html>')

def spoiler(title: str, body: str) -> str:
    return f'<div class="spoiler"><b class="spoiler-title">{title}</b><div class="spoiler-content" style="display: none;">{body}</div></div>'

def header(contestId: int, index: str, name: str = "Name") -> str:
    return f'<p><a href="/contest/{contestId}/problem/{index}">{contestId}{index} - {name}</a></p>'


class SectionSplitTests(unittest.TestCase):
    def test_sections_are_cut_at_problem_headers_and_skip_the_intro(self):
        page = blog(
            "<p>Sorry for the delay.</p>"
            + header(1944, "A") + spoiler("Hint 1", f"<p>Count the bridges.{FILLER}</p>") + spoiler("Solution", "<p>Burn $$$i$$$ of them.</p>")
            + header(1943, "A") + spoiler("Hint 1", f"<p>Alice can adapt.{FILLER}</p>")
        )
        sections = splitBlogIntoSections(page)
        self.assertEqual(sorted(sections), ["1943_A", "1944_A"])
        self.assertEqual(sections["1944_A"], f"Hint 1:\n\nCount the bridges.{FILLER}\n\nSolution:\n\nBurn $$$i$$$ of them.")
        self.assertEqual(sections["1943_A"], f"Hint 1:\n\nAlice can adapt.{FILLER}")
        self.assertNotIn("Sorry", sections["1944_A"])

    def test_code_blocks_and_the_spoilers_that_only_held_code_are_dropped(self):
        page = blog(
            header(1, "A") + f"<p>Plain explanation.{FILLER}</p>"
            + spoiler("Code", "<pre><code>int main(){}</code></pre>")
            + spoiler("Solution", f"<p>Use a loop.</p><pre>for(;;);</pre>")
        )
        text = splitBlogIntoSections(page)["1_A"]
        self.assertNotIn("int main", text)
        self.assertNotIn("for(;;)", text)
        self.assertNotIn("Code:", text)
        self.assertIn("Solution:\n\nUse a loop.", text)

    def test_a_link_inside_a_sentence_does_not_start_a_section(self):
        page = blog(
            header(1, "A") + f"<p>This is like <a href=\"/contest/9/problem/B\">9B - Other</a> in spirit.{FILLER}</p>"
        )
        self.assertEqual(list(splitBlogIntoSections(page)), ["1_A"])

    def test_a_credit_line_right_after_the_header_is_not_content(self):
        page = blog(header(1, "A") + "<p>Idea: someone, Preparation: someone else</p>" + f"<p>Real text.{FILLER}</p>")
        self.assertEqual(splitBlogIntoSections(page)["1_A"], f"Real text.{FILLER}")

    def test_a_section_with_only_credits_is_not_a_tutorial(self):
        page = blog(header(1, "A") + "<p>Idea: someone Preparation: someone else Editorial: a third person</p>" + header(1, "B") + f"<p>Text.{FILLER}</p>")
        self.assertEqual(list(splitBlogIntoSections(page)), ["1_B"])

    def test_a_short_section_is_dropped(self):
        page = blog(header(1, "A") + "<p>See the other post.</p>")
        self.assertEqual(splitBlogIntoSections(page), {})
        self.assertGreater(MIN_TUTORIAL_CHARS, len("See the other post."))

    def test_the_same_problem_twice_is_joined(self):
        page = blog(header(1, "A") + f"<p>First part.{FILLER}</p>" + header(2, "B") + f"<p>Other.{FILLER}</p>" + header(1, "A") + f"<p>Second part.{FILLER}</p>")
        self.assertEqual(splitBlogIntoSections(page)["1_A"], f"First part.{FILLER}\n\nSecond part.{FILLER}")

    def test_a_post_without_problem_headers_gives_nothing(self):
        self.assertEqual(splitBlogIntoSections(blog(f"<p>Just thoughts.{FILLER}</p>")), {})

    def test_only_the_post_body_is_read_not_the_comments(self):
        page = soupOf(
            '<div class="topic"><div class="content"><div class="ttypography">' + header(1, "A") + f"<p>Body.{FILLER}</p></div></div></div>"
            '<div class="comments"><div class="ttypography">' + header(1, "A") + f"<p>Spam.{FILLER}</p></div></div>"
        )
        self.assertEqual(splitBlogIntoSections(page)["1_A"], f"Body.{FILLER}")


class DynamicTutorialTests(unittest.TestCase):
    def test_placeholders_are_listed_by_key_with_their_problem_code(self):
        page = blog(
            header(1800, "A") + spoiler("Tutorial", '<div class="problemTutorial" problemcode="1800A">Tutorial is loading...</div>')
            + header(1800, "C1") + spoiler("Tutorial", '<div class="problemTutorial" problemcode="1800C1">Tutorial is loading...</div>')
        )
        self.assertEqual(findDynamicTutorials(page), {"1800_A": "1800A", "1800_C1": "1800C1"})

    def test_a_post_without_placeholders(self):
        self.assertEqual(findDynamicTutorials(blog("<p>text</p>")), {})

    def test_a_placeholder_does_not_leak_into_the_static_section(self):
        page = blog(header(1800, "A") + spoiler("Tutorial", '<div class="problemTutorial" problemcode="1800A">Tutorial is loading...</div>'))
        self.assertEqual(splitBlogIntoSections(page), {})

    def test_the_endpoint_html_becomes_text_without_its_title_or_code(self):
        html = ("<h3><a href='/contest/1800/problem/A'>1800A - Is It a Cat?</a></h3>"
                '<div class="ttypography"><div class="problem-statement"><div>'
                '<p>Convert to lower case and compare with &quot;meow&quot;.</p>'
                '<p>Use <span class="tex-font-style-it">unique</span> in C++.</p><pre>code</pre></div></div></div>')
        self.assertEqual(parseDynamicTutorial(html), 'Convert to lower case and compare with "meow".\n\nUse unique in C++.')

    def test_empty_endpoint_html_gives_empty_text(self):
        self.assertEqual(parseDynamicTutorial("<h3>Title</h3>"), "")


class CsrfTests(unittest.TestCase):
    def test_token_is_read_from_the_meta_tag(self):
        self.assertEqual(findCsrfToken(soupOf('<meta name="X-Csrf-Token" content="abc123"/>')), "abc123")

    def test_missing_token(self):
        self.assertIsNone(findCsrfToken(soupOf("<html></html>")))


if __name__ == "__main__":
    unittest.main()
