#!/usr/bin/env python3
"""Import Berengaudus's Exposition on the Seven Visions of the Book of Revelation (in a fresh,
public-domain translation) into the Commentaries-Database, one piece at a time, by driving a
headless ``claude`` agent.

A per-father copy of process_jerome_commentary.py (see ../SKILL.md, "Other fathers"): the same
two-prompt flow (import, then "Double check, was this fully imported properly?"), the same
splitting, logs and --check. What differs is the source layout:

    Writings-Database/Berengaudus/Commentary on Revelation/English.html

    <h1>..</h1><i>translator's note</i>   (the preamble)
    <h2>Translator's Introduction</h2>    (the translator's essay: stripped, see WORKS["strip"])
    <h2>On the First Vision</h2>          (non-verse: the preface opening each of the seven
                                           visions; the fourth to seventh begin mid-chapter)
    <h2>Chapter 1</h2>                    (a chapter, holding one lemma after another:)
    <b>Revelation 1:1a <i>lemma</i></b><br><br>
    exposition<br><br>...
    <h2>The Author's Admonition</h2>      (non-verse: the closing note)

``load_work`` cuts every chapter (and the lemma part of every vision section) into one section
per bold lemma, so that the rest -- pieces, prompts, --check, the audit and import_checks.py --
works as it does for Jerome's <h2>-per-lemma works. A lemma section's heading is the
translator's verse label ("1:1a", "1:13b-16"); its html keeps the label (the agent sees it, as
a hint), its body drops it (the label is not Berengaudus's text, so it isn't imported or
checked), as a Jerome section's body drops its <h2>.

    python3 process_berengaudus_commentary.py Revelation --dry-run
    python3 process_berengaudus_commentary.py Revelation --split-only
    python3 process_berengaudus_commentary.py Revelation Part002_Ch01b.html
    python3 process_berengaudus_commentary.py Revelation --start-after Part002_Ch01b.html
    python3 process_berengaudus_commentary.py Revelation --check
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

FATHER = "Berengaudus"

# A chapter with more html than this is cut into near-equal parts at <h2> boundaries.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "Revelation": {
        "html": "Berengaudus/Commentary on Revelation/English.html",
        "book": "Revelation",
        "source_title": "Commentary on Revelation",
        # Each lemma is a bold paragraph (see load_work); the audit's lemma detector needs this.
        "bold_lemmas": True,
        # The translator's essay (on authorship, sources and themes, quoting passages of the
        # commentary) is not Berengaudus's text.
        "strip": [r"(?s)<h2>Translator’s Introduction</h2>.*?(?=<h2>)"],
        "notes": (
            "The translator's labels mostly follow the KJV verses, but check each against the "
            "wording. Known exceptions: \"12:18\" (\"And he stood upon the sand of the sea.\") is the "
            "first half of KJV 13:1, since the KJV's chapter 12 ends at verse 17: file it under "
            "\"Revelation 13_1\" (it comes first there, before the 13:1 lemma that opens the next "
            "piece). \"3:10a\" opens with the end of KJV 3:9 (\"Behold, I will make them come and "
            "worship at your feet, and they will know that I have loved you;\") before 3:10's "
            "first clause, and its comment is on that worship at the angel's feet. \"1:18a\" "
            "(\"I am the first and the last.\") is the end of KJV 1:17: file it under "
            "\"Revelation 1_17\", after the 1:17a and 1:17b blocks. \"14:8b\" "
            "(\"And another angel followed, saying.\") is the start of KJV 14:8. Berengaudus "
            "passes over some verses (3:6, 3:13, 3:22) without a lemma; that is fine. A range "
            "crossing chapters would be written like \"Revelation 12_17-13_1\".\n\n"
            "EVERY LEMMA STARTS ITS OWN BLOCK. Each bold lemma (its verse label dropped) stays "
            "whole, uncut, at the start of the first block from it, and a block never runs on "
            "from one lemma's comment into the next lemma: even when consecutive lemmas are parts "
            "of the same verse (\"1:1a\", \"1:1b\", \"1:1c\"), each is its own block, and they go in "
            "the same verse file one after the other. The lemma is the whole bold paragraph, "
            "including the remarks the translator left in it between the bold stretches: \"The "
            "seven stars, he says, are the angels of the seven churches\" (1:20b), \"And from the "
            "throne (that is, from the Church) proceed lightnings, and voices, and thunders.\" "
            "(4:5a), \"And I have the keys of death and of hell [inferni].\" (1:18c). The one "
            "irregular lemma is \"1:13b-16\": its paragraph runs \"It follows: Clothed in a long "
            "garment, and tightened about the breast with a golden belt;\" on through 1:16, and "
            "the comment then takes the verses one at a time, each opening with its words in "
            "italics (\"But his head and hair were white like white wool and like snow\", \"And "
            "his feet were like fine brass, as in a burning furnace\", \"And he had in his right "
            "hand seven stars\", \"And his face was like the sun shining in its strength\"), so "
            "split it there by verse. Most lemmas' comments are short and are then one block. A "
            "long comment may be split further, between paragraphs or sentences, only where it "
            "really moves on to another verse than its lemma's; don't chop it into tiny "
            "fragments, and use a range when a stretch treats several verses as one argument.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "comment after it addresses only the first of them, file that block (lemma included, "
            "uncut) under that verse alone; and \"3:10a\" above goes under \"Revelation 3_9\", "
            "because its comment is on 3:9. The lemma's span never widens a block's range; e.g. "
            "\"19:1-8\" and \"14:14-19\" quote long passages, so follow the comment verse by verse.\n\n"
            "THE LONG EXCURSUSES. Some lemmas carry long typological expositions of Old "
            "Testament narratives: \"4:5c\" (Isaiah's seven gifts of the Spirit), \"6:3a\" (the ark "
            "and the dove of Noah, then Abraham and Isaac, Esau and Jacob, Jacob's ladder and "
            "wrestling), \"6:5a\" (Moses: the burning bush, the rod, the Law), \"6:7\" (David and "
            "the Philistine, Elijah and the widow of Zarephath, Elisha and Naaman). In Revelation "
            "they belong under the lemma's verse (\"4:5c\" under \"Revelation 4_5\", \"6:3a\" under "
            "\"Revelation 6_3\", and so on); there is no need to cut them up within that file. "
            "Where a stretch of such an excursus genuinely quotes and expounds a particular "
            "Old Testament verse or passage, ALSO file that stretch, as its own block, under that "
            "verse, by the CROSS-BOOK rule above (e.g. the ark's measurements under the Genesis "
            "verse that gives them). Keep each such cross-reference to the smallest range that "
            "matches what the stretch expounds, and don't cross-file bare proof-texts.\n\n"
            "Keep everything verbatim, including the translator's square brackets giving the "
            "Latin (\"[Apocalypsis]\", \"[inferni]\"), the translator's Scripture references in "
            "parentheses, which stay in the text exactly as printed (\"(Jn. 13:25)\", \"(Ps. "
            "83:5)\", \"(On chapter 2)\", \"(above in chapter 15)\"), the curly double and single "
            "quotation marks as printed (don't add or remove any), the en dashes, and the "
            "NON-BREAKING HYPHENS (U+2011) in words like \"two‑edged\", \"ankle‑length\" and "
            "\"father‑in‑law\": copy them as that same character, not as a plain hyphen. The "
            "pieces have had the translator's footnote markers removed, and the full html's notes "
            "section is the translator's, not Berengaudus's: import neither. The translator's "
            "Scripture references number the Psalms by the Latin (Vulgate) Bible, chapter and "
            "verse: \"The sacrifice to God is a repentant spirit (Ps. 50:19)\" is KJV Psalm 51:17, "
            "\"The Lord said to my Lord, Sit at my right hand (Ps. 109:1)\" is KJV 110:1, "
            "\"Blessed are they who dwell in your house, O Lord; they shall praise you for ages of "
            "ages\" (Ps. 83:5) is KJV 84:4. So find any Psalm cross-reference by matching the "
            "wording against the KJV.\n\n"
            "Earlier pieces of THIS run have already imported their chapters, so you may find "
            "\"Commentary on Revelation\" blocks in the files you write to (e.g. a block from the "
            "piece before yours under the same verse, or a cross-reference). Those are NOT old "
            "imports or duplicates: leave them exactly as they are and append yours after them. "
            "Other fathers' folders are not touched; Berengaudus has no other works in this "
            "folder.\n\n"
            "THE FIXED DECISIONS -- these are already made; follow them rather than judging for "
            "yourself. Each of the seven visions opens with a short preface, the text under its "
            "\"On the ... Vision\" heading before its first lemma; each is filed whole, as a block "
            "of its own, under the first verse of the vision, BEFORE that verse's lemma blocks:\n"
            "- \"On the First Vision\" (\"It is certain that the blessed John\" to \"clearly show that "
            "it was his.\") is also the work's prologue: it is the FIRST block of "
            "\"Revelation 1_1\" (a new file; the old import's file was deleted), followed by the "
            "1:1a, 1:1b and 1:1c lemma blocks, one each.\n"
            "- \"On the Second Vision\" (\"Reason requires that after the seven letters\" to "
            "\"should be described more clearly.\"): first block of \"Revelation 4_1\".\n"
            "- \"On the Third Vision\" (\"Not without reason, after the description of the form of "
            "the Church\" to \"according to apostolic faith.\"): first block of \"Revelation 5_1\".\n"
            "- \"On the Fourth Vision\" (\"By the abundance of the grace of our Lord Jesus Christ\" "
            "to \"the teachers of the Law.\"): first block of \"Revelation 8_6\"; it stands in the "
            "middle of chapter 8, after the 8:5 lemma.\n"
            "- \"On the Fifth Vision\" (\"The fifth vision, whose meaning we have now reached\" to "
            "\"full of the wrath of God upon the ungodly.\"): first block of \"Revelation 15_5\", "
            "after the 15:3b-4 lemma.\n"
            "- \"On the Sixth Vision\" (\"By the mercy of our Lord Jesus Christ, we have come to the "
            "sixth vision\" to \"will be fulfilled in the resurrection.\"): first block of "
            "\"Revelation 20_11\", after the 20:10b lemma.\n"
            "- \"On the Seventh Vision\" (\"The seventh vision, which by the Lord’s gift we have "
            "reached\" to \"under the figure of the city of Jerusalem.\"): first block of "
            "\"Revelation 21_9\".\n"
            "Each vision ends with a short prayer growing out of the last verse expounded (e.g. at "
            "3:21, \"May he of whom we speak grant this to us, that in the distribution of these "
            "thrones\"; at 4:11b, \"Therefore, may he himself, who created all things out of "
            "nothing, consent to create in us a pure heart\"; and likewise at 8:5, 15:3b-4, 20:10b, "
            "21:8 and 22:21): KEEP each one, at the end of that verse's block. \"The Author’s "
            "Admonition\" at the end (\"Whoever wishes to know the author’s name\" to \"or at least "
            "changed for the better.\") is the author's closing note on his name and his rustic "
            "style: skip it whole, and say so. The work's commentary ends with 22:21 (\"He lives "
            "and reigns with the Father and the Holy Spirit for ever and ever. Amen.\"): import "
            "it to its end."
        ),
    },
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file (path segments are
    double-encoded after the father folder, matching the existing source_urls)."""
    father, *rest = work["html"].split("/")
    # A work in a subfolder ("Commentary on Revelation/English.html") keeps %2F between its
    # segments, as the existing source_urls do.
    inner = "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in rest)
    return (
        "https://historicalchristian.faith/by_father.php?file="
        f"{quote(father)}%2F{inner}"
    )


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"berengaudus_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
CHAPTER_RE = re.compile(r"^(\d+):\d")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn\d+" id="r\d+">\d+</a></sup>')
NOTES_SECTION_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">.*?</section>\s*', re.S)


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def load_work(work):
    """Return (preamble_html, sections): one section per lemma (heading = its verse label),
    plus the non-verse sections. Each keeps its raw html (heading and label included), its
    body (without them) and the chapter it belongs to (None if non-verse)."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Translator's footnotes (alternative Latin readings, corrected references) are
    # editorial apparatus, not Berengaudus: drop the inline markers and the notes section.
    text = FOOTNOTE_REF_RE.sub("", text)
    text = NOTES_SECTION_RE.sub("", text)
    # Other editorial marks a work asks to drop from its sections (not from the preamble).
    cut = text.find("<h2>")
    for pat in work.get("strip", []):
        text = text[:cut] + re.sub(pat, "", text[cut:])
    parts = H2_RE.split(text)
    preamble = parts[0]
    sections = []
    # The translator's verse label opening each lemma: "<b>Revelation 1:13b-16" (once with an
    # en dash, "2:26–27").
    label_re = re.compile(rf"<b>{re.escape(work['book'])} (\d+):(\d+[a-h]?(?:[-–]\d+[a-h]?)?) ?")
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        heading = _clean(h2)
        body = parts[i + 1].replace("</article>", "").rstrip() + "\n"
        lead, *lemmas = re.split(rf"(?=<b>{re.escape(work['book'])} \d)", body.lstrip("\n"))
        if _clean(lead) or not lemmas:
            # Non-verse: a vision's preface (the text before its first lemma), or the Admonition.
            sections.append({"heading": heading, "chapter": None, "html": h2 + "\n" + lead,
                             "body": lead})
            h2 = ""
        for k, chunk in enumerate(lemmas):
            m = label_re.match(chunk)
            sections.append(
                {
                    "heading": f"{m[1]}:{m[2].replace('–', '-')}",
                    "chapter": int(m[1]),
                    # A "Chapter N" heading stays in the html of the chapter's first lemma.
                    "html": (h2 + "\n" if h2 and not k else "") + chunk,
                    "body": label_re.sub("<b>", chunk, count=1),
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
    "We have Berengaudus's {title} here: \"{units_dir}/{first_unit}\" with the files "
    "continuing up to \"{units_dir}/{last_unit}\". These are consecutive pieces cut, in order, "
    "from our fresh, PUBLIC-DOMAIN English translation of the whole work, \"{html_path}\" "
    "(consult it if you need surrounding context). The work is Berengaudus's verse-by-verse "
    "commentary on the book of {book} -- file everything under the book \"{book}\", in the "
    "\"{father}/\" folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (the translator's verse labels in it: {headings})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. Each "
    "piece repeats the work's title and translator's note at the top -- that note is "
    "background for you, not commentary; don't import it.\n\n"
    "VERSE KEYS. The <h2> headings are only chapter headings (\"Chapter 4\") and the headings "
    "of the visions' prefaces (\"On the Fourth Vision\"). Each lemma (the Scripture passage "
    "Berengaudus comments on) is a bold paragraph that opens with the translator's verse label, "
    "e.g. \"Revelation 1:1a\" or \"Revelation 1:4b-5a\", followed by the lemma in italics; the "
    "letters a, b, c ... mark parts of a verse, so \"1:1a\", \"1:1b\" and \"1:1c\" are all "
    "KJV 1:1. Berengaudus's comment follows in the paragraphs after it, up to the next bold "
    "lemma. Treat these labels as HINTS ONLY: they may be off. For each stretch of commentary, "
    "work out which KJV verse(s) it actually expounds -- compare the Scripture Berengaudus "
    "quotes and discusses with the KJV text, looking it up with `" + KJV_LOOKUP + "` -- and file "
    "it there, under KJV chapter/verse numbering.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. Berengaudus's "
    "lemmas are only where his text happens to divide -- one may quote a long passage (e.g. "
    "eight verses) and then work through it verse by verse -- so do NOT simply file a lemma's "
    "comment under the full range of its label. Break it up wherever the exposition moves from "
    "one verse to the next: e.g. if a stretch comments on 2:5, insert it in 2:5, not in 2:1-9. "
    "It's ok to use a range if necessary to avoid breaking up a coherent thought/piece "
    "(Berengaudus sometimes expounds several verses as one argument), just prefer smaller "
    "ranges/individual verses. When you split a lemma's comment, its pieces together must "
    "still contain the WHOLE of it, every word -- and you split ONLY by cutting the text into "
    "consecutive stretches: each block must be one continuous stretch of Berengaudus, in his "
    "order. Never cut up or move the lemma: when a lemma quotes several verses, that whole "
    "quotation stays, uncut, at the start of the first block from it. Do NOT duplicate the "
    "same stretch of commentary across several ADJACENT {book} verses -- put it ONCE, at its "
    "smallest accurate verse/range.\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the adjacent-{book}-verse "
    "duplication forbidden above). Berengaudus constantly quotes and expounds other "
    "Scripture. Whenever a stretch genuinely QUOTES AND EXPOUNDS a specific verse from another "
    "book -- a Psalm or other OT verse, a Gospel passage, or an Epistle passage -- you may ALSO "
    "file that portion under that verse in its own file (e.g. \"Isaiah 29_13\", \"Jude "
    "1_9\"), in addition to its {book} placement. File a cross-parallel only where Berengaudus "
    "genuinely expounds the passage, not for a passing mention or a bare one-line "
    "proof-text. Use KJV book/verse numbering for the target file.\n\n"
    "NON-VERSE SECTIONS. The text before a vision's first lemma, under its \"On the ... "
    "Vision\" heading, is that vision's preface, and \"The Author's Admonition\" closes the "
    "work; the notes above say what to do with each. Manuscript rubrics such as \"HERE BEGINS "
    "THE BOOK.\" are not Berengaudus's commentary; leave them out.\n\n"
    "THE TEXT. Copy Berengaudus's words VERBATIM -- nothing abridged, paraphrased, corrected, "
    "added or rearranged -- and keep the lemma where it stands in the source. Drop the html "
    "tags (bold and italics simply become plain text; don't turn them into quotation marks) "
    "and separate paragraphs with a single blank line. Leave out the <h2> headings and the "
    "translator's verse labels (\"Revelation 1:1a\"): a block starts with the lemma's own "
    "words (\"The Apocalypse of Jesus Christ, which God gave to him.\"). Don't add headings, "
    "verse numbers or notes of your own. Don't write a python script to do this; process the "
    "file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- the whole work sits behind one page).\n\n"
    "EXISTING BLOCKS. The old import of this work (an earlier machine translation, same "
    "source_url) has ALREADY been deleted, so you are only ADDING: if a verse file exists, "
    "append your [[commentary]] after its existing blocks; otherwise create it. Blocks from "
    "other works must be left exactly as they are."
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

    log_dir = os.path.join(WORK_DIR, f"berengaudus_{args.work.lower()}_import_logs")
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
