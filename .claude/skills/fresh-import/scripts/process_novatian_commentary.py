#!/usr/bin/env python3
"""Import the Scripture commentary in Novatian's Treatise Concerning the Trinity (De Trinitate,
in R. E. Wallis's public-domain translation, ANF 5, 1886) into the Commentaries-Database, one
piece at a time, by driving a headless ``claude`` agent.

A per-father copy of process_basil_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, splitting, logs and --check. The treatise is
not a verse-by-verse commentary but a dogmatic work on the rule of faith (the Father, the Son,
the Spirit) that proves its case from Scripture throughout, so the import is SELECTIVE (WORKS
"selective": True): the agents read every chapter and file only the stretches that genuinely
expound a verse; the rest is left out.

    Writings-Database/Novatian/A Treatise of Novatian Concerning the Trinity.html

    <h1>A Treatise of Novatian Concerning the Trinity</h1>
    <h2>Preface.</h2> ...                    (the ANF editor's summary: dropped)
    <h2>Chapter IX. Argument.—Further, that ...</h2>                 (a chapter = one section)
    <h2>Chapter XV.<sup>…102…</sup> Argument.—Again He Proves ...</h2>
    Novatian's text ...<sup><a href="#fn8" id="r8">8</a></sup>
    <section class="notes"><hr/><span id="fn8">... Ps. cxlviii. 5.</span> ...  (the notes)

``load_work`` gives one section per chapter (heading "Chapter IX. (= 9)"). The editor's
"Argument" summary is inside the <h2>, so there is no summary line to cut. The footnotes give
most of the Scripture references, so the html the agent sees carries each one inline, as
``<sup>[note: Ps. xlv. 1.]</sup>``, as a hint; the body (the text imported and checked) drops
them.

    python3 process_novatian_commentary.py NovTrinity --dry-run
    python3 process_novatian_commentary.py NovTrinity --split-only
    python3 process_novatian_commentary.py NovTrinity Part002_Ch05-08.html
    python3 process_novatian_commentary.py NovTrinity --check
"""

import argparse
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import unicodedata
from datetime import datetime
from urllib.parse import quote

# --- Paths --------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# These scripts live in <Commentaries-Database>/.claude/skills/fresh-import/scripts.
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
# The claude agent runs here so the Commentaries-Database CLAUDE.md conventions apply
# and its relative `<Father>/<Book Verse>.toml` writes land in the right tree.
PROJECT_DIR = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
BOOK_NAMES_PATH = os.path.join(PROJECT_DIR, "book_names.json")
# The Writings-Database checkout: $WRITINGS_DB, else a sibling of the Commentaries-Database.
WRITINGS_DIR = os.environ.get("WRITINGS_DB") or os.path.join(
    os.path.dirname(PROJECT_DIR), "Writings-Database")
# Units and run logs go here (gitignored), not next to the scripts.
WORK_DIR = os.path.join(SKILL_DIR, "work")
# KJV lookup for the agent, run from PROJECT_DIR.
KJV_LOOKUP = 'python3 .claude/skills/fresh-import/scripts/kjv_lookup.py "<Book> <C>:<V>"'

FATHER = "Novatian"

