#!/usr/bin/env python3
"""Import the Scripture commentary in Aphrahat's Demonstrations into the Commentaries-Database,
one Demonstration at a time, by driving a headless ``claude`` agent.

A per-father copy of process_athanasius_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, splitting, multi-work command line, --check
and --order. The Demonstrations are not a verse-by-verse commentary but treatises (on faith,
love, wars, monks, penitents, the resurrection, pastors, Christ the Son of God, persecution,
death) that quote and expound Scripture throughout, so the import is SELECTIVE (WORKS
"selective": True): the agents read every Demonstration and file only the stretches that
genuinely expound a verse.

Three files of the Writings-Database are imported, one WORKS entry per Demonstration
("AphDem01" .. "AphDem22", by its number):

    Aphrahat the Persian Sage/The Demonstrations.html   (Johnston, NPNF2-13, 1898)
        <h1>The Demonstrations</h1><i>translator's note</i><br/><br/>
        <h2>Letter of an Inquirer.</h2> ...                    (not Aphrahat's: no entry)
        <h2>Demonstration I.—Of Faith.</h2>
        §1. I have received thy letter, ...<sup>..</sup> ...<br/><br/>
        §2. Faith is compounded ...                            (the print's section marks)
        <h2>Demonstration V.—Of Wars.</h2> ...                 (I, V, VI, VIII, X, XVII, XXI, XXII)
        <section class="notes"> ... Ps. cxviii. 22. ...        (570 notes, numbered through)
    Aphrahat the Persian Sage/Demonstration 2 On love.html      (Hallock, JSOR 1930)
    Aphrahat the Persian Sage/Demonstration 7 On penitents.html (Hallock, JSOR 1932)
        <h1>..</h1><i>citation</i><br/><br/>1. Surely, beloved, ...<br/><br/>2. ...

The eight NPNF Demonstrations share one url, so a block belongs to a work by its url AND its
source_title ("Demonstration 5 (Of Wars), Section 3"): see ``block_is_mine``. Budge's
translation of Demonstration I ("On Faith.html") is not imported (the user chose Johnston's).

``load_work`` gives one section per section number ("§2." / "2." opening a paragraph); the
numbers are dropped from the text and shown in the pieces as ``<h2>`` headings. The heading
lines under the <h1> (the translator's note or the journal citation, Hallock's editorial
introduction to Dem. 7) are the preamble: background for the agent, not text. The scribes'
closing rubrics ("The Demonstration Concerning Love Is Completed.") are dropped. Footnotes are
shown inline as ``<sup>[note: Ps. cxviii. 22.]</sup>`` hints and dropped from the body.

    python3 process_aphrahat_commentary.py AphDem01 --dry-run
    python3 process_aphrahat_commentary.py AphDem01 AphDem05-AphDem08   # run these
    python3 process_aphrahat_commentary.py AphDem01-AphDem22 --check
    python3 process_aphrahat_commentary.py AphDem01 --order             # all files: work order
    python3 process_aphrahat_commentary.py AphDem01 --fix-order BASE    # ... and fix it
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

FATHER = "Aphrahat the Persian Sage"

# A piece holds consecutive sections up to about this many html chars (Demonstrations VI and
# XXII are bigger, and are cut at section boundaries).
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

APH_DIR = "Aphrahat the Persian Sage"
NPNF = f"{APH_DIR}/The Demonstrations.html"

# (number, html file, the <h2> of the Demonstration in a shared file or None, source_title,
# edition, extra settings). Extra settings: `head` = how many paragraphs under the <h1> are
# heading matter (default 1); `drop_paras` = regexes, a paragraph whose plain text starts with
# one is dropped; `strip` = regexes removed from the raw html. Each must match.
_DEMS = [
    (1, NPNF, "Demonstration I.—Of Faith.", "Demonstration 1 (Of Faith)", "npnf", {}),
    (2, f"{APH_DIR}/Demonstration 2 On love.html", None, "Demonstration 2 (Of Love)", "hallock",
     {"drop_paras": [r"The Demonstration Concerning Love Is Completed\."]}),
    (5, NPNF, "Demonstration V.—Of Wars.", "Demonstration 5 (Of Wars)", "npnf", {}),
    (6, NPNF, "Demonstration VI.—Of Monks.", "Demonstration 6 (Of Monks)", "npnf", {}),
    (7, f"{APH_DIR}/Demonstration 7 On penitents.html", None, "Demonstration 7 (Of Penitents)",
     "hallock",
     # Hallock's editorial introduction ("(The following Homily, issued in 336-337 A.D. ...").
     {"head": 2,
      "drop_paras": [r"The demonstration concerning penitents is completed"]}),
    (8, NPNF, "Demonstration VIII.—Of the Resurrection of the Dead.",
     "Demonstration 8 (Of the Resurrection of the Dead)", "npnf", {}),
    (10, NPNF, "Demonstration X.—Of Pastors.", "Demonstration 10 (Of Pastors)", "npnf", {}),
    (17, NPNF, "Demonstration XVII.—Of Christ the Son of God.",
     "Demonstration 17 (Of Christ the Son of God)", "npnf", {}),
    (21, NPNF, "Demonstration XXI.—Of Persecution.", "Demonstration 21 (Of Persecution)", "npnf",
     {}),
    (22, NPNF, "Demonstration XXII.—Of Death and the Latter Times.",
     "Demonstration 22 (Of Death and the Latter Times)", "npnf", {}),
]

# Per-Demonstration notes for the agents.
_NOTES = {
    7: ("Hallock prints his own Scripture references in parentheses in the text (\"(S. John "
        "16: 33)\", \"(Mal. 2: 6)\"): they are part of the printed text, so keep them in a "
        "block exactly as printed; they are also good hints (but confirm each against the "
        "KJV wording: some are loose). The second heading line, Hallock's introduction "
        "(\"(The following Homily, issued in 336-337 A.D. ...\"), is background, not text."),
}

WORKS = {
    f"AphDem{no:02d}": {
        "html": fn,
        "h2": h2,
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        "kind": kind,
        "number": no,
        "label": "Section",
        # "Demonstration 5 (Of Wars), Section 3"; "..., Sections 3-4" (as the old newadvent
        # block had it: "Demonstration 17 (Of Christ the Son of God), Section 10").
        "source_title": title,
        "notes": _NOTES.get(no, ""),
        **extra,
    }
    for no, fn, h2, title, kind, extra in _DEMS
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
    the url'd block of the old import ("file=Aphrahat%2520the%2520Persian%2520Sage%2FThe...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def block_is_mine(work, c):
    """Whether a [[commentary]] block belongs to this work: its url, and (since the NPNF
    Demonstrations share one file and url) a source_title of this Demonstration."""
    t = c.get("source_title") or ""
    return (c.get("source_url") == source_url_for(work)
            and (t == work["source_title"] or t.startswith(work["source_title"] + ",")))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"aphrahat_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
PARA_SPLIT_RE = re.compile(r"(?:<br\s*/?>\s*){2,}")
H2_RE = re.compile(r"<h2>(.*?)</h2>", re.S)
# A section number opening a paragraph: NPNF's "§2. Faith is", Hallock's "2. And when".
SECTION_NO_RE = {"npnf": re.compile(r"§(\d+)\.\s+"), "hallock": re.compile(r"(\d+)\.\s+")}


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _plain(p):
    """A paragraph's plain text without its note marks."""
    return _clean(FOOTNOTE_REF_RE.sub("", p))


