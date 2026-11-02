#!/usr/bin/env python3
"""Import Theodoret of Cyrus's Commentary on Romans (the anonymous translation in "The Christian
Remembrancer", 1839-1840, notes signed "E. B.", as transcribed by Roger Pearse) into the
Commentaries-Database, one piece at a time, by driving a headless ``claude`` agent.

A per-father copy of process_cyril_commentary.py (see ../SKILL.md, "Other fathers"): the same
two-prompt flow, splitting, logs and --check. What differs is the source layout:

    Writings-Database/Theodoret of Cyrus/Commentary on Romans.html

    <h1>..</h1><i>source note</i>                (the preamble)
    <h2>Translator's Introduction</h2>           (the translator's: stripped, see WORKS["strip"])
    <h2>ARGUMENT.</h2>                           (Theodoret's argument of the epistle: the prologue)
    <h2>Chapter II.&nbsp;</h2>                   (a chapter of Romans)
    He proceeds now ... 1. <i>lemma</i> comment ... 2. <i>lemma</i> comment ...
    <h2>Book II.</h2>                            (one of Theodoret's five tomes begins: a preface,
    preface ... 9. <i>lemma</i> ...               then the chapter's verses run on under it)

The translator's verse numbers stand INSIDE the running text, often mid-sentence ("he then
begins his proposed design; 6. <i>Not as though ...</i>"). ``load_work`` cuts one section at
each of them, as Cyril's cuts at each label: the heading is "C:V" (the chapter from the last
"Chapter N" heading), the html keeps the number (the agent sees it as a hint), the body drops
every number (they are the translator's, not Theodoret's). A number is taken as a label only if
it follows on from the previous one within the chapter (prev < v <= prev + 5), so references
such as "(See John i. 29, 36. Acts viii. 32.)" are not cut. A label whose stretch holds nothing
but its italic lemma is joined to the next one ("15:1-2"). Text under a "Chapter" heading
before its first label (Theodoret's lead-in to the chapter) opens the first section; text under
"ARGUMENT." or a "Book" heading before the first label is a non-verse section.

    python3 process_theodoret_commentary.py Romans --dry-run
    python3 process_theodoret_commentary.py Romans --split-only
    python3 process_theodoret_commentary.py Romans Part002_Ch01b.html
    python3 process_theodoret_commentary.py Romans --start-after Part002_Ch01b.html
    python3 process_theodoret_commentary.py Romans --check
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

FATHER = "Theodoret of Cyrus"

# A chapter with more html than this is cut into near-equal parts at section boundaries.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "Romans": {
        "html": "Theodoret of Cyrus/Commentary on Romans.html",
        "book": "Romans",
        "source_title": "Commentary on Romans",
        # Labels lie in the running text: tolerate a section joined to the one before it in the
        # audit's LEMMA check (see audit_jerome_import.py).
        "label_sections": True,
        "strip": [
            # The translator's introduction (Theodoret's life, Dupin's and Photius's praise).
            r"(?s)<h2>Translator's Introduction</h2>.*?(?=<h2>ARGUMENT\.</h2>)",
        ],
        "notes": (
            "The translator's verse numbers are mostly right, but check each against the wording "
            "(four misprints have been corrected in the source: 3:26, 8:29 and 16:24 had been printed "
            "\"25.\", \"39.\" and \"21.\", and 1:3 \"3:\"). The \"4.\" in chapter 5 stands before \"Knowing "
            "that tribulation worketh patience, and patience proof,\", the end of KJV 5:3. 16:6 has "
            "no number: \"Greet Mary, who bestowed much labour on us\" and its comment come inside the "
            "16:5 section; file them under Romans 16_6. In 3:9-18 Paul's chain of quotations (\"As it "
            "is written, There is none righteous, no, not one:\" ...) is printed in plain text with "
            "the numbers between; file Theodoret's comments on them under the verses they explain, "
            "with a range where one comment covers several. Theodoret often quotes a verse in pieces "
            "and comments on each piece; a verse's pieces and their comments make one block.\n\n"
            "THE DOXOLOGY, ROMANS 16:25-27. Like the Greek manuscripts Theodoret read, his text "
            "places it after 14:23, with no verse number, at the end of the \"14:23\" section: from "
            "\"And that he may prove himself enjoining what is agreeable to God, he offers up a "
            "fervent prayer in their behalf; Now to Him that is of power to stablish you\" to the end "
            "of the chapter (\"But leaving such to their own folly, let us proceed onwards in our "
            "course. Having then thus offered up these supplications for them, the holy Apostle adds "
            "exhortations, giving praise to the Gentile converts, and designating them as strong, by "
            "reason of their faith.\"). File that whole stretch, as one block, under \"Romans "
            "16_25-27\", and the 14:23 comment before it (\"But he that maketh a distinction is "
            "condemned if he eat ... passes sentence on himself.\") under Romans 14_23. Chapter 16's "
            "comment on 16:24 ends the work; nothing else of 16:25-27 follows it.\n\n"
            "THE ARGUMENT (the prologue). \"ARGUMENT.\" is Theodoret's argument of the whole "
            "epistle (\"Various and comprehensive is the doctrine which the holy apostle unfolds in "
            "the present epistle.\" ... \"Such then is the general argument of the epistle, all the "
            "particulars in which the interpretation of the separate passages will now clearly make "
            "known to us.\"). Import it whole, as ONE block of its own, the FIRST block of \"Romans "
            "1_1\" (there is no other Theodoret block there), before the 1:1 commentary. Don't cross-file "
            "it.\n\n"
            "THE TOME PREFACES (\"Book II.\" ... \"Book V.\"): each is Theodoret's own summary of the "
            "argument so far, leading into the next part; import each WHOLE as its own block, the "
            "first block of the file named here, before that verse's commentary. \"Book II.\" (\"We "
            "have already said, that the holy apostle was desirous of showing the necessity of the "
            "incarnation\" ... \"he next produces his medicine of faith, and sets forth the "
            "loving-kindness of the divine dispensation, and says,\") goes in \"Romans 3_9\". "
            "\"Book III.\" is an empty heading: the 6:12 commentary follows it directly. \"Book IV.\" "
            "(\"That the incarnation of our God and Saviour both was necessary\" ... \"Being about then "
            "to denounce the infidelity of the Jews, he first displays the love he bore them, and "
            "says,\") goes in \"Romans 9_1\". \"Book V.\" (\"The knowledge of the nature of God, and "
            "faith, and right affections towards Him, are the sum and true foundation of all good\" "
            "... \"and thus he opens the subject.\") goes in \"Romans 12_1\". Don't join a preface to "
            "the verse block after it.\n\n"
            "THE ENDS OF THE TOMES. Each tome ends with an exhortation and a doxology. Book I's "
            "closes the exposition for a while and is NOT imported: at the end of the \"3:8\" section, "
            "leave out the stretch from \"And here, ceasing from our exposition awhile, and resting "
            "our mind, let us laud and magnify Him\" to \"belong glory and majesty, now and for ever, "
            "unto endless ages. Amen.\" The others apply the verse just expounded and stay, at the "
            "end of that verse's block: after 6:11 (\"To this advice it behoves us all to take heed, "
            "flying from the snares of sin\" ... \"Amen.\"), after 8:38-39 (\"Which therefore that "
            "ourselves may also possess, let us both pray and strive\" ... \"Amen.\"), after 11:36 "
            "(\"Let us then, leaving such (arguers) for the present, magnify our Creator and Saviour, "
            "to whom belongs glory for ever and ever. Amen.\") and at the end of the work, after 16:24 "
            "(\"In this grace let us also become partakers, that we may rise superior to all snares\" "
            "... \"Amen.\"): import each to its end.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. When a lemma quotes two verses but the comment "
            "after it addresses only the first, file that block (lemma included, uncut) under that "
            "verse alone. The lemma's span never widens a block's range. When Theodoret comes back "
            "to an earlier verse inside a later section (e.g. the 3:18 section returns to \"In "
            "what then are we better than they?\", 3:9), keep the stretch in its place, in the "
            "block of the verse that section explains, unless it is a real exposition of the "
            "earlier verse that stands on its own.\n\n"
            "Keep everything verbatim, as printed, including the translator's bracketed references "
            "and supplied words, \"[Greek]\", the Greek letters, \"&c.\" (as the \"&\" character) and "
            "the dashes and quotation marks; the pieces have had the translator's footnote markers "
            "removed (the full source html still has them, with his notes signed \"E. B.\"; none of "
            "them is imported). The translator gives Psalm references in roman numerals and once "
            "with an LXX number (\"Ps. l. (LXX. li. 14, 23\"): find any cross-reference by matching "
            "the wording against the KJV.\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Romans\" blocks in the files you write to (a block from the piece "
            "before yours, or a cross-reference). Those are NOT old imports or duplicates: leave "
            "them exactly as they are and append yours after them. Other Theodoret files hold "
            "excerpts of his other works (e.g. \"INTERPRETATION OF HEBREWS 11\"): leave them first and "
            "untouched."
        ),
    },
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the existing Theodoret of Cyrus source_urls ("file=Theodoret%2520of%2520Cyrus%2F...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"theodoret_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn\d+" id="r\d+">\d+</a></sup>')
NOTES_SECTION_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">.*?</section>\s*', re.S)
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _roman(r):
    return sum(-ROMAN[c] if i + 1 < len(r) and ROMAN[c] < ROMAN[r[i + 1]] else ROMAN[c]
               for i, c in enumerate(r))


# A candidate verse number in the running text: "6. <i>Not as though", "&#8212;7. <i>For he",
# "&nbsp;19. <i>And not", "9. For this is the word" (a lemma not in italics). Not after a letter,
# digit, period or comma (that is a reference: "Exod. iii. 15", "29, 36.").
LABEL_RE = re.compile(
    r"(?<![\w.,(])(?P<v>\d{1,2})\.(?:\s|&nbsp;)*(?=(?:<sup>.*?</sup>\s*)?<i>|[A-Z\"(&])")


def find_labels(body, prev=None):
    """[(start, end, verse)] of the verse labels in a heading's body, in order: only numbers
    that follow on from the previous label (prev < v <= prev + 5; the chapter's first <= 5).
    `prev` carries a chapter's last verse across a Book heading."""
    out = []
    for m in LABEL_RE.finditer(body):
        v = int(m["v"])
        if (prev is None and v <= 5) or (prev is not None and prev < v <= prev + 5):
            out.append((m.start(), m.end(), v))
            prev = v
    return out


def _cut(body, a, e, labels):
    """body[a:e] without the label spans inside it."""
    out, j = [], a
    for s, t, _ in labels:
        if a <= s < e:
            out.append(body[j:s])
            j = t
    return "".join(out) + body[j:e]


def load_work(work):
    """Return (preamble_html, sections): one section per verse label (heading "C:V", or "C:V-W"
    for a lemma-only label joined to the next), plus the non-verse sections (ARGUMENT, the Book
    prefaces). Each keeps its raw html (heading and labels included), its body (without them)
    and its chapter (None if non-verse)."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # The translator's (E. B.'s) notes are editorial apparatus: drop the markers and the notes.
    text = FOOTNOTE_REF_RE.sub("", text)
    text = NOTES_SECTION_RE.sub("", text)
    cut = text.find("<h2>")
    for pat in work.get("strip", []):
        text = text[:cut] + re.sub(pat, "", text[cut:])
    parts = H2_RE.split(text)
    preamble = parts[0]
    sections, chapter, last_v = [], None, None
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        heading = _clean(h2)
        body = parts[i + 1].replace("</article>", "").lstrip("\n").rstrip() + "\n"
        is_chapter = re.fullmatch(r"Chapter ([IVXL]+)\.", heading)
        if is_chapter:
            chapter, last_v = _roman(is_chapter[1]), None
        labels = find_labels(body, last_v) if chapter else []
        if labels:
            last_v = labels[-1][2]
        lead_end = labels[0][0] if labels else len(body)
        lead = body[:lead_end]
        if _clean(lead) and not (is_chapter and labels):
            # ARGUMENT. or a Book preface: a non-verse section.
            sections.append({"heading": heading, "chapter": None, "html": h2 + "\n" + lead,
                             "body": lead})
            h2 = ""
        if not labels:
            continue
        # One run per label; a run holding nothing but its italic lemma joins the next.
        runs = []
        for k, (a, t, v) in enumerate(labels):
            e = labels[k + 1][0] if k + 1 < len(labels) else len(body)
            if runs and runs[-1]["join"]:
                runs[-1].update(e=e, hi=v)
            else:
                runs.append({"a": a, "e": e, "lo": v, "hi": v})
            rest = re.sub(r"<i>.*?</i>", "", body[t:e], flags=re.S)
            runs[-1]["join"] = not re.search(r"[A-Za-z]", _clean(rest)) and k + 1 < len(labels)
        for k, r in enumerate(runs):
            # A chapter's lead-in (Theodoret's opening words before the first label) opens its
            # first section; the <h2> stays in the html of the first section after it.
            a = 0 if (not k and is_chapter) else r["a"]
            head = f"{chapter}:{r['lo']}" + (f"-{r['hi']}" if r["hi"] != r["lo"] else "")
            sections.append(
                {
                    "heading": head,
                    "chapter": chapter,
                    "html": (h2 + "\n" if h2 and not k else "") + body[a:r["e"]],
                    "body": _cut(body, a, r["e"], labels),
                }
            )
    return preamble, sections


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in re.split(r"(?:<br\s*/?>\s*){2,}", section["body"]):
        p = _clean(p)
        if p:
            out.append(p)
    return out


def chapter_groups(sections):
    """Contiguous runs of sections by chapter; a non-verse section joins the group of the
    verse section after it (or the last group, if nothing follows)."""
    groups, pending = [], []
    for s in sections:
        if s["chapter"] is None:
            pending.append(s)
            continue
        if not groups or groups[-1]["chapter"] != s["chapter"]:
            groups.append({"chapter": s["chapter"], "sections": []})
        groups[-1]["sections"].extend(pending + [s])
        pending = []
    if pending:
        if not groups:
            groups.append({"chapter": 0, "sections": []})
        groups[-1]["sections"].extend(pending)
    return groups


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
    """The ordered list of pieces: {name, chapter, sections}."""
    units = []
    for g in chapter_groups(sections):
        runs = split_evenly(g["sections"], cap)
        for j, run in enumerate(runs):
            suffix = chr(ord("a") + j) if len(runs) > 1 else ""
            units.append(
                {
                    "name": f"Part{len(units) + 1:03d}_Ch{g['chapter']:02d}{suffix}.html",
                    "chapter": g["chapter"],
                    "sections": run,
                }
            )
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
    "We have Theodoret of Cyrus's {title} here: \"{units_dir}/{first_unit}\" with the files "
    "continuing up to \"{units_dir}/{last_unit}\". These are consecutive pieces cut, in order, "
    "from our PUBLIC-DOMAIN English translation of the whole work (the anonymous one printed in "
    "\"The Christian Remembrancer\", 1839-1840), \"{html_path}\" (consult it if you need "
    "surrounding context). The work is Theodoret's verse-by-verse commentary on the Epistle to "
    "the {book} -- file everything under the book \"{book}\", in the \"{father}/\" folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections, by the translator's verse numbers, and its headings: "
    "{headings})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. Each "
    "piece repeats the work's title and the source note at the top -- that note is background "
    "for you, not commentary; don't import it.\n\n"
    "VERSE KEYS. The <h2> headings are the epistle's chapters (\"Chapter IX.\") and the "
    "openings of Theodoret's five tomes (\"Book II.\", which can fall inside a chapter: the "
    "chapter's verses run on under it). Inside a chapter the translator's verse numbers stand "
    "in the running text, often in mid-sentence (\"he then begins his proposed design; 6. "
    "<i>Not as though the word of God hath taken none effect</i>.\"), each followed by the "
    "verse quoted (the lemma), usually in italics, sometimes in plain text. Theodoret often "
    "quotes a verse in pieces as he goes, in italics too. Treat the numbers as HINTS ONLY: "
    "they may be off. For each stretch of commentary, work out which KJV verse(s) it actually "
    "expounds -- compare the Scripture Theodoret quotes and discusses with the KJV text, looking "
    "it up with `" + KJV_LOOKUP + "` -- and file it there, under KJV chapter/verse "
    "numbering.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. Theodoret "
    "comments verse by verse, usually briefly: file each verse's comment under that verse "
    "(e.g. a stretch on 9:6 goes in \"Romans 9_6\"). Where he treats two or three verses as one "
    "thought (he quotes them together, or one comment explains them all), use a range rather "
    "than chopping a coherent comment into fragments; just prefer single verses. A stretch "
    "that is only a verse quoted, with no comment of its own before the next verse number, "
    "goes with the comment that explains it. Each block must be one continuous stretch of "
    "Theodoret, in his order, and the blocks together must hold the WHOLE text, every word "
    "(apart from what the notes say to leave out). Never cut up or move a lemma. Do NOT "
    "duplicate the same stretch of commentary across several {book} verses -- put it ONCE, at "
    "its smallest accurate verse/range.\n\n"
    "WHERE BLOCKS START. A verse's block starts where the translator's verse number stood: "
    "with the lemma's first words, even when the number falls in mid-sentence -- the words "
    "before the number (\"he then begins his proposed design;\") end the previous block. The "
    "only exception is a chapter's opening words before its first verse number (e.g. Chapter "
    "II's \"He proceeds now in another way to prove our possession of the power of "
    "discriminating between good and evil.\"): they open that chapter's first block.\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the within-{book} duplication "
    "forbidden above). Theodoret quotes much other Scripture. Whenever a stretch genuinely "
    "QUOTES AND EXPOUNDS a specific verse from another book -- says what it means, not merely "
    "cites it -- you may ALSO file that portion under that verse in its own file (e.g. "
    "\"Genesis 15_6\"), in addition to its {book} placement. Most of his quotations are passing "
    "proof-texts (often with the translator's reference in brackets, \"(Exod. iii. 15)\"): do "
    "not cross-file those, nor the Old Testament verses Paul himself quotes in the epistle "
    "(they are the lemma's, not Theodoret's exposition of the prophet). Use KJV book/verse "
    "numbering for the target file, matching a Psalm by its wording.\n\n"
    "NON-VERSE SECTIONS. \"ARGUMENT.\" (Theodoret's argument of the epistle) and the tome "
    "prefaces (\"Book II.\" etc.) hold no verse numbers: the notes above say where each goes.\n\n"
    "THE TEXT. Copy Theodoret's words VERBATIM -- nothing abridged, paraphrased, corrected, "
    "added or rearranged -- and keep the lemma where it stands in the source. Drop the html "
    "tags (italics simply become plain text; don't turn them into quotation marks) and "
    "separate paragraphs with a single blank line. Leave out the <h2> headings and the "
    "translator's verse numbers (\"6.\", \"18.\"): copy the text around a number as if it "
    "were not there. Keep everything else as printed: the translator's references in "
    "brackets (\"(Exod. iii. 15)\", \"(see Isa. xliii. 10; xlv. 21, 23; xliv. 6, 8, &c.,)\"), "
    "his words supplied in brackets (\"the gospel (covenant)\"), \"[Greek]\" where a Greek "
    "word was lost, Greek letters, \"&c.\" (as the \"&\" character), dashes and quotation "
    "marks. Don't add headings, verse numbers or notes of your own. Don't write a python "
    "script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- the whole work sits behind one page).\n\n"
    "EXISTING BLOCKS. The old imports of this work (url-less excerpts of another translation) "
    "have ALREADY been deleted, so you are only ADDING: if a verse file exists, append your "
    "[[commentary]] after its existing blocks; otherwise create it. Blocks from other works "
    "must be left exactly as they are."
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
        book=work["book"],
        father=FATHER,
        unit_name=unit["name"],
        headings=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        source_title=work["source_title"],
    )


# --- Deterministic post-import check ------------------------------------------

OLD_RESIDUE_RE = re.compile(r"\((?:Chap\.|Chapter \d|Vers?\.|Verses? \d)")
PROBE_WORDS = 8
# Scribal rubrics the prompt tells the agent to leave out; not counted as missing.
RUBRIC_RE = re.compile(r"^HERE (?:BEGINS|ENDS)\b")


def _norm(s):
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", s).strip()


def run_check(work, sections):
    """Return a list of problems (empty == all good). Prints a summary."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    url = source_url_for(work)
    book = work["book"]
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        books = json.load(f)["canonical_names"]
    filename_re = re.compile(
        "(" + "|".join(map(re.escape, books)) + r") \d+_\d+(?:-\d+(?:_\d+)?)?\.toml"
    )
    problems, quotes, files_used, cross, contiguity = [], [], 0, [], []
    source = _norm(" ".join(" ".join(paragraphs_of(s)) for s in sections))
    # "(Verse 11)"-style references that the source itself contains are not residue.
    genuine = set(OLD_RESIDUE_RE.findall(source))

    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        path = os.path.join(folder, fn)
        own_book = fn.startswith(book + " ")
        if not own_book:
            # Cross-book parallels: only files that mention this work's url.
            with open(path, encoding="utf-8") as f:
                if url not in f.read():
                    continue
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{fn}: TOML parse error: {exc}")
            continue
        mine = [c for c in data.get("commentary", []) if c.get("source_url") == url]
        if not mine:
            continue
        if not filename_re.fullmatch(fn):
            problems.append(f"{fn}: filename is not '<Book> C_V' / 'C_V-V' / 'C_V-C_V'")
        if own_book:
            files_used += 1
        else:
            cross.append(fn[:-5])
        for c in mine:
            q = c.get("quote", "")
            contiguity.append((fn, q))
            # Coverage is judged on the commented book's own files only.
            if own_book:
                quotes.append(q)
            if c.get("source_title") != work["source_title"]:
                problems.append(f"{fn}: wrong source_title {c.get('source_title')!r}")
            if any(r not in genuine for r in OLD_RESIDUE_RE.findall(q)):
                problems.append(f"{fn}: old-translation residue in a block")
            if re.search(r"</?i>", q):
                problems.append(f"{fn}: leftover html tag in a block")

    for stale in work.get("stale_files", []):
        if os.path.exists(os.path.join(folder, stale + ".toml")):
            problems.append(f"{stale}.toml: stale old-translation file still exists")

    for fn, q in contiguity:
        if _norm(q) not in source:
            problems.append(
                f"{fn}: block is not one continuous stretch of the source (text cut up, "
                f"rearranged or altered): {_norm(q)[:80]!r}"
            )

    haystack = _norm(" ".join(quotes))
    probed = 0
    for s in sections:
        for i, p in enumerate(paragraphs_of(s), 1):
            if RUBRIC_RE.match(p):
                continue
            words = _norm(p).split(" ")
            for label, probe in (("start", words[:PROBE_WORDS]), ("end", words[-PROBE_WORDS:])):
                probed += 1
                if " ".join(probe) not in haystack:
                    problems.append(
                        f"section {s['heading']!r} paragraph {i} {label} not found: "
                        f"{' '.join(probe)!r}"
                    )

    print(f"\nCHECK: {len(quotes)} block(s) of this work in {files_used} {book} file(s); "
          f"{probed} paragraph probes")
    print(f"Cross-book parallels ({len(cross)}): {', '.join(cross) or 'none'}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        print("(A non-verse section the agent deliberately skipped will show up as "
              "'not found' -- confirm in the log that it was skipped on purpose.)")
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
    parser.add_argument("work", choices=sorted(WORKS), help="Which commentary to import.")
    parser.add_argument(
        "single", nargs="?",
        help="Process ONE piece (e.g. Part002_Ch02.html); see --dry-run for the names.",
    )
    parser.add_argument(
        "--start-after", metavar="NAME",
        help="Resume after this piece (e.g. Part001_Ch01.html).",
    )
    parser.add_argument(
        "--through", metavar="NAME",
        help="Stop after this piece (e.g. Part020_Ch12.html); combine with --start-after "
             "to run a chunk.",
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
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        if work["book"] not in json.load(f)["canonical_names"]:
            raise SystemExit(f"Book {work['book']!r} is not in book_names.json")
    preamble, sections = load_work(work)
    units = make_units(preamble, sections, args.split_chars)
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
          f"(chapters over {args.split_chars} chars cut):")
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

    log_dir = os.path.join(WORK_DIR, f"theodoret_{args.work.lower()}_import_logs")
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