# A piece holds consecutive chapters up to about this many html chars.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "NovTrinity": {
        "html": "Novatian/A Treatise of Novatian Concerning the Trinity.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        # "On the Trinity, Chapter 9" / "..., Chapters 9-10" (the user's choice; the old ACCS
        # excerpts had "ON THE TRINITY 18:15–17", "THE TRINITY 29.16").
        "source_title": "On the Trinity",
        "notes": (
            "Wallis's footnotes also hold the American editor's bracketed remarks (\"[Vol. iii. p. "
            "428.]\", \"[Cap. xxi. p. 632, supra.]\", \"Bull, Defensio\", \"Hippol.\", \"Compare the "
            "Athanasian Confession\"), Latin readings (\"Mensurnis,\" \"Benedicat.\", "
            "\"Principalitas.\") and, in the headings of Chapters XV-XXVII, \"According to "
            "Pamelius, ch. xxiii.\": Pamelius's different chapter numbering, NOT Scripture and NOT "
            "the chapter number for source_title (always use the file's own Roman number in the "
            "<h2>). A bracketed note that names verses (\"[Among the apparitions are noted Gen. "
            "xxxii. 24, Ex. iii., ...]\") is the editor's comparison, not a quotation by Novatian. "
            "Novatian quotes an Old Latin Bible, often following the Septuagint, so his wording "
            "is far from the KJV's: match by SENSE. \"Thou hast made all things in wisdom\" is "
            "Psalms 104:24 (the note's \"Ps. ciii. 24.\" is the Latin number); \"the Angel of "
            "Great Counsel\" / \"Messenger of Great Counsel\" is Isaiah 9:6 in the Septuagint; "
            "\"Thus saith the Lord to Christ my Lord\" is Isaiah 45:1 (the Septuagint's \"to Cyrus\" "
            "misread, as the note says); \"My heart has emitted a good word\" / \"My heart hath "
            "uttered forth a good Word\" is Psalms 45:1; \"We shall find Him, as it were, prepared "
            "in the morning\" is Hosea 6:3. Some of the notes' references are misprinted (kept as "
            "printed in the source), so always confirm by the WORDING: in Chapter III \"hath "
            "meted out the heaven with a span\" is Isaiah 40:12 and the next quotation, \"who "
            "looketh on the earth, and maketh it tremble ...\", joins Psalms 104:32 to Isaiah "
            "40:22 and 40:12 (the notes \"Ps. ciii. 32.\" and \"Isa. xl. 22, 12.\" sit one quotation "
            "late); later in Chapter III \"Rom. xi. 33.\" on \"of Him, and through Him, and in Him are all "
            "things\" is Romans 11:36; in Chapter VI \"2 Chron. xix. 16.\" on \"Incline thine ear, "
            "and hear,\" is 2 Kings 19:16; in Chapter VIII \"Ps. lxviii. 18.\" on \"For the chariot "
            "of God,\" says he, \"is multiplied ten thousand times;\" is Psalms 68:17; in Chapter IX "
            "\"Isa. vii. 13.\" on \"Behold, a virgin shall conceive\" is Isaiah 7:14 and \"Isa. xiii. "
            "2, 3.\" on \"His voice shall not be heard in the streets\" is Isaiah 42:2-3; in Chapter "
            "X \"1 Cor. xvi. 50.\" is 1 Corinthians 15:50; in Chapter XI \"Matt. xxiii. 42\" on the "
            "\"Son of David,\" is Matthew 22:42; in Chapter XII \"Heb. iii. 3.\" on \"God shall come "
            "from the south\" is HABAKKUK 3:3; in Chapter XIII \"Ps. xix. 6, 7.\" on \"as a "
            "bridegroom goeth forth from his bride-chamber\" is Psalms 19:5-6; in Chapter XXVI "
            "\"John xii. 20.\" on \"I have both glorified Him, and I will glorify Him again?\" is "
            "John 12:28 and \"John xi. 12.\" on \"Father, I knew that Thou hearest me always\" is "
            "John 11:41-42; the editor's \"1 Kings xxviii. 11\" is 1 Samuel 28:11. The notes' "
            "Psalm numbers are otherwise the English (KJV) ones. Most of the treatise is one long "
            "paragraph per chapter, so cut between sentences. Much of it is an argument from "
            "Scripture (\"If Christ is only man, how is it that He says ...\"): a verse used as "
            "one premise in a chain of such questions, with no more said about it, is a "
            "proof-text; where Novatian stops to argue from a verse's wording (who is speaking, "
            "who is sent, why it says \"one\" and not \"one person\"), or explains a figure (the "
            "wheels and living creatures of Ezekiel as God's chariot, the theophanies to Abraham, "
            "Hagar and Jacob, Moses called a god), that is commentary on that verse."
        ),
    },
}