def chapter_title(work, chapters):
    """The source_title for a block from these section numbers."""
    a, b = min(chapters), max(chapters)
    return (f"{work['source_title']}, {work['label']} {a}" if a == b
            else f"{work['source_title']}, {work['label']}s {a}-{b}")


def load_work(work):
    """Return (preamble_html, sections): one section per section number. A section's heading
    is "Section 2", its html the section as the agent sees it (an <h2> with the number, the
    text, the footnotes inline as [note: ...] hints), its body the text without number and
    notes, `chapter` None (there are no verse sections) and `chapter_no` its number."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    for rx in work.get("strip", []):
        text, n = re.subn(rx, "", text)
        if not n:
            raise SystemExit(f"{work['html']}: strip pattern matched nothing: {rx!r}")
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(text)])

    def hinted(s):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""), s)

    head, rest = text.split("</h1>", 1)
    rest = rest.replace("</article>", "")
    if work["h2"]:
        # The shared NPNF file: the translator's note is the heading matter, and the text is
        # this Demonstration's <h2> up to the next one (its <h2> goes into the preamble).
        pieces = H2_RE.split(rest)
        titles = pieces[1::2]
        if titles.count(work["h2"]) != 1:
            raise SystemExit(f"{work['html']}: no single <h2> {work['h2']!r} in {titles}")
        i = titles.index(work["h2"])
        lead, rest = pieces[0], pieces[2 * i + 2]
        lead_paras = [p.strip() for p in PARA_SPLIT_RE.split(lead) if p.strip()]
        head_paras = lead_paras + [f"<b>{work['h2']}</b>"]
    else:
        head_paras = []
    paras = [p.strip() for p in PARA_SPLIT_RE.split(rest)]
    paras = [p for p in paras if p]
    if not work["h2"]:
        nhead = work.get("head", 1)
        if not paras[0].startswith("<i>"):
            raise SystemExit(f"{work['html']}: no italic heading line: {paras[0][:100]!r}")
        head_paras, paras = paras[:nhead], paras[nhead:]
    preamble = (hinted(head) + "</h1>\n"
                + "".join(hinted(p) + "<br/><br/>\n" for p in head_paras))

    used = set()
    keep = []
    for p in paras:
        plain = _plain(p)
        rxs = [rx for rx in work.get("drop_paras", []) if re.match(rx, plain)]
        if rxs:
            used.update(rxs)
            continue
        keep.append(p)
    for rx in work.get("drop_paras", []):
        if rx not in used:
            raise SystemExit(f"{work['html']}: pattern matched no paragraph: {rx!r}")

    label = work["label"]
    section_no = SECTION_NO_RE[work["kind"]]
    sections = []
    for p in keep:
        sm = section_no.match(p)
        if sm:
            n = int(sm.group(1))
            last = sections[-1]["chapter_no"] if sections else 0
            if n != last + 1:
                raise SystemExit(f"{work['html']}: section {n} after {last}: {_plain(p)[:80]!r}")
            sections.append({"heading": f"{label} {n}", "chapter": None, "chapter_no": n,
                             "h2": f"<h2>{label} {n}.</h2>\n", "paras": []})
            p = p[sm.end():]
        elif not sections:
            raise SystemExit(f"{work['html']}: text before section 1: {_plain(p)[:80]!r}")
        sections[-1]["paras"].append(p)

    for s in sections:
        raw = "<br/><br/>\n".join(s.pop("paras")) + "\n"
        s["html"] = s.pop("h2") + hinted(raw)
        s["body"] = FOOTNOTE_REF_RE.sub("", raw)
    nos = [s["chapter_no"] for s in sections]
    if nos != list(range(1, len(nos) + 1)) or len(nos) < 2:
        raise SystemExit(f"{work['html']}: sections are not numbered 1..n: {nos}")
    return preamble, sections


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in PARA_SPLIT_RE.split(section["body"]):
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
    sections, named by its first and last section."""
    units = []
    for run in split_evenly(sections, cap):
        a, b = run[0]["chapter_no"], run[-1]["chapter_no"]
        units.append({
            "name": f"Part{len(units) + 1:03d}_S{a:02d}-{b:02d}.html",
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
    "We have Aphrahat the Persian Sage's \"{title}\" here: \"{units_dir}/{first_unit}\""
    "{more_units}. {piece_word} our PUBLIC-DOMAIN English translation, {edition}, "
    "\"{html_path}\" (consult it if you need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. Aphrahat (fl. 337-345), one of the earliest Syriac "
    "Fathers whose works survive, wrote twenty-three Demonstrations: treatises in the form of "
    "letters to an inquirer (\"my beloved\"), each on one subject of faith or practice, built "
    "almost entirely out of Scripture. He quotes the Syriac Bible (the Peshitta), retells "
    "biblical history at length, reads the Old Testament as types of Christ and the Church, "
    "and argues from Scripture against the Jews. Your task is to EXTRACT from the "
    "Demonstration the stretches that are genuinely commentary on a specific verse of "
    "Scripture, and file each under that verse in the \"{father}/\" folder. Much of the text "
    "will NOT be imported, and that is expected: a section with no exposition of a verse "
    "gives no block.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the work's title and heading line(s) at the top "
    "({head_what}); that is background for you, not text to import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Aphrahat QUOTES or "
    "plainly refers to a specific verse AND DOES SOMETHING WITH IT: says what it means, "
    "interprets its words (literally, morally or spiritually), resolves a difficulty in it, "
    "applies a figure or type in it (\"this was a type of ...\", Daniel's beasts and the "
    "image as the kingdoms, Jesus prefigured in Joseph, Moses or David), builds his argument "
    "on its wording (e.g. against the Jews, from how a prophecy is phrased), or APPLIES it to "
    "the life of faith in a way that shows how he reads it (a verse brought in to describe "
    "true faith, love, penitence or the life of the monks, and then drawn out). Do NOT import "
    "a verse quoted only in passing, a bare proof-text dropped into a sentence, a chain of "
    "proof-texts quoted without comment, a bare retelling of a biblical story, or exhortation "
    "that merely mentions Scripture. His long lists (\"Abel was persecuted, as Jesus was "
    "persecuted ...\"; \"by faith Noah ...\") are expositions of a verse only where he draws "
    "something out of it. Ask: would a reader studying this verse learn something about how "
    "Aphrahat understood or used it from this stretch? If so, import it; if it would only "
    "learn that Aphrahat quoted it, leave it out.\n\n"
    "VERSE KEYS. {note_what} Use them as HINTS only, and confirm every verse against the KJV "
    "wording with `" + KJV_LOOKUP + "`, filing under KJV book/chapter/verse numbering. "
    "Aphrahat's Syriac Bible often words a verse differently from the KJV (and sometimes "
    "follows a reading of its own): match by sense. Deuterocanonical books are fine "
    "(\"Sirach\", \"Wisdom\", ...): use only the book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Aphrahat's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the verse and the whole of his exposition of it. "
    "Don't pad a block with unrelated exhortation before or after "
    "the exposition. File it under the SMALLEST verse range the exposition really addresses: a "
    "single verse when it expounds one verse, a range only when it expounds several verses as "
    "one argument (a range crossing chapters is written like \"Matthew 5_48-6_1\"). When one "
    "stretch genuinely expounds two different passages (e.g. an Old Testament type and the "
    "Gospel verse that fulfils it, interpreted together), file the same text under each, as "
    "separate files; that is welcome. "
    "But never put two overlapping blocks of this Demonstration in the SAME file, and don't "
    "split one exposition into fragments under one verse.\n\n"
    "THE TEXT. Copy Aphrahat's words VERBATIM: nothing abridged, paraphrased, corrected, "
    "added or rearranged. Drop the html tags (italics simply become plain text; don't turn "
    "them into quotation marks) and separate paragraphs with a single blank line. Leave out "
    "the \"[note: ...]\" footnotes and the <h2> headings (\"Section 2.\"): the section numbers "
    "have already been removed from the text, so a paragraph that opened \"{example_no} "
    "{example}\" in the printed text reads \"{example}\" here, and so it must in your block. "
    "Keep the translator's parenthesised and square-bracketed supplements (\"(appointed)\", "
    "\"[saying]\") as printed, and the printed text's quotation marks, dashes (\"said:—\"), "
    "Syriac words, run-together words and misprints as they are. Don't add headings, verse "
    "numbers or notes of your own. Don't write a python script to do this; process the file "
    "yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this Demonstration, set:\n"
    "  source_url   = {source_url}\n"
    "{title_rule}\n\n"
    "EXISTING BLOCKS. The old imports of these Demonstrations have ALREADY been deleted, so you "
    "are only ADDING: if a verse file exists, append your [[commentary]] after its existing "
    "blocks; otherwise create it. Earlier pieces of THIS run (other Demonstrations, or earlier "
    "sections of this one) may already have left blocks from the Demonstrations in the files "
    "you write to: they are NOT old imports or duplicates; leave them exactly as they are and "
    "append yours after them. The remaining older excerpts in the folder (from Demonstrations "
    "4 \"On Prayer\", 9, 14 and 18, which have no new translation here, usually with an empty "
    "source_url) must be left exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- section, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


EDITION = {
    "npnf": ("A. E. Johnston's translation from the Syriac (Nicene and Post-Nicene Fathers, "
             "2nd series, vol. 13, 1898), which gives eight of the Demonstrations"),
    "hallock": ("F. H. Hallock's translation from the Syriac (Journal of the Society of "
                "Oriental Research, 1930-32)"),
}
HEAD_WHAT = {
    "npnf": "the translator's note on the edition, and the Demonstration's title",
    "hallock": "the journal citation",
}
NOTE_WHAT = {
    "npnf": (
        "The translator's footnotes are shown inline as \"[note: ...]\" in superscript, after "
        "the word they mark. Most give the reference of a quotation (\"Ps. cxviii. 22.\", "
        "\"Matt. vii. 24, 25.\", \"Cf.\" = an allusion, \"(Pesh.)\" = the Peshitta's wording); "
        "a few discuss the Syriac and give no verse. CAUTION with the Psalms: the notes' Psalm "
        "numbers are the English ones, but their VERSE numbers often follow the Hebrew/Syriac "
        "count, which numbers a psalm's title as verse 1, so they run one ahead of the KJV "
        "(\"Ps. xxii. 17–19\" is KJV Psalms 22:16-18, \"Ps. lxix. 22, 27\" is KJV 69:21, 26); "
        "a few are misprinted (\"Ps. xxiii. 45.\"). A note can also sit on the wrong quotation, "
        "or be missing."),
    "hallock": (
        "This translation has almost no footnotes; work out each verse from the quotation "
        "itself."),
}
EXAMPLE = {
    "npnf": ("§2.", "Faith is compounded of many things"),
    "hallock": ("2.", "And when thou proceedest"),
}


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    lab = work["label"]
    title_rule = (
        f"  source_title = \"{work['source_title']}, {lab} N\"\n"
        f"where N is the number of the {lab.lower()} the block comes from (the <h2> "
        f"headings), e.g. \"{work['source_title']}, {lab} 2\"; a block running across "
        f"{lab.lower()}s is \"{work['source_title']}, {lab}s 2-3\".")
    kind = work["kind"]
    return PROMPT1_TEMPLATE.format(
        title=work["source_title"],
        edition=EDITION[kind],
        head_what=HEAD_WHAT[kind],
        note_what=NOTE_WHAT[kind],
        example_no=EXAMPLE[kind][0],
        example=EXAMPLE[kind][1],
        units_dir=units_dir,
        first_unit=units[0]["name"],
        more_units=(f" with the files continuing up to \"{units_dir}/{units[-1]['name']}\""
                    if len(units) > 1 else ""),
        piece_word=("These are consecutive pieces cut, in order, from" if len(units) > 1
                    else "It is the whole Demonstration, from"),
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        father=FATHER,
        # (The driver passes the name tagged with the work, "AphDem22/Part002_...".)
        unit_name=os.path.basename(unit["name"]),
        headings=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        title_rule=title_rule,
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
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


def run_check(work, sections, quiet=False):
    """Return a list of problems (empty == all good). Prints a summary (with `quiet`, only
    failures). A selective import has no coverage to check: this checks that every block of
    this Demonstration is one verbatim stretch of it, found once, under a valid filename, with
    the right source_title (and that no block with this url has a title of no Demonstration)."""
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
        ours = [c for c in data.get("commentary", []) if c.get("source_url") == url]
        for c in ours:
            if not any(block_is_mine(w, c) for w in WORKS.values()):
                problems.append(f"{fn}: a block with this url has a source_title of no "
                                f"Demonstration: {c.get('source_title')!r}")
        mine = [c for c in ours if block_is_mine(work, c)]
        if not mine:
            continue
        files.add(fn)
        # (Athanasius's agents created 42 files opening with a blank line.)
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

    if not quiet or problems:
        print(f"\nCHECK {work['source_title']}: {n} block(s) in {len(files)} file(s); "
              f"{len(per_chapter)} of {len(sections)} section(s) used")
    if not quiet:
        for no in sorted(per_chapter):
            print(f"  {sections[no - 1]['heading']}: {', '.join(per_chapter[no])}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    elif not quiet:
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




def check_order(base=None):
    """Cross-work order: in each file, the Demonstrations' blocks (all appended after the
    files' BASE content) must follow Demonstration number, then source position. Works run out
    of sequence (the pilot) break it. With `base`, reorder only those appended blocks, by cutting
    the file text, and assert the BASE content stays a byte-identical prefix. Returns the files
    out of order (before any fix)."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    block_re = re.compile(r"(?m)^\[\[commentary\]\][ \t]*$")
    def key_of(c):
        hits = [k for k, w in WORKS.items() if block_is_mine(w, c)]
        return hits[0] if hits else None
    sources = {}

    def pos(k, quote):
        if k not in sources:
            secs = load_work(WORKS[k])[1]
            sources[k] = _norm(" ".join(" ".join(paragraphs_of(s)) for s in secs))
        return sources[k].find(_norm(quote))

    bad = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml") or fn == "metadata.toml":
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if "Aphrahat%2520the%2520Persian%2520Sage" not in text:
            continue
        starts = [m.start() for m in block_re.finditer(text)]
        blocks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
        parsed = tomllib.loads(text)["commentary"]
        assert len(parsed) == len(blocks), fn
        keys = [(WORKS[key_of(c)]["number"], pos(key_of(c), c["quote"]))
                if key_of(c) else None for c in parsed]
        mine = [i for i, k in enumerate(keys) if k]
        if not mine:
            continue
        if mine != list(range(mine[0], len(blocks))):
            print(f"  NOT APPENDED AT THE END: {fn}")
            bad.append(fn)
            continue
        order = sorted(mine, key=lambda i: keys[i])
        if order == mine:
            continue
        print(f"  OUT OF WORK ORDER: {fn[:-5]} {[keys[i] for i in mine]}")
        bad.append(fn)
        if base:
            new = text[:starts[mine[0]]] + "".join(
                blocks[i].rstrip("\n") + "\n\n" for i in order)
            new = new.rstrip("\n") + "\n"
            old = subprocess.run(["git", "-C", PROJECT_DIR, "show",
                                  f"{base}:{FATHER}/{fn}"], capture_output=True, text=True).stdout
            assert new.startswith(old.rstrip("\n")), fn
            assert tomllib.loads(new)["commentary"] == (
                parsed[:mine[0]] + [parsed[i] for i in order]), fn
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            print("    reordered")
    print(f"{len(bad)} file(s) out of work order" + (" (fixed)" if base and bad else ""))
    return bad


def expand_works(specs):
    """Work keys from the arguments: keys ("AphDem05") and ranges ("AphDem05-AphDem22")."""
    keys = sorted(WORKS)
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        if a not in WORKS or (b and b not in WORKS):
            raise SystemExit(f"unknown work {spec!r} (keys: {', '.join(keys)})")
        out += keys[keys.index(a):keys.index(b) + 1] if b else [a]
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "works", nargs="+",
        help="Demonstrations to import, run one after another (every piece of each): keys "
             "(AphDem05) and/or ranges (AphDem05-AphDem22).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folders and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true",
                      help="Run only the check (printing only failures when several works).")
    mode.add_argument("--order", action="store_true",
                      help="Check that every file holds the Demonstrations' blocks in order "
                           "(any works argument; all files are checked).")
    mode.add_argument("--fix-order", metavar="BASE",
                      help="As --order, and reorder the out-of-order files' appended blocks, "
                           "keeping their content at BASE (the deletion commit) unchanged.")
    args = parser.parse_args()
    if args.order or args.fix_order:
        sys.exit(1 if check_order(args.fix_order) and not args.fix_order else 0)
    keys = expand_works(args.works)

    loaded = {}
    for k in keys:
        pre, secs = load_work(WORKS[k])
        loaded[k] = (pre, secs, make_units(pre, secs, SPLIT_CHARS))

    if args.check:
        bad = [k for k in keys if run_check(WORKS[k], loaded[k][1], quiet=len(keys) > 1)]
        print(f"\n{len(keys) - len(bad)} of {len(keys)} Demonstration(s) pass the check"
              + (f"; failing: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    print(f"Work:       {FATHER}, Demonstrations ({len(keys)} work(s))")
    print(f"Agent cwd:  {PROJECT_DIR}")
    for k in keys:
        pre, secs, units = loaded[k]
        for u in units:
            size = sum(len(s["html"]) for s in u["sections"])
            print(f"  {k}  {u['name']:<22} {size:>6} chars  "
                  f"{', '.join(s['heading'] for s in u['sections'])}")

    if args.dry_run:
        k = keys[0]
        pre, secs, units = loaded[k]
        print(f"\nSource url: {source_url_for(WORKS[k])}")
        print(f"\n--dry-run: prompt 1 for {k} {units[0]['name']}:\n")
        print(build_prompt1(WORKS[k], units_dir_for(k), units, units[0]))
        print(f"\n[prompt 2 is always]: {PROMPT2}")
        return

    if args.split_only:
        for k in keys:
            pre, secs, units = loaded[k]
            print(f"Wrote {len(units)} piece(s) to {write_units(k, pre, units)}")
        return

    log_dir = os.path.join(WORK_DIR, "aphrahat_demonstrations_import_logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(log_dir, f"run-{stamp}.jsonl")
    events_path = os.path.join(log_dir, f"run-{stamp}.events.jsonl")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}\n")

    failed = []
    with open(log_path, "a") as log, open(events_path, "a") as events_log:
        for k in keys:
            pre, secs, units = loaded[k]
            units_dir = write_units(k, pre, units)
            for unit in units:
                # The log's unit names carry the work ("AphDem22/Part002_S08-15.html").
                tagged = dict(unit, name=f"{k}/{unit['name']}")
                try:
                    process_unit(WORKS[k], units_dir, units, tagged, log, events_log)
                except RuntimeError as exc:
                    print(f"  ABORTING at {k} ({unit['name']}): {exc}")
                    print(f"  (pieces kept in {units_dir})")
                    log.write(json.dumps({"unit": tagged["name"], "error": str(exc)}) + "\n")
                    log.flush()
                    sys.exit(1)
            shutil.rmtree(units_dir)
            if run_check(WORKS[k], secs):
                failed.append(k)

    print(f"\nDone. {len(keys)} Demonstration(s) processed.")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}")
    if failed:
        print(f"CHECK FAILED for: {', '.join(failed)} (see above)")


if __name__ == "__main__":
    main()
