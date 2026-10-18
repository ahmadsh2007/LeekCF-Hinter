import unittest

from bs4 import BeautifulSoup

from src.utils.htmlText import extractText

def textOf(html: str) -> str:
    return extractText(BeautifulSoup(f"<div>{html}</div>", "html.parser").div)

class InlineTextTests(unittest.TestCase):
    def test_old_style_math_stays_inside_its_sentence_and_is_delimited(self):
        html = '<p>The size is <span class="tex-span"><i>n</i> × <i>m</i></span> meters.</p>'
        self.assertEqual(textOf(html), "The size is $$$n × m$$$ meters.")

    def test_superscript_and_subscript_become_latex_scripts(self):
        html = ('<p><span class="tex-span">1 ≤ <i>a</i><sub class="lower-index">i</sub> ≤ 10<sup class="upper-index">9</sup></span></p>')
        self.assertEqual(textOf(html), "$$$1 ≤ a_i ≤ 10^9$$$")

    def test_multi_character_scripts_are_braced(self):
        html = '<p><span class="tex-span"><i>a</i><sub class="lower-index">i+1</sub></span></p>'
        self.assertEqual(textOf(html), "$$$a_{i+1}$$$")

    def test_modern_math_delimiters_pass_through_untouched(self):
        self.assertEqual(textOf(r"<p>Given $$$1 \le n \le 10^5$$$.</p>"), r"Given $$$1 \le n \le 10^5$$$.")

    def test_font_style_spans_code_and_links_do_not_split_the_paragraph(self):
        html = ('<p>Print <span class="tex-font-style-tt">YES</span> or <span class="tex-font-style-bf">NO</span>, '
                'see <a href="/x">the rules</a> and <code>x</code>.</p>')
        self.assertEqual(textOf(html), "Print YES or NO, see the rules and x.")

    def test_whitespace_runs_and_odd_spaces_collapse_to_one_space(self):
        self.assertEqual(textOf("<p>1 ≤ n,\n   m\xa0≤ 5</p>"), "1 ≤ n, m ≤ 5")

    def test_line_break_inside_a_paragraph_is_kept_as_a_newline(self):
        self.assertEqual(textOf("<p>first<br/>second</p>"), "first\nsecond")

    def test_two_line_breaks_in_a_row_keep_a_blank_line(self):
        self.assertEqual(textOf("<p>first<br/><br/>second</p>"), "first\n\nsecond")

    def test_comments_scripts_and_styles_are_ignored(self):
        self.assertEqual(textOf("<p>kept<!-- gone --><script>bad()</script><style>.x{}</style></p>"), "kept")


class BlockTextTests(unittest.TestCase):
    def test_paragraphs_are_separated_by_a_blank_line(self):
        self.assertEqual(textOf("<p>One.</p><p>Two.</p>"), "One.\n\nTwo.")

    def test_bare_text_next_to_a_block_becomes_its_own_paragraph(self):
        self.assertEqual(textOf("Intro <b>text</b><p>Body.</p>"), "Intro text\n\nBody.")

    def test_unordered_list_has_one_bullet_per_line(self):
        self.assertEqual(textOf("<ul> <li> one </li><li> two </li></ul>"), "- one\n- two")

    def test_ordered_list_is_numbered(self):
        self.assertEqual(textOf("<ol><li>one</li><li>two</li></ol>"), "1. one\n2. two")

    def test_list_between_paragraphs(self):
        html = "<p>Rules:</p><ul><li>a</li><li>b</li></ul><p>Done.</p>"
        self.assertEqual(textOf(html), "Rules:\n\n- a\n- b\n\nDone.")

    def test_list_item_with_inline_math_stays_on_one_line(self):
        html = '<ul><li>The MEX of $$$[2,2,1]$$$ is <span class="tex-span">0</span>.</li></ul>'
        self.assertEqual(textOf(html), "- The MEX of $$$[2,2,1]$$$ is $$$0$$$.")

    def test_preformatted_block_keeps_its_line_breaks(self):
        self.assertEqual(textOf("<p>Code:</p><pre>a = 1\n  b = 2</pre>"), "Code:\n\na = 1\n  b = 2")

    def test_titled_section_puts_the_title_on_its_own_paragraph(self):
        html = '<div class="input-specification"><div class="section-title">Input</div><p>The first line.</p></div>'
        self.assertEqual(textOf(html), "Input\n\nThe first line.")

    def test_empty_element_gives_empty_string(self):
        self.assertEqual(textOf("  <p> </p>  "), "")


if __name__ == "__main__":
    unittest.main()