def _raw_notes(work):
    """The notes of a work's file, in printed order (the text of each)."""
    with open(os.path.join(WRITINGS_DIR, work["html"]), encoding="utf-8") as f:
        m = NOTES_RE.search(f.read())
    return [_clean(t) for _, t in NOTE_RE.findall(m.group(1))] if m else []


def note_hints(work, markers):
    """{marker number: note text} for the hint of each footnote marker."""
    notes = _raw_notes(work)
    return {n: notes[n - 1] for n in markers if n <= len(notes)}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the other importers ("file=Basil%2520of%2520Caesarea%2FON%2520THE%2520SPIRIT.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"novatian_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50}
# A chapter's heading: "Chapter IX. Argument.—Further, ...", "Chapter XI.—And Indeed ...", or
# (XV-XXVII) "Chapter XV.<sup>…</sup> Argument.—Again ..." (the note gives Pamelius's numbering).
CHAPTER_RE = re.compile(r"Chapter ([IVXL]+)\.(?:\s.*|—.*)?", re.S)


def roman(s):
    n = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN_VALUES[a]
        n += -v if ROMAN_VALUES.get(b, 0) > v else v
    return n


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def chapter_title(work, chapters):
    """The source_title for a block from these chapter numbers:
    "On the Trinity, Chapter 7", "..., Chapters 7-8"."""
    a, b = min(chapters), max(chapters)
    t = work["source_title"]
    return f"{t}, Chapter {a}" if a == b else f"{t}, Chapters {a}-{b}"


def load_work(work):
    """Return (preamble_html, sections): one section per chapter. The editor's Preface (a
    summary of the treatise, not Novatian's text) is dropped. A section's heading is "Chapter
    IX. (= 9)", its html the section as the agent sees it (the <h2> with the editor's
    "Argument", and the text, the footnotes inline as [note: ...] hints), its body the text
    without heading and notes, and `chapter` None (there are no verse sections); `chapter_no`
    is the chapter's number."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(text)])

    def hinted(s):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""),
            s)

    parts = H2_RE.split(text)
    preamble = hinted(parts[0])
    sections = []
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        raw = parts[i + 1].replace("</article>", "").lstrip("\n").rstrip() + "\n"
        title = _clean(FOOTNOTE_REF_RE.sub("", h2))
        if title == "Preface.":
            if sections:
                raise SystemExit(f"{work['html']}: Preface after the first chapter")
            continue
        cm = CHAPTER_RE.fullmatch(title)
        if not cm:
            raise SystemExit(f"{work['html']}: unexpected <h2>: {h2}")
        no = roman(cm.group(1))
        sections.append({
            "heading": f"Chapter {cm.group(1)}. (= {no})",
            "chapter": None,
            "chapter_no": no,
            "html": hinted(h2) + "\n" + hinted(raw),
            "body": FOOTNOTE_REF_RE.sub("", raw),
        })
    nos = [s["chapter_no"] for s in sections]
    if nos != list(range(1, len(nos) + 1)):
        raise SystemExit(f"{work['html']}: chapters are not numbered 1..n: {nos}")
    return preamble, sections


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in re.split(r"(?:<br\s*/?>\s*){2,}", section["body"]):
        p = _clean(p)
        if p:
            out.append(p)
    return out


def split_evenly(sections, cap):
    """Cut a list of sections into the fewest near-equal runs (at section boundaries)
    whose html each fits under `cap`, as far as section sizes allow."""
    sizes = [len(s["html"]) for s in sections]
    total = sum(sizes)
    k = max(1, math.ceil(total / cap))
    while True:
        runs, cur, acc = [], [], 0
        for s, n in zip(sections, sizes):
            # Cut before this section if that lands closer to the next even boundary.
            target = total * (len(runs) + 1) / k
            if cur and len(runs) < k - 1 and abs(acc - target) <= abs(acc + n - target):
                runs.append(cur)
                cur = []
            cur.append(s)
            acc += n
        runs.append(cur)
        too_big = any(
            sum(len(s["html"]) for s in r) > cap and len(r) > 1 for r in runs
        )
        if not too_big or k >= len(sections):
            return runs
        k += 1


def make_units(preamble, sections, cap):
    """The ordered list of pieces: {name, chapter, sections}; a piece is a run of whole
    chapters, named by its first and last chapter."""
    units = []
    for run in split_evenly(sections, cap):
        a, b = run[0]["chapter_no"], run[-1]["chapter_no"]
        units.append({
            "name": f"Part{len(units) + 1:03d}_Ch{a:02d}-{b:02d}.html",
            "chapter": None,
            "sections": run,
        })
    return units


def unit_html(preamble, unit):
    tail = "</article>\n" if "<article" in preamble else ""
    return preamble + "".join(s["html"] for s in unit["sections"]) + tail


def write_units(work_key, preamble, units):
    d = units_dir_for(work_key)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    for u in units:
        with open(os.path.join(d, u["name"]), "w", encoding="utf-8") as f:
            f.write(unit_html(preamble, u))
    return d


# --- Prompts ------------------------------------------------------------------

PROMPT1_TEMPLATE = (
    "We have Novatian's Treatise Concerning the Trinity (De Trinitate) here: "
    "\"{units_dir}/{first_unit}\" with the files continuing up to \"{units_dir}/{last_unit}\". "
    "These are consecutive pieces cut, in order, from our PUBLIC-DOMAIN English translation of "
    "the work (R. E. Wallis's, Ante-Nicene Fathers vol. 5, 1886), \"{html_path}\" (consult it if "
    "you need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. The treatise sets out the rule of faith in 31 "
    "chapters: God the Father, Creator, immense, immutable, without passions or members "
    "(Chapters I-VIII); the Son, true man and true God, proved from the Old and New Testaments "
    "against the heretics who make Him only man and against the Sabellians who make Him the "
    "Father (IX-XXVIII); the Holy Spirit (XXIX); and the one God, the Son being from the Father "
    "(XXX-XXXI). Novatian argues from Scripture throughout, quoting and expounding it "
    "constantly. Your task is to EXTRACT from the piece the stretches that are genuinely "
    "commentary on a specific verse of Scripture, and file each under that verse in the "
    "\"{father}/\" folder. Much of the text will NOT be imported, and that is expected: a "
    "chapter with no exposition of a verse gives no block.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the work's title at the top; that is background "
    "for you, not text to import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Novatian QUOTES or plainly refers to a "
    "specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its words "
    "(literally or spiritually), resolves a difficulty in it, applies a figure or type in it "
    "(a theophany, a prophecy of Christ), builds his argument on its wording (who speaks, to "
    "whom, why it says what it says), or answers the heretics' reading of it. Do NOT import a "
    "verse quoted only in passing, a bare proof-text dropped into a sentence, a chain of "
    "proof-texts quoted without comment, or teaching that merely mentions Scripture. Ask: "
    "would a reader studying this verse learn something about how Novatian understood or used "
    "it from this stretch? If so, import it; if it would only learn that Novatian quoted it, "
    "leave it out.\n\n"
    "VERSE KEYS. The footnotes are shown inline as \"[note: ...]\" in superscript, after the "
    "word they mark. Most give the reference of a quotation, abbreviated with Roman chapter "
    "numbers (\"John x. 35, 36.\" = John 10:35-36, \"Ps. xlv. 1.\", \"Isa. ix. 6, LXX.\"); "
    "others are the editors' remarks and give no verse. A note can sit on the wrong quotation, "
    "or be missing. Use the notes as HINTS only, and confirm every verse against the KJV "
    "wording with `" + KJV_LOOKUP + "`, filing under KJV book/chapter/verse numbering. "
    "Deuterocanonical books are fine (\"Sirach\", \"Wisdom\", \"Baruch\", ...): use only the "
    "book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Novatian's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the verse and the whole of his exposition of it. Don't pad a "
    "block with unrelated argument before or after the exposition. File it under the SMALLEST "
    "verse range the exposition really addresses: a single verse when it expounds one verse, a "
    "range only when it expounds several verses as one argument (a range crossing chapters is "
    "written like \"Genesis 18_33-19_1\"). When one stretch genuinely expounds two different "
    "passages (e.g. an Old Testament prophecy and the Gospel verse that fulfils it, interpreted "
    "together), file the same text under each, as separate files; that is welcome. But never "
    "put two overlapping blocks of this work in the SAME file, and don't split one exposition "
    "into fragments under one verse.\n\n"
    "THE TEXT. Copy Novatian's words VERBATIM: nothing abridged, paraphrased, corrected, added "
    "or rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Leave out the \"[note: "
    "...]\" footnotes and the <h2> headings (the chapter's number and the editor's \"Argument\" "
    "summary, e.g. \"Chapter XII. Argument.—That Christ is God, ...\", are a heading, not "
    "text). Keep the printed text's quotation marks, dashes, bracketed words, run-together "
    "words and misprints as they are. Don't add headings, verse numbers or notes of your own. "
    "Don't write a python script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}, Chapter N\"\n"
    "where N is the (Arabic) number of the chapter the block comes from, e.g. \"{source_title}, "
    "Chapter 12\" for a block from \"Chapter XII.\"; a block running across chapters is "
    "\"{source_title}, Chapters 12-13\".\n\n"
    "EXISTING BLOCKS. The old imports of this work have ALREADY been deleted, so you are only "
    "ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it (with no blank line before its first [[commentary]]). Earlier pieces "
    "of THIS run may already have left blocks from Novatian's On the Trinity in the files you "
    "write to: they are NOT old imports or duplicates; leave them exactly as they are and "
    "append yours after them. Blocks from other works (On the Jewish Meats, In Praise of "
    "Purity, On the Spectacles, the letters, and excerpts with no source_url) must be left "
    "exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- chapter, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    return PROMPT1_TEMPLATE.format(
        title=work["source_title"],
        units_dir=units_dir,
        first_unit=units[0]["name"],
        last_unit=units[-1]["name"],
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        father=FATHER,
        unit_name=unit["name"],
        headings=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        source_title=work["source_title"],
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
    # NFC: accented Greek can come in oxia forms (U+1F73 "έ"), which an agent copying it may
    # write as the identical-looking tonos form (U+03AD); neither should fail the check.
    s = unicodedata.normalize("NFC", s)
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", s).strip()


def source_offsets(sections):
    """(normalised source text, [(start, end, chapter_no)] per section)."""
    parts = [_norm(" ".join(paragraphs_of(s))) for s in sections]
    source = " ".join(parts)
    offs, pos = [], 0
    for s, p in zip(sections, parts):
        offs.append((pos, pos + len(p), s["chapter_no"]))
        pos += len(p) + 1
    return source, offs


def chapters_spanned(offs, a, e):
    return [no for x, y, no in offs if x < e and y > a]


def run_check(work, sections):
    """Return a list of problems (empty == all good). Prints a summary. A selective import
    has no coverage to check: this checks that every block of this book is one verbatim
    stretch of it, found once, under a valid filename, with the right source_title."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    url = source_url_for(work)
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        books = json.load(f)["canonical_names"]
    filename_re = re.compile(
        "(" + "|".join(map(re.escape, books)) + r") \d+_\d+(?:-\d+(?:_\d+)?)?\.toml"
    )
    source, offs = source_offsets(sections)
    problems, n, files, per_chapter = [], 0, set(), {}

    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if url not in text:
            continue
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{fn}: TOML parse error: {exc}")
            continue
        mine = [c for c in data.get("commentary", []) if c.get("source_url") == url]
        if not mine:
            continue
        files.add(fn)
        # (The agents of the Athanasius run created 42 files opening with a blank line.)
        if text.startswith("\n"):
            problems.append(f"{fn}: file starts with a blank line")
        if not filename_re.fullmatch(fn):
            problems.append(f"{fn}: filename is not '<Book> C_V' / 'C_V-V' / 'C_V-C_V'")
        spans = []
        for c in mine:
            n += 1
            q = _norm(c.get("quote", ""))
            if re.search(r"</?[a-z]+>|\[note:", q):
                problems.append(f"{fn}: leftover html tag or [note: ...] in a block")
            hits = [m.start() for m in re.finditer(re.escape(q), source)] if q else []
            if not hits:
                problems.append(f"{fn}: block is not one continuous stretch of the source "
                                f"(text cut up, rearranged or altered): {q[:80]!r}")
                continue
            if len(hits) > 1:
                problems.append(f"{fn}: block matches the source {len(hits)} times: {q[:60]!r}")
            a, e = hits[0], hits[0] + len(q)
            spans.append((a, e))
            chs = chapters_spanned(offs, a, e)
            want = chapter_title(work, chs)
            if c.get("source_title") != want:
                problems.append(f"{fn}: source_title {c.get('source_title')!r}, the text is "
                                f"{want!r}")
            for no in chs:
                per_chapter.setdefault(no, []).append(fn[:-5])
        spans.sort()
        for (a1, e1), (a2, e2) in zip(spans, spans[1:]):
            if a2 < e1:
                problems.append(f"{fn}: two blocks of this work overlap in one file")

    print(f"\nCHECK: {n} block(s) of this work in {len(files)} file(s); "
          f"{len(per_chapter)} of {len(sections)} sections used")
    heads = {s["chapter_no"]: s["heading"] for s in sections}
    for no in sorted(per_chapter):
        print(f"  {heads[no]}: {', '.join(per_chapter[no])}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    else:
        print("CHECK PASSED")
    return problems


# --- Live rendering of stream-json events -------------------------------------


def _truncate(text, limit=500):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " …"


def render_event(event):
    """Print a human-readable line for one stream-json event, live."""
    etype = event.get("type")

    if etype == "system" and event.get("subtype") == "init":
        model = event.get("model", "?")
        print(f"    · session start (model={model})")

    elif etype == "assistant":
        for block in event.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                print(f"    💬 {_truncate(block['text'])}")
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                hint = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                hint = f" {_truncate(str(hint), 160)}" if hint else ""
                print(f"    🔧 {name}{hint}")

    elif etype == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                flag = " [error]" if block.get("is_error") else ""
                print(f"    ↳ result{flag}: {_truncate(str(content), 200)}")

    elif etype == "result":
        if event.get("subtype") != "success":
            print(f"    ⚠ result subtype={event.get('subtype')}")


# --- One claude call ----------------------------------------------------------


def is_rate_limit_error(stderr):
    lower = stderr.lower()
    return any(
        term in lower
        for term in ["rate limit", "rate_limit", "overloaded", "too many requests", "529"]
    )


def call_claude(prompt, events_log, tag, resume_session=None):
    """Run one headless claude invocation, streaming stream-json events.

    Returns (final_text, session_id). Every raw event line is persisted to
    events_log tagged with `tag` (e.g. "Part003_Ch02a/prompt1"). When resume_session
    is given, the call continues that conversation via --resume."""
    delays = RETRY_DELAYS
    for attempt in range(len(delays) + 1):
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if resume_session:
            cmd += ["--resume", resume_session]
        cmd += ["--output-format", "stream-json", "--verbose", prompt]

        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        final_text = ""
        session_id = resume_session
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events_log.write(
                json.dumps({"tag": tag, "attempt": attempt + 1, "event": event}) + "\n"
            )
            events_log.flush()
            if event.get("session_id"):
                session_id = event["session_id"]
            render_event(event)
            if event.get("type") == "result" and "result" in event:
                final_text = event["result"]

        proc.wait()
        stderr = proc.stderr.read()

        if proc.returncode == 0:
            return final_text.strip(), session_id

        if is_rate_limit_error(stderr):
            delays = RATE_LIMIT_DELAYS

        if attempt < len(delays):
            wait = delays[attempt]
            print(
                f"    Retry {attempt + 1}/{len(delays)} after {wait}s... "
                f"(rc={proc.returncode} stderr={stderr.strip()[:80]})"
            )
            time.sleep(wait)
        else:
            msg = (
                f"rc={proc.returncode} stderr={stderr.strip()[:200]} "
                f"final={final_text.strip()[:200]}"
            )
            raise RuntimeError(f"claude call failed after retries: {msg}")

    raise RuntimeError("Unreachable")


# --- Driver -------------------------------------------------------------------


def log_record(log, unit, prompt_no, started, ended, session_id, output):
    log.write(
        json.dumps(
            {
                "unit": unit["name"],
                "sections": [s["heading"] for s in unit["sections"]],
                "prompt": prompt_no,
                "timestamp": started.isoformat(),
                "duration_seconds": round((ended - started).total_seconds(), 1),
                "session_id": session_id,
                "output": output,
            }
        )
        + "\n"
    )
    log.flush()


def process_unit(work, units_dir, units, unit, log, events_log):
    """Run prompt 1 (import) then prompt 2 (self-review) in one conversation."""
    print(f"\n{'=' * 60}")
    print(f"{unit['name']}: {', '.join(s['heading'] for s in unit['sections'])}")
    print(f"{'=' * 60}")
    tag = unit["name"].removesuffix(".html")

    print("  [prompt 1] importing...")
    started = datetime.now()
    out1, session_id = call_claude(
        build_prompt1(work, units_dir, units, unit), events_log, tag=f"{tag}/prompt1"
    )
    ended = datetime.now()
    log_record(log, unit, 1, started, ended, session_id, out1)
    print(f"  [prompt 1] done ({round((ended - started).total_seconds(), 1)}s)"
          f" -- session {session_id}")
    print(f"  {_truncate(out1, 300)}")

    if not session_id:
        print("  WARNING: no session_id captured from prompt 1; prompt 2 would "
              "start a fresh conversation. Skipping prompt 2 for this piece.")
        return

    print("  [prompt 2] double-checking...")
    started = datetime.now()
    out2, _ = call_claude(
        PROMPT2, events_log, tag=f"{tag}/prompt2", resume_session=session_id
    )
    ended = datetime.now()
    log_record(log, unit, 2, started, ended, session_id, out2)
    print(f"  [prompt 2] done ({round((ended - started).total_seconds(), 1)}s)")
    print(f"  {_truncate(out2, 300)}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("work", choices=sorted(WORKS), help="Which work to import.")
    parser.add_argument(
        "single", nargs="?",
        help="Process ONE piece (e.g. Part002_Ch09-16.html); see --dry-run for the names.",
    )
    parser.add_argument(
        "--start-after", metavar="NAME",
        help="Resume after this piece (e.g. Part001_Ch01-08.html).",
    )
    parser.add_argument(
        "--through", metavar="NAME",
        help="Stop after this piece (e.g. Part002_Ch09-16.html); combine with --start-after "
             "to run a chunk.",
    )
    parser.add_argument(
        "--chapters", metavar="A-B",
        help="Run ONE ad-hoc piece of exactly chapters A..B (e.g. 1-14), instead of the usual "
             "pieces: for re-running a stretch when the usual split no longer matches the pieces "
             "already imported.",
    )
    parser.add_argument(
        "--split-chars", type=int, default=SPLIT_CHARS,
        help=f"Cut chapters bigger than this many html chars (default {SPLIT_CHARS}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folder and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true", help="Run only the check.")
    args = parser.parse_args()
    if args.single and (args.start_after or args.through):
        parser.error("give a single piece or --start-after/--through, not both")

    work = WORKS[args.work]
    preamble, sections = load_work(work)
    units = make_units(preamble, sections, args.split_chars)
    if args.chapters:
        if args.single or args.start_after or args.through:
            parser.error("--chapters runs one piece of its own; give no other piece options")
        lo, hi = map(int, args.chapters.split("-"))
        run = [s for s in sections if lo <= s["chapter_no"] <= hi]
        if not run or run[0]["chapter_no"] != lo or run[-1]["chapter_no"] != hi:
            raise SystemExit(f"No chapters {args.chapters} in this work")
        units = [{"name": f"Part001_Ch{lo:02d}-{hi:02d}.html", "chapter": None, "sections": run}]
    units_dir = units_dir_for(args.work)
    names = [u["name"] for u in units]

    print(f"Work:       {FATHER}, {work['source_title']}")
    print(f"Source:     {os.path.join(WRITINGS_DIR, work['html'])}")
    print(f"Source url: {source_url_for(work)}")
    print(f"Units dir:  {units_dir}")
    print(f"Agent cwd:  {PROJECT_DIR}")

    if args.check:
        sys.exit(1 if run_check(work, sections) else 0)

    print(f"\n{len(sections)} section(s) -> {len(units)} piece(s) "
          f"(runs of chapters up to {args.split_chars} chars):")
    for u in units:
        size = sum(len(s["html"]) for s in u["sections"])  # excl. the repeated preamble
        print(f"  {u['name']:<22} {size:>7} chars  "
              f"{', '.join(s['heading'] for s in u['sections'])}")

    if args.single:
        if args.single not in names:
            raise SystemExit(f"No piece named {args.single!r}")
        todo = [u for u in units if u["name"] == args.single]
    else:
        first, last = 0, len(units)
        if args.start_after:
            if args.start_after not in names:
                raise SystemExit(f"No piece named {args.start_after!r}")
            first = names.index(args.start_after) + 1
        if args.through:
            if args.through not in names:
                raise SystemExit(f"No piece named {args.through!r}")
            last = names.index(args.through) + 1
        todo = units[first:last]
    if not todo:
        print("Nothing to do.")
        return

    if args.dry_run:
        print(f"\n--dry-run: prompt 1 for {todo[0]['name']}:\n")
        print(build_prompt1(work, units_dir, units, todo[0]))
        print(f"\n[prompt 2 is always]: {PROMPT2}")
        return

    write_units(args.work, preamble, units)
    print(f"\nWrote {len(units)} piece(s) to {units_dir}")
    if args.split_only:
        return

    log_dir = os.path.join(WORK_DIR, f"novatian_{args.work.lower()}_import_logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(log_dir, f"run-{stamp}.jsonl")
    events_path = os.path.join(log_dir, f"run-{stamp}.events.jsonl")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}\n")

    with open(log_path, "a") as log, open(events_path, "a") as events_log:
        for unit in todo:
            try:
                process_unit(work, units_dir, units, unit, log, events_log)
            except RuntimeError as exc:
                print(f"  ABORTING at {unit['name']}: {exc}")
                print(f"  (pieces kept in {units_dir})")
                log.write(json.dumps({"unit": unit["name"], "error": str(exc)}) + "\n")
                log.flush()
                sys.exit(1)

    shutil.rmtree(units_dir)
    print(f"\nDone. {len(todo)} piece(s) processed; removed {units_dir}")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}")

    # A full or resumed run ends on the last piece, so the whole work should be in place.
    if not args.single and todo[-1] is units[-1]:
        run_check(work, sections)


if __name__ == "__main__":
    main()
