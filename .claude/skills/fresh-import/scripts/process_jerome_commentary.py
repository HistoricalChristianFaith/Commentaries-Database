#!/usr/bin/env python3
"""Import one of Jerome's commentaries (in our fresh, public-domain translation) into the
Commentaries-Database, one piece at a time, by driving a headless ``claude`` agent.

Written for the run of "fresh Jerome" import issues (Commentaries-Database #32-#38:
Philemon, Galatians, Titus, Isaiah, Obadiah, Ezekiel, Haggai) and follows the same flow as
process_ambrosiaster_romans.py and the other importers. Each of those works lives in the
Writings-Database as ONE html file laid out the same way:

    Writings-Database/Jerome/Commentary on <Book>.html

    <h1>..</h1><i>translator's note</i>   (the preamble)
    <h2>Prologue</h2>                     (non-verse: a dedicatory / historical preface)
    <h2>Book One</h2>                     (non-verse, multi-book works: a book preface)
    <h2>1:1</h2>                          (a verse section: Jerome's lemma in <i>..</i>,
    <h2>1:3-4</h2>                         then his exposition)
    <h2>1:14-2:1</h2>
    ...

A whole work is too big for one conversation (Isaiah is 2 MB), so the run goes:

  1. SPLIT. The html is cut on its <h2> sections into pieces, written as standalone html
     files (each repeating the preamble) under ``../work/jerome_<work>_units/``:
       * one piece per CHAPTER of the commented book (by the chapter in Jerome's heading);
       * a chapter over SPLIT_CHARS (30k) of html is cut into near-equal parts at <h2>
         boundaries -- never mid-section (a single oversized section stands alone);
       * non-verse sections (Prologue, Book N) stay in document order, in the piece of the
         verse section that follows them.
     The cut points are only that: Jerome's headings follow his Latin Bible's numbering and
     are HINTS. The agent decides which KJV verse(s) each stretch of commentary belongs to.
  2. IMPORT. For each piece, TWO prompts against the SAME claude conversation:
       * PROMPT 1 -- extract the commentary from this piece into the verse .toml files;
       * PROMPT 2 -- "Double check, was this fully imported properly?" (``--resume``).
  3. CLEAN UP. After every piece succeeded, the units folder is deleted. (On an abort it is
     kept for inspection; every run re-splits from scratch, so resuming is unaffected.)

After a full (or resumed-to-the-end) run, a deterministic CHECK runs against the ORIGINAL
html (also available alone via ``--check``): every <Book> file parses as TOML and has a
valid filename, every block of this work has the right source_title and no
old-translation residue ("(Verse 4.)" style prefixes), every block is one exact, continuous
stretch of the source (nothing cut up or rearranged), the stale old-translation files are
gone, and the opening and closing words of every paragraph appear in some block of this
work.

Old imports of these works (the earlier machine translation) share the same source_url and
must be removed BEFORE running this, e.g.:

    python3 delete_commentaries.py Jerome "<source_url>"

    python3 process_jerome_commentary.py Haggai --dry-run          # pieces + first prompt
    python3 process_jerome_commentary.py Haggai --split-only       # write units, keep them
    python3 process_jerome_commentary.py Haggai                    # import, clean up, check
    python3 process_jerome_commentary.py Haggai Part002_Ch02.html  # ONE piece (testing)
    python3 process_jerome_commentary.py Haggai --start-after Part001_Ch01.html
    python3 process_jerome_commentary.py Haggai --check            # check only
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

FATHER = "Jerome"

# A chapter with more html than this is cut into near-equal parts at <h2> boundaries.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "Haggai": {
        "html": "Jerome/Commentary on Haggai.html",
        "book": "Haggai",
        "source_title": "Commentary on Haggai",
        # Numbering quirks to spell out for the agent (the translator's note in each
        # piece's preamble also states this one).
        "notes": (
            "Jerome's headings follow the Vulgate, which in Haggai chapter 2 runs one verse "
            "AHEAD of the KJV: Vulgate 2:1 is KJV 1:15, and Vulgate 2:n (n >= 2) is KJV "
            "2:(n-1) -- so e.g. his heading \"1:14-2:1\" is KJV 1:14-15 and \"2:21-24\" is "
            "KJV 2:20-23. Chapter 1 is unaffected."
        ),
        # Known old-translation residue to assert gone after the run.
        "stale_files": ["Haggai 1_17-18"],
    },
    "Philemon": {
        "html": "Jerome/Commentary on Philemon.html",
        "book": "Philemon",
        "source_title": "Commentary on Philemon",
        # Philemon has one chapter and Jerome's headings already use KJV verse numbers.
        "notes": (
            "Philemon has a single chapter, so every file is \"Philemon 1_<verse>\". The "
            "translator's note mentions footnotes; they have been removed from these pieces "
            "and are not to be imported."
        ),
    },
    "Titus": {
        "html": "Jerome/Commentary on Titus.html",
        "book": "Titus",
        "source_title": "Commentary on Titus",
        "notes": (
            "Jerome's Titus headings use the same chapter/verse numbers as the KJV. The "
            "translator's note mentions footnotes; they have been removed from these pieces "
            "and are not to be imported."
        ),
    },
    "Galatians": {
        "html": "Jerome/Commentary on Galatians.html",
        "book": "Galatians",
        "source_title": "Commentary on Galatians",
        "notes": (
            "Jerome's Galatians headings use the same chapter/verse numbers as the KJV. Some "
            "mark half-verses (e.g. \"1:15-16a\", \"5:10b\"); our filenames never carry a/b, "
            "so file such a stretch under the whole verse number. The translator's note "
            "mentions footnotes; they have been removed from these pieces and are not to be "
            "imported."
        ),
    },
    "Obadiah": {
        "html": "Jerome/Commentary on Obadiah.html",
        "book": "Obadiah",
        "source_title": "Commentary on Obadiah",
        "notes": (
            "Obadiah has a single chapter, so every file is \"Obadiah 1_<verse>\", and "
            "Jerome's headings already use KJV verse numbers. Two headings mark half-verses "
            "(\"1:12-13a\", \"1:13b-14\"); our filenames never carry a/b, so file such a "
            "stretch under the whole verse number. Each lemma gives Obadiah first in "
            "Jerome's own version from the Hebrew and then, after \"LXX:\", in his Latin of "
            "the Septuagint: BOTH versions together are the lemma and stay together, uncut, "
            "at the start of the section's first block (the lemma usually runs inline in "
            "one long paragraph, sometimes after a phrase like \"There follows in the "
            "prophet Obadiah:\"). Jerome typically expounds a lemma twice -- first according "
            "to the history (following the Hebrew), then spiritually (often following the "
            "LXX) -- and each pass may cover the whole lemma range. Split by verse only "
            "where the text really moves verse by verse; don't chop it into tiny "
            "back-and-forth fragments -- use a range when a pass treats the verses as one "
            "argument."
        ),
    },
    "Isaiah": {
        "html": "Jerome/Commentary on Isaiah.html",
        "book": "Isaiah",
        "source_title": "Commentary on Isaiah",
        "notes": (
            "Isaiah's chapters and verses are numbered as in the KJV, but these <h2> headings "
            "are the modern editors' references, not Jerome's, and about one in fifteen is off "
            "by a verse or two (e.g. the lemmas headed \"30:20\" to \"30:24\" are KJV 30:19-23, "
            "\"19:25-26\" is KJV 19:24-25, \"2:19\" is KJV 2:20, \"63:18-19\" begins at 63:17): "
            "always identify the verses from the lemma's wording against the KJV. Heading "
            "forms: \"1:27, 29\" means verses 27 through 29; \"ff.\" or \"f.\" means the lemma "
            "runs on past that verse, so find where it ends.\n\n"
            "Each lemma gives Isaiah first in Jerome's own version from the Hebrew and then, "
            "after \"LXX:\", in his Latin of the Septuagint: BOTH versions together are the "
            "lemma and stay together, uncut, at the start of the section's first block. Keep "
            "everything in the text verbatim, including the Origenian signs (÷ ※ ⁚), "
            "Vallarsi's glosses in square brackets, and the editors' Scripture references in "
            "parentheses such as \"(Matt 7:7)\". In those references the Psalms carry the "
            "Latin number with the Hebrew/KJV number in brackets: \"Ps 143 [144]:1\" is KJV "
            "Psalm 144, so use the bracketed number for the psalm. The verse number, though, "
            "may follow the Latin count, which numbers a psalm's title as a verse (e.g. "
            "\"Ps 67 [68]:27\" quotes KJV 68:26): always fix a Psalm cross-reference's verse "
            "by matching the wording against the KJV.\n\n"
            "Jerome often expounds a lemma twice -- first according to the history (following "
            "the Hebrew), then spiritually (often following the LXX) -- and each pass may "
            "cover the whole lemma range. Split by verse only where the text really moves "
            "verse by verse; don't chop it into tiny back-and-forth fragments -- use a range "
            "when a pass treats the verses as one argument. We are interested in the "
            "commentary, not the lemma: file every block under the verse(s) its COMMENTARY "
            "addresses. So when a lemma quotes several verses but the exposition that "
            "follows it in the first block addresses only the first of them, file that first "
            "block (lemma included, uncut) under that verse alone -- e.g. a lemma quoting "
            "9:14-21 followed by comment on 9:14 goes in \"Isaiah 9_14\", not "
            "\"Isaiah 9_14-21\". The lemma's span never widens a block's range.\n\n"
            "Chapters 13-23 are expounded TWICE in this work: Book Five is Jerome's earlier, "
            "purely historical commentary on the ten \"visions\" (13:1-23:18), and Books Six "
            "and Seven then go over 13:1-23:18 again spiritually. So in Books Six and Seven "
            "the Isaiah 13-23 files will already hold \"Commentary on Isaiah\" blocks "
            "imported earlier in this same run from Book Five (and any piece may find blocks "
            "from the piece before it). Those are NOT old imports or duplicates: leave them "
            "exactly as they are and append yours after them.\n\n"
            "One section is cut by a piece boundary: the section headed \"13:18ff.\" holds "
            "only the start of a lemma (the Hebrew of 13:19-22a), already filed as a "
            "lemma-only block in \"Isaiah 13_19-22\". The section headed \"14:1\" does NOT "
            "begin at 14:1: its opening (\"Its time is near to come, and its days will not "
            "be prolonged. LXX: And Babylon ...\") finishes that lemma, gives its LXX, and "
            "then comments on 13:19-22. File that opening stretch, up to where Jerome "
            "reaches chapter 14, as a new block appended to \"Isaiah 13_19-22\" (it will be "
            "merged with the lemma start afterwards); only then continue with 14:1.\n\n"
            "\"Isaiah 1_1\" already holds a block of Jerome's separate \"Prologue to Isaiah\" "
            "(from his Biblical Prefaces, a different work): leave it first, and append this "
            "work's Prologue after it, followed by the 1:1 commentary.\n\n"
            "BOOK PREFACES -- these decisions are already made; follow them rather than "
            "judging for yourself. The \"Book One\" heading has no text. Book Three (on the "
            "vision of the Lord, the Seraphim and the coal) -> its own block under "
            "\"Isaiah 6_1-7\". Book Fifteen (the Apostles follow the Hebrew; \"the present "
            "passage ... differs in words\") -> its own block under \"Isaiah 54_1\", before "
            "the 54:1 commentary. Book Sixteen (the sources of the catena in Romans 3:13-18) "
            "-> its own block under \"Romans 3_13-18\". Book Eighteen (against the "
            "millenarians' literal reading of the promises) -> its own block under "
            "\"Isaiah 65_17-25\". Every other preface (Books Two, Four to Fourteen, "
            "Seventeen) is dedicatory or autobiographical: skip it, and say so."
        ),
    },
    "Ezekiel": {
        "html": "Jerome/Commentary on Ezekiel.html",
        "book": "Ezekiel",
        "source_title": "Commentary on Ezekiel",
        "notes": (
            "Ezekiel's chapters and verses are numbered as in the KJV (the chapter 20/21 "
            "boundary too: \"20:45-49\" is KJV 20:45-49 and \"21:1-5\" is KJV 21:1-5), but "
            "these <h2> headings are the modern editors' references, and a few are off: "
            "\"1:27-2:1a\" is KJV 1:27-28 (its lemma ends \"This is the vision of the likeness "
            "of the glory of the Lord\", KJV 1:28); \"2:1b\" (\"And I saw, and I fell upon my "
            "face, and I heard the voice of one speaking\") is the end of KJV 1:28, not 2:1; "
            "\"2:1c\" is KJV 2:1; \"2:9b-3:1a\" is KJV 2:9-10 (it has no 3:1 text); \"3:1b\" is "
            "KJV 3:1; \"11:2b-12\" begins at KJV 11:1 (\"twenty-five men at the entrance of "
            "the gate\"), so it covers 11:1-12. Always identify the verses from the lemma's "
            "wording against the KJV. About 140 headings mark part-verses with a/b/c "
            "(\"4:9a\", \"18:31b\", \"40:5c\", \"12:3b-5\"); our filenames never carry a/b/c, "
            "so file such a stretch under the whole verse number(s). When a verse is split "
            "over two sections (\"7:12a\", \"7:12b\", ...), each section still gets its own "
            "block(s), and both go in the same verse file, one after the other. A range "
            "crossing chapters is written like \"Ezekiel 1_27-2_1\".\n\n"
            "THE LEMMA. Each section opens with Jerome's version of Ezekiel from the Hebrew, "
            "in italics. In about 130 sections it is followed by a parenthesis giving the "
            "Septuagint, in quotation marks: (LXX: \"...\"); that parenthesis sometimes runs on "
            "with Jerome's remarks on the text and its signs (\"And what follows: ÷ And "
            "brightness in it ⁚, is to be marked beforehand with an obelus.)\") -- all of it, "
            "to its closing parenthesis, belongs to the lemma. Other lemmas give the LXX "
            "readings inline as alternatives: \"a desert (or destruction and solitude)\". "
            "Either way, the WHOLE lemma (Hebrew version plus the LXX parenthesis) stays "
            "together, uncut, at the start of the section's first block, and every section's "
            "first block starts exactly at the section start: never join the end of one "
            "section and the next section's lemma in one block, even when both go in the same "
            "verse file -- append them as two blocks. One section, \"18:31b\", opens with its "
            "lemma inside Jerome's paraphrase in single quotes ('And make for yourselves a new "
            "heart and a new spirit, so that ...'): start its block at that opening quote "
            "mark. Most sections are one long paragraph, so you will cut inside paragraphs: "
            "cut between sentences.\n\n"
            "Keep everything in the text verbatim, including the Origenian signs (÷ ※ ⁚), the "
            "Greek, the Hebrew in Jerome's Latin transliteration with its English gloss in "
            "square brackets (\"ἀναγωγὴν [anagogy, the higher sense]\"), the quotation marks "
            "of the LXX lemmas, the single quotation marks Jerome uses for paraphrase, and the "
            "dashes. Psalms carry the Latin number with the Hebrew/KJV number in parentheses: "
            "\"Psalm 18 (19)\" is KJV Psalm 19, so use the number in parentheses. Verse "
            "numbers may follow the Latin count, which numbers a psalm's title as a verse: "
            "always fix a Psalm cross-reference's verse by matching the wording against the "
            "KJV.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, "
            "file that first block (lemma included, uncut) under that verse alone -- e.g. if "
            "the lemma headed \"21:8-17\" were followed by comment on 21:8-9 alone, that first "
            "block would go in \"Ezekiel 21_8-9\", not \"Ezekiel 21_8-17\". The lemma's span "
            "never widens a block's range. From chapter 13 on, Jerome usually sets out a "
            "long passage and then expounds it, often twice -- first according to the history, "
            "then spiritually -- and each pass may cover the whole lemma range. Split by "
            "verse only where the text really moves verse by verse; don't chop it into tiny "
            "back-and-forth fragments -- use a range when a pass treats the verses as one "
            "argument.\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may "
            "find \"Commentary on Ezekiel\" blocks in the files you write to (e.g. the first "
            "half of a verse, filed by the piece before yours). Those are NOT old imports or "
            "duplicates: leave them exactly as they are and append yours after them.\n\n"
            "\"Ezekiel 1_1\" already holds a block from Jerome's Commentary on Daniel and one "
            "of Jerome's separate \"Prologue to Ezekiel\" (from his Biblical Prefaces, a "
            "different work): leave both first, and append this work's Prologue after them, "
            "as its own block, followed by the 1:1 commentary (section \"1:1a\").\n\n"
            "BOOK PREFACES -- these decisions are already made; follow them rather than "
            "judging for yourself. The \"Book One\" heading has no text. Book Eleven (the "
            "prophecy against Gog and Magog; \"This Gog is the Goth\") -> its own block, the "
            "whole preface, under \"Ezekiel 38_2\". Every other preface (Books Two to Ten, "
            "Twelve to Fourteen) is dedicatory or autobiographical: skip it whole, and say "
            "so.\n\n"
            "CLOSING NOTE. The section headed \"39:17-29\" ends with Jerome's note closing "
            "Book Eleven, from \"Thus far we have spoken on Ezekiel the prophet\" to \"than "
            "to say too little.\": leave that out; the section's commentary ends just before "
            "it. Short transitional sentences elsewhere (\"We have touched briefly on the "
            "obvious things, so that we may linger over the more obscure.\") are kept."
        ),
    },
    "Joel": {
        "html": "Jerome/Commentary on Joel.html",
        "book": "Joel",
        "source_title": "Commentary on Joel",
        "notes": (
            "Joel is numbered as in the KJV, in three chapters: these headings are Jerome's own "
            "division into lemmata and follow the Vulgate/KJV chapters, not the Hebrew Bible's "
            "four. So \"2:28-32\" (\"I will pour out my spirit upon all flesh\") is KJV 2:28-32, "
            "and \"3:1-3\" (\"For behold, in those days and at that time\") is KJV 3:1-3. Still "
            "identify the verses from the wording against the KJV.\n\n"
            "THE LEMMA. Each section opens with Joel in Jerome's own version from the Hebrew, in "
            "italics, and then, after \"LXX:\", in his Latin of the Septuagint: BOTH versions "
            "together are the lemma and stay together, uncut, at the start of the section's "
            "first block, and every section's first block starts exactly at the section start: "
            "never join the end of one section and the next section's lemma in one block, even "
            "when both go in the same verse file -- append them as two blocks. (The section "
            "\"1:13-14\" ends \"cry, he says, to the Lord in your hearts and say:\", leading into "
            "the lemma of \"1:15\": that sentence stays with 1:13-14, and \"1:15\" starts its own "
            "block.) Three lemmas are irregular. \"1:1\" has no LXX (Jerome notes the one "
            "difference, \"Bathuel for Phatuel\", in his comment). In \"1:4\" the LXX is just "
            "\"LXX: likewise.\". In \"3:4-6\" the LXX is interrupted by a gloss and then goes on: "
            "\"... or do you keep anger in your heart against me? — for this is what "
            "μνησικακείτε means in Greek —. Swiftly and quickly I will return your retribution "
            "upon your heads ...\" -- all of it, through \"that you might cast them out of their "
            "borders.\", is the lemma. Two sections hold a second lemma in a new paragraph: in "
            "\"2:28-32\" the opening lemma ends with KJV 2:32a (\"everyone who calls upon the name "
            "of the Lord shall be saved\"), and the second paragraph sets out 2:32b with its own "
            "LXX (\"For in mount Zion and in Jerusalem there shall be salvation, as the Lord has "
            "said; and in the remnant whom the Lord shall call. LXX: ...\"): start a new block "
            "there, with that sub-lemma and its LXX whole at its start. In \"3:18\" the lemma has "
            "only 3:18a, and the second paragraph opens with 3:18b (\"And a fountain will go "
            "forth from the house of the Lord and will water the torrent of thorns.\"), so the "
            "whole section belongs to 3:18. Most sections are one long paragraph, so you will "
            "cut inside paragraphs: cut between sentences.\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"τροπικῶς (figuratively)\", \"ψυλλέα (a "
            "Psyllian, a snake-charmer)\"), the Hebrew words in Jerome's own transliteration "
            "(\"saddai\", \"esphoch\", \"amonim\"), the dashes, and the punctuation as printed "
            "(\"prince of your virginity?.\", \"as Vergil says: ..., and a hundred altars "
            "glow\"). Jerome's text has no quotation marks -- the Scripture he quotes is in "
            "italics, which simply become plain text; don't add any. Psalms carry the Latin "
            "(LXX) number with the Hebrew/KJV number in parentheses: the one numbered "
            "reference, \"the fiftieth (51st) psalm\", is KJV Psalm 51 (its words \"Deal kindly, "
            "O Lord, in your good will with Zion, that the walls of Jerusalem may be built\" are "
            "KJV 51:18). Jerome quotes many other psalms without a number (\"as the psalmist "
            "says\"): fix any Psalm cross-reference by matching the wording against the KJV.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, "
            "file that first block (lemma included, uncut) under that verse alone -- e.g. if "
            "the lemma headed \"1:9-12\" were followed by comment on 1:9 alone, that first block "
            "would go in \"Joel 1_9\", not \"Joel 1_9-12\". The lemma's span never widens a "
            "block's range. (The section \"1:1\" does comment on 1:1 itself -- the names Phatuel "
            "and Joel, and the times of the prophecy -- so it goes in \"Joel 1_1\".) Jerome "
            "usually expounds a lemma twice -- first according to the history (the locusts as "
            "the Chaldeans and the other enemies of Judah), then spiritually (\"Let us pass to "
            "the spiritual understanding\", \"according to tropology\", \"According to "
            "ἀναγωγὴν (anagogy)\") -- and each pass may cover the whole lemma range. Split by "
            "verse only where the text really moves verse by verse; don't chop it into tiny "
            "back-and-forth fragments -- use a range when a pass treats the verses as one "
            "argument. (In \"2:1-11\" Jerome says \"I did not wish to divide a pericope joined "
            "and coherent in itself\": that is why he set out eleven verses as one lemma; judge "
            "each pass by how it actually moves through the verses.)\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Joel\" blocks in the files you write to (e.g. a block from the "
            "piece before yours under the same verse). Those are NOT old imports or duplicates: "
            "leave them exactly as they are and append yours after them. Blocks from Jerome's "
            "other works already in \"Joel 1_4\", \"Joel 1_14\", \"Joel 2_15\" and \"Joel 3_18\" "
            "stay first, untouched.\n\n"
            "\"Joel 1_1\" does not exist yet (the old import has been removed): create it with "
            "this work's Prologue as its first block -- the WHOLE Prologue, from \"The order of "
            "the twelve prophets\" to \"but our will.\", its closing request to Pammachius "
            "included -- followed by the 1:1 commentary as a second block.\n\n"
            "There is no closing note: the work ends in commentary on 3:21 (\"the Lord loves the "
            "gates of Zion above all the tents of Jacob.\"), so import \"3:20-21\" to its end."
        ),
    },
    "Malachi": {
        "html": "Jerome/Commentary on Malachi.html",
        "book": "Malachi",
        "source_title": "Commentary on Malachi",
        "notes": (
            "Malachi is numbered as in the KJV, in four chapters: these headings follow the "
            "Vulgate/KJV chapters, not the Hebrew Bible's three (so \"4:1-3\" is KJV 4:1-3, not "
            "Hebrew 3:19-21), and \"1:14-2:2\" crosses chapters (a range crossing chapters is "
            "written like \"Malachi 1_14-2_2\"). Still identify the verses from the wording "
            "against the KJV: in Jerome's version 3:8 reads \"Will a man fix God, since you fix "
            "me?\" (KJV \"Will a man rob God?\").\n\n"
            "THE LEMMA. Each section opens with Malachi in Jerome's own version from the "
            "Hebrew, in italics, and then, after \"LXX:\", in his Latin of the Septuagint: BOTH "
            "versions together are the lemma and stay together, uncut, at the start of the "
            "section's first block. In \"4:4\" the LXX is just \"LXX: likewise.\". In \"1:1\" the "
            "second paragraph opens with an LXX-only addition and its own comment (\"LXX: Set it "
            "upon your hearts. This is not found in the Hebrew\"): start a new block there, "
            "also in \"Malachi 1_1\". Most sections are one long paragraph, so you will cut "
            "inside paragraphs: cut between sentences.\n\n"
            "LEMMAS THAT BEGIN BEFORE THEIR HEADING. Six sections END with a short paragraph of "
            "italic Scripture on its own, with no LXX and no comment. That paragraph is NOT the "
            "end of its own section: it is the Hebrew version of the OPENING of the NEXT "
            "section's lemma (the next section's LXX starts with the same words, and the "
            "commentary that follows takes them up). So do not import it at the end of its own "
            "section: it is the start of the next section's first block, followed by a blank "
            "line and then that section's lemma (Hebrew and LXX), whole and uncut. The six are: "
            "end of \"1:6-7\": \"To you, O priests, who despise my name, and you have said: In "
            "what have we despised your name?\" (KJV 1:6b; it opens the lemma of \"1:7\"); end of "
            "\"1:9-10\": \"I have no pleasure in you, says the Lord of hosts, and I will not "
            "accept a gift from your hand.\" (KJV 1:10b; it opens \"1:11-13\"); end of \"3:1\": "
            "\"Behold, he comes, says the Lord of hosts.\" (the end of KJV 3:1; it opens "
            "\"3:2-6\"); end of \"3:2-6\": \"And you, sons of Jacob, have not been consumed.\" (KJV "
            "3:6b; it opens \"3:7\"); end of \"3:7\": \"Return to me, and I will return to you, "
            "says the Lord of hosts. And you have said: In what shall we return?\" (KJV 3:7b; it "
            "opens \"3:8-12\"); end of \"3:16\": \"And the Lord attended and heard, and a book of "
            "remembrance was written before him for those who fear the Lord, and think upon his "
            "name.\" (KJV 3:16b; it opens \"3:17-18\"). Two of these fall at the edge of a piece: "
            "the piece ending with \"1:6-7\" and the piece ending with \"3:7\" must leave that "
            "final paragraph out (say so), and the piece starting with \"1:7\" or with \"3:8-12\" "
            "must start its first block with it, copied exactly from the full source html, "
            "where it stands just before that heading. Otherwise every section's first block "
            "starts exactly at the section start, and the sections are never joined: the end "
            "of one section's commentary and the next section's lemma are always two blocks, "
            "even in the same verse file. File such a first block, like any other, by the "
            "verse(s) its commentary addresses -- that may include the opening half-verse "
            "(e.g. the comment under \"1:7\" begins \"To you, then, O priests, who despise my "
            "name, is this word directed\", which is 1:6b).\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"ἀνθρωποπάθως (in human fashion)\", "
            "\"μετωνυμικῶς (by metonymy)\", \"ἠλειμμένον (Anointed One)\"), the Hebrew words in "
            "Jerome's own transliteration (\"massa\", \"chabod\", \"phares\", \"borith\", "
            "\"haiecba\", \"aggoi\", \"sgolla\"), the dashes, the double quotation marks of the "
            "Prologue and the single ones elsewhere (\"the LXX translated 'if he "
            "supplants'\"), and the punctuation as printed, odd or not: "
            "\"Fire for shall burn before him\", \"The natural for man does not receive the "
            "things that are of the spirit\", and \"or of your testament, ; and no other made "
            "her\" (where an italic run ends before a semicolon). Italics simply become plain "
            "text; don't add quotation marks. Psalms carry the Latin (LXX) number with the "
            "Hebrew/KJV number in parentheses: \"Psalm 72 (73)\" is KJV Psalm 73, \"Psalm 88 "
            "(89)\" is KJV Psalm 89, \"Psalm 102 (103)\" is KJV Psalm 103, \"Psalm 81 (82)\" is "
            "KJV Psalm 82. Jerome quotes many other psalms without a number: fix any Psalm "
            "cross-reference by matching the wording against the KJV.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, "
            "file that first block (lemma included, uncut) under that verse alone -- e.g. if "
            "the lemma headed \"2:5-7\" were followed by comment on 2:5 alone, that first "
            "block would go in \"Malachi 2_5\", not \"Malachi 2_5-7\". The lemma's span never "
            "widens a block's range. Jerome usually expounds a lemma twice -- first according "
            "to the history (the priests and people returned from Babylon under Ezra, whom "
            "the Hebrews take Malachi to be), then spiritually (\"Now let us come to the "
            "spiritual understanding\", \"according to tropology\", \"according to ἀναγωγὴν "
            "(anagogy)\") -- and each pass may cover the whole lemma range. Split by verse only "
            "where the text really moves verse by verse (in \"2:13-16\" he says \"fitting brief "
            "statements to the individual verses\"); don't chop it into tiny back-and-forth "
            "fragments -- use a range when a pass treats the verses as one argument.\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Malachi\" blocks in the files you write to (e.g. a block from the "
            "piece before yours under the same verse). Those are NOT old imports or duplicates: "
            "leave them exactly as they are and append yours after them. Blocks from Jerome's "
            "other works already in \"Malachi 1_6\" (Letter 52), \"Malachi 2_11\" (Against "
            "Jovinianus) and \"Malachi 4_2\" (a homily on Easter Sunday) stay first, "
            "untouched.\n\n"
            "\"Malachi 1_1\" does not exist yet (the old import has been removed): create it "
            "with this work's Prologue as its first block -- the WHOLE Prologue, from \"We wish "
            "to interpret Malachi, the last of the twelve prophets\" to \"not so much of an "
            "interpretation as of the bare points of an interpretation.\", its words to "
            "Minervius and Alexander included -- followed by the 1:1 commentary (and then the "
            "block starting \"LXX: Set it upon your hearts.\").\n\n"
            "There is no closing note: the work ends in commentary on 4:5-6 (\"understanding "
            "John in Elijah.\"), so import \"4:5-6\" to its end."
        ),
    },
    "Nahum": {
        "html": "Jerome/Commentary on Nahum.html",
        "book": "Nahum",
        "source_title": "Commentary on Nahum",
        "notes": (
            "Nahum is numbered as in the KJV, in three chapters: these headings follow the "
            "Vulgate/KJV chapters, not the Hebrew Bible's (so \"1:15\", \"Behold upon the "
            "mountains the feet of him who brings good tidings\", is KJV 1:15, not Hebrew 2:1, "
            "and \"2:1-2\" is KJV 2:1-2). Every heading matches the KJV, but still identify the "
            "verses from the wording against the KJV. There is no \"1:1\" section: the "
            "Prologue itself expounds 1:1 (see below), and the first verse section is "
            "\"1:2\".\n\n"
            "THE LEMMA. Each section opens with Nahum in Jerome's own version from the Hebrew, "
            "in italics, and then, in most sections, after \"LXX:\", in his Latin of the "
            "Septuagint: BOTH versions together are the lemma and stay together, uncut, at "
            "the start of the section's first block, and every section's first block starts "
            "exactly at the section start: never join the end of one section and the next "
            "section's lemma in one block, even when both go in the same verse file -- append "
            "them as two blocks. Several lemmas are irregular. \"1:2\", \"1:3\", \"1:4\", "
            "\"1:15\", \"2:1-2\", \"2:11-12\" and \"3:7\" have no LXX right after the Hebrew; in "
            "\"1:14\" the LXX runs on into KJV 1:15a (\"for they are swift; behold upon the "
            "mountains the feet of one who brings good news and announces peace.\"), and "
            "Jerome explains: \"I have set down more from the Seventy translators for this "
            "reason, that the second περικοπὴ (pericope) could not be separated from the "
            "first.\" -- that whole LXX is still the lemma of \"1:14\". In \"3:18-19\" the LXX "
            "opens \"Woe to them.\": that too is part of the lemma.\n\n"
            "SUB-LEMMAS. In \"1:2\", \"1:3\", \"1:4\" and \"1:6\" the lemma gives only the first "
            "half of the verse, and the second paragraph opens with the second half (in "
            "\"1:2\", \"1:4\" and \"1:6\" with its own LXX: \"The Lord avenging, and having fury\", "
            "\"Bashan has grown weak, and Carmel, and the flower of Lebanon has languished.\", "
            "\"His indignation has been poured out like fire, and the rocks have been "
            "dissolved by him.\"; in \"1:3\" without one: \"The Lord, in storm and whirlwind are "
            "his ways, and clouds are the dust of his feet.\"). Each of these sections "
            "comments on its one verse throughout, so it belongs in that verse's file "
            "(\"Nahum 1_2\", \"Nahum 1_3\", \"Nahum 1_4\", \"Nahum 1_6\"); keep it as one block "
            "-- do not split it at the paragraph break. In \"2:1-2\" the second paragraph opens "
            "with the LXX of the lemma (\"LXX: Watch the way, hold the loin, be strengthened "
            "in strength exceedingly\") and goes on to expound it: if you cut there, that "
            "paragraph starts its own block with that LXX whole at its start. In \"3:13-17\" "
            "the LXX of the lemma stops at 3:16a (\"you have multiplied your tradings like the "
            "stars of heaven.\"); after the Hebrew exposition Jerome says \"Now, because the "
            "LXX seem to have the beginning of a sense of their own, I will set down their "
            "testimony and follow the order of the explanation I have begun.\", and the "
            "second paragraph opens with the LXX of 3:16b-17 (\"LXX: The cankerworm rushed in "
            "and flew out; your commingled one leapt out like the attelabus\"): start a new "
            "block at that \"LXX:\", with that sub-lemma whole at its start, filed by the "
            "verse(s) its comment addresses. In \"1:15\" Jerome postpones the LXX (\"For a "
            "little while I shall put off the LXX translators\") and gives it later inside "
            "the paragraph (\"LXX: Celebrate, O Judah, your feasts, pay your vows\"); in \"3:7\" "
            "it comes inside the comment too (\"The Seventy, moreover:\"). Most sections are "
            "one long paragraph, so you will cut inside paragraphs: cut between sentences.\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"καὶ ἀθῳῶν οὐκ ἀθῳώσει (and clearing he will "
            "not clear)\", \"Μεταφορικῶς (metaphorically)\", \"ὦ σύμμικτε (O mixed one)\"), the "
            "Greek left unglossed (\"συμμίκτους\", \"ἁρμόσαι χορδὴν\"), the Hebrew words in "
            "Jerome's own transliteration (\"massa\", \"basupha\", \"iaccum\", \"macoma\", \"chi "
            "calloth\", \"pherec malea\"), the dashes, the double quotation marks the text "
            "has in a few places (in \"1:8\", \"1:14\" and \"3:18-19\"), and the punctuation as "
            "printed. Italics simply become plain "
            "text; don't add quotation marks. Psalms carry the Latin (LXX) number with the "
            "Hebrew/KJV number in parentheses: \"the forty-eighth (49th) psalm\" is KJV Psalm "
            "49, \"the sixty-seventh (68th) psalm\" (\"Ascending on high, he led captivity "
            "captive\") is KJV 68:18, \"the seventy-sixth (77th) psalm\" (\"The voice of your "
            "thunder in the wheel\") is KJV 77:18. Jerome quotes many other psalms without a "
            "number: fix any Psalm cross-reference by matching the wording against the KJV.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, "
            "file that first block (lemma included, uncut) under that verse alone -- e.g. if "
            "the lemma headed \"3:8-12\" were followed by comment on 3:8 alone, that first "
            "block would go in \"Nahum 3_8\", not \"Nahum 3_8-12\". The lemma's span never "
            "widens a block's range. (In \"1:14\", likewise, the LXX's 1:15a in the lemma does "
            "not make the first block 1:14-15; but where Jerome's comment really takes up the "
            "\"swift\" feet upon the mountains of 1:15a, that stretch may be \"Nahum 1_14-15\".) "
            "Jerome usually expounds a lemma twice -- first according to the history (the "
            "fall of Nineveh to the Chaldeans, Sennacherib), then spiritually, often "
            "following the LXX (\"according to tropology\", \"Now let us come to the Seventy "
            "translators.\", Nineveh as the world and the heretics) -- and each pass may cover "
            "the whole lemma range. Split by verse only where the text really moves verse by "
            "verse; don't chop it into tiny back-and-forth fragments -- use a range when a "
            "pass treats the verses as one argument.\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Nahum\" blocks in the files you write to (e.g. a block from the "
            "piece before yours under the same verse). Those are NOT old imports or "
            "duplicates: leave them exactly as they are and append yours after them. The "
            "block from Jerome's Against the Pelagians already in \"Nahum 1_3\" stays first, "
            "untouched.\n\n"
            "\"Nahum 1_1\" does not exist yet (the old import has been removed): create it "
            "with this work's WHOLE Prologue as its only block, from \"According to the Seventy "
            "translators, in the order of the twelve prophets\" to \"where the Lord is to be "
            "the avenger against the true Assyrians.\", its words to Paula and Eustochium "
            "included. It quotes and expounds 1:1 (\"The taking up of Nineveh. The book of the "
            "vision of Nahum the Elkoshite.\"), so it is also this work's 1:1 commentary; don't "
            "split it.\n\n"
            "There is no closing note: the work ends in commentary on 3:19 (\"he rushes in "
            "indeed, but cannot enter.\"), so import \"3:18-19\" to its end."
        ),
    },
    "Habakkuk": {
        "html": "Jerome/Commentary on Habakkuk.html",
        "book": "Habakkuk",
        "source_title": "Commentary on Habakkuk",
        "notes": (
            "Habakkuk is numbered as in the KJV, in three chapters, and every heading matches "
            "the KJV, but still identify the verses from the wording against the KJV. Some "
            "headings mark half-verses (\"1:2-3a\", \"1:3b-4\", \"3:3a\", \"3:3b-4\"); our "
            "filenames never carry a/b, so file such a stretch under the whole verse number (a "
            "verse split over two sections gets a block from each, one after the other, in the "
            "same file). There is no \"1:1\" section: the Prologue itself expounds 1:1 (see "
            "below), and the first verse section is \"1:2-3a\".\n\n"
            "THE LEMMA. Each section opens with Habakkuk in Jerome's own version from the "
            "Hebrew, in italics, and then, after \"LXX:\", in his Latin of the Septuagint: BOTH "
            "versions together are the lemma and stay together, uncut, at the start of the "
            "section's first block, and every section's first block starts exactly at the "
            "section start: never join the end of one section and the next section's lemma in "
            "one block, even when both go in the same verse file -- append them as two blocks. "
            "\"Always.\" (Hebrew) and \"Diapsalma.\" (LXX) at the end of a lemma are the selah, "
            "and part of the lemma. Several lemmas are irregular. In \"1:3b-4\" and \"3:3b-4\" "
            "the first paragraph holds only the Hebrew of the first half-verse (\"And judgment "
            "has come about, and contradiction is the stronger.\"; \"His glory covered the "
            "heavens, and the earth is full of his praise.\"), and the second paragraph goes on "
            "with the Hebrew of the next verse and then the LXX of both (\"LXX: Against me "
            "judgment has come about\"; \"LXX: His power covered the heavens\"): both "
            "paragraphs, through the end of that LXX, are the lemma, and the section's first "
            "block starts with the first paragraph. In \"3:10-13\" and \"3:14-16\" the opening "
            "lemma has the Hebrew only, and Jerome expounds the Hebrew first (\"We have set "
            "down our edition alone, so that, following it, that is, following the Hebrew, we "
            "may weave together the sequence of the passage, and afterwards discuss the LXX "
            "clause by clause, section by section.\"; \"And now we discuss only the Hebrew, so "
            "that we may discuss the edition of the Seventy separately\"); then EVERY later "
            "paragraph of those two sections opens with an LXX sub-lemma (\"LXX: They will see "
            "you, and they will grieve\", \"LXX: You will scatter the waters of the way.\", ... "
            "\"LXX: You raised up bonds up to the neck, to the end.\"; \"LXX: You divided in "
            "amazement the heads of the mighty.\", ... \"LXX: I shall rest in the day of "
            "tribulation, that I may go up to the people of my sojourning.\"): start a new block "
            "at each such \"LXX:\", with its sub-lemma whole at its start, filed by the verse(s) "
            "its comment addresses (the Hebrew exposition before them is split by verse like "
            "any other stretch). In \"3:8-9\" the second paragraph opens with the sub-lemma of "
            "KJV 3:9b (\"You will split the rivers of the earth. LXX: The earth will be split "
            "by rivers.\"): start a new block there, with that sub-lemma whole at its start. In "
            "\"3:2\" the second, third and fourth paragraphs open with sub-lemmas that are all "
            "still 3:2 (\"In the midst of the years you will make it known.\", the LXX-only "
            "\"When the time comes, you will be shown, when my soul is troubled.\", and \"When "
            "you are angry, you will remember mercy\"): the whole section comments on 3:2, so "
            "keep it as one block in \"Habakkuk 3_2\" -- do not split it at the paragraph "
            "breaks. In \"2:19-20\" the second and third paragraphs are two lines of Vergil "
            "(\"A spirit within sustains them, and mind, poured through all the limbs,\" / "
            "\"moves the whole mass, and mingles itself with the great body.\") inside Jerome's "
            "sentence: keep them as their own paragraphs, in the same block as the sentence "
            "that introduces them; never start or end a block on them. Most sections are one "
            "long paragraph, so you will cut inside paragraphs: cut between sentences.\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"πολιτείᾳ (commonwealth)\", \"ἀγωνοθέτῃ (the "
            "president of the games)\"), the Greek glossed with \"that is\" (\"περίληψις, that "
            "is, embracing\", \"Καὶ ἀφιὼν ἀκρίτως τὸν θυμὸν ἑαυτοῦ, that is: And sending forth "
            "his fury without judgment\"), the Hebrew words in Jerome's own transliteration "
            "(\"massa\", \"alluoth\", \"rua\", \"sam\", \"dabar\", \"deber\"), the translator's "
            "parenthesized book names (\"the first book of Kingdoms (1 Samuel)\", \"the fourth "
            "book of Kingdoms (2 Kings)\"), the dashes (\"— so to speak —\", \"since you once "
            "wished it —.\"), the double quotation marks the text has in a few places (\"with a "
            "turbid overturning\", \"every spirit\", the quotations of Vergil and Tullius), the "
            "single ones ('your'), and the punctuation as printed. Italics simply become plain "
            "text; don't add quotation marks. Psalms carry the Latin (LXX) number with the "
            "Hebrew/KJV number in parentheses: \"Psalm 72 (73)\" is KJV Psalm 73, \"Psalm 17 "
            "(18)\" (\"Who made my feet perfect like those of harts\") is KJV 18:33, \"Psalm 18 "
            "(19)\" (\"Their sound has gone out into all the earth\") is KJV 19:4, \"Psalm 28 "
            "(29)\" is KJV Psalm 29. Jerome quotes many other psalms without a number: fix any "
            "Psalm cross-reference by matching the wording against the KJV.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, "
            "file that first block (lemma included, uncut) under that verse alone -- e.g. if "
            "the lemma headed \"1:6-11\" were followed by comment on 1:6 alone, that first block "
            "would go in \"Habakkuk 1_6\", not \"Habakkuk 1_6-11\". The lemma's span never "
            "widens a block's range. Jerome usually expounds a lemma twice -- first according "
            "to the history (Nebuchadnezzar and the Chaldeans, the captivity of Judah), then "
            "spiritually, often following the LXX (\"according to tropology\", \"according to "
            "anagogy\", the devil, the Antichrist and the heretics) -- and each pass may cover "
            "the whole lemma range. Split by verse only where the text really moves verse by "
            "verse; don't chop it into tiny back-and-forth fragments -- use a range when a pass "
            "treats the verses as one argument.\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Habakkuk\" blocks in the files you write to (e.g. a block from the "
            "piece before yours under the same verse). Those are NOT old imports or "
            "duplicates: leave them exactly as they are and append yours after them. Blocks "
            "from Jerome's other works already in \"Habakkuk 2_2-3\" and \"Habakkuk 3_8\" "
            "(Homilies on the Psalms), \"Habakkuk 2_4\" (Commentary on Galatians), "
            "\"Habakkuk 3_1\" and \"Habakkuk 3_16\" (Against the Pelagians) and \"Habakkuk "
            "3_4\" (a homily on the Epiphany) stay first, untouched.\n\n"
            "\"Habakkuk 1_1\" does not exist yet (the old import has been removed): create it "
            "with this work's WHOLE Prologue as its only block, from \"First, Chromatius, most "
            "learned of bishops\" to \"Habakkuk writes as a prophet the things that he knows are "
            "to come.\", its words to Chromatius included. It expounds 1:1 (the prophet's name, "
            "\"embrace\"; massa, the burden or weight; the vision of the prophet), so it is also "
            "this work's 1:1 commentary; don't split it, and don't file any of it under 1:2-4, "
            "which it quotes in passing.\n\n"
            "BOOK PREFACES -- these decisions are already made; follow them rather than judging "
            "for yourself. The \"Book One\" heading has no text. The \"Book Two\" preface (\"We "
            "are writing a second book on Habakkuk, my Chromatius\" to \"in the number of the "
            "Lord's resurrection.\") is dedicatory: skip it whole, and say so.\n\n"
            "There is no closing note: Book One ends in commentary on 2:20 (\"and of my own "
            "accord I take it up again.\"), and the work ends in commentary on 3:19 (\"and "
            "surpass the other singers with my song.\"), so import \"2:19-20\" and \"3:18-19\" "
            "to their ends."
        ),
    },
    "Zephaniah": {
        "html": "Jerome/Commentary on Zephaniah.html",
        "book": "Zephaniah",
        "source_title": "Commentary on Zephaniah",
        "notes": (
        "Zephaniah is numbered as in the KJV, in three chapters, and every heading matches "
        "the KJV, but still identify the verses from the wording against the KJV. Verse 1:14 is "
        "split over two sections (\"1:13-14a\" ends with KJV 1:14a, \"Close is the great day of the "
        "Lord; it is close, and exceedingly swift.\"; \"1:14b-16\" opens with KJV 1:14b, \"The voice "
        "of the day of the Lord is bitter; there the strong man will be afflicted.\"); our filenames "
        "never carry a/b, so file such a stretch under the whole verse number (each section still "
        "gets its own block(s), and both may go in the same file, one after the other).\n\n"
        "THE LEMMA. Each section opens with Zephaniah in Jerome's own version from the Hebrew, in "
        "italics, and then, after \"LXX:\", in his Latin of the Septuagint: BOTH versions together "
        "are the lemma and stay together, uncut, at the start of the section's first block, and "
        "every section's first block starts exactly at the section start: never join the end of "
        "one section and the next section's lemma in one block, even when both go in the same "
        "verse file -- append them as two blocks. Three lemmas are irregular. In \"1:1\" the LXX "
        "is just \"LXX likewise.\" (plain text, no colon), which is part of the lemma. In "
        "\"1:14b-16\" the first paragraph holds only the Hebrew of KJV 1:14b, and the second "
        "paragraph goes on with the Hebrew of 1:15-16 (\"That day is a day of wrath\") and then "
        "the LXX of all three verses (\"LXX: The voice of the day of the Lord is bitter and "
        "harsh\"): both paragraphs, through the end of that LXX (\"against the fortified cities "
        "and against the lofty corners.\"), are the lemma, and the section's first block starts "
        "with the first paragraph. In \"1:11\" the second paragraph opens with a sub-lemma for "
        "KJV 1:11b (\"All who were wrapped in silver have perished. LXX: All who are lifted up by "
        "silver have perished.\"): the whole section comments on 1:11, so keep it as one block in "
        "\"Zephaniah 1_11\" -- do not split it at the paragraph break. Every other section is one "
        "long paragraph, so you will cut inside paragraphs: cut between sentences.\n\n"
        "Keep everything in the text verbatim, including the Greek words and the English glosses "
        "in parentheses after them (\"ἐπώνυμον (named after it)\", \"εὶς τὸν ὅλμον (into the "
        "mortar)\", \"ἀναστάσει (the Resurrection: the Church of the Anastasis in Jerusalem)\", "
        "\"θαμβευταὶ (the astonished)\"), the Greek glossed with \"that is\" (\"τεμενίτας, that is, "
        "temple-keepers or fanatics\", \"πνευματοφόροι, that is, bearing the spirit\"), the Greek "
        "left unglossed (\"διασυρτικῶς\"), the Hebrew words in Jerome's own transliteration "
        "(\"machtes\", \"acchumarim\", \"goi chorethim\", \"mamasac\", \"hareb\", \"phoezim\", "
        "\"barura\", \"badura\"), the two Latin words kept beside their English (\"Triflers "
        "(nugas)\", \"the water-snake (excetra)\"), the dashes (\"— which was turned by the LXX "
        "into 'king' —,\"), the single quotation marks Jerome's text uses for names and renderings "
        "('watchtower', 'my Ethiopian', 'the elevation of the Lord'), and the punctuation as "
        "printed. The text has no double quotation marks: italics simply become plain text; don't "
        "add quotation marks. Psalms carry the Latin (LXX) number with the Hebrew/KJV number in "
        "parentheses: \"Psalm 50 (51)\" (\"Do not take your Holy Spirit from me\") is KJV 51:11, "
        "\"Psalm 26 (27)\" (\"The Lord is my illumination and my savior; whom shall I fear?\") is "
        "KJV 27:1, \"Psalm 43 (44)\" (\"But now you have rejected and confounded us\") is KJV 44:9. "
        "Jerome quotes many other psalms without a number: fix any Psalm cross-reference by "
        "matching the wording against the KJV. Cross-references go only to OTHER books: when "
        "Jerome quotes another verse of Zephaniah (e.g. \"1:1\" and \"2:12-15\" quoting 3:10 on the "
        "Ethiopians), do not file that stretch under that verse as well -- no text is ever "
        "duplicated within Zephaniah.\n\n"
        "We are interested in the commentary, not the lemma: file every block under the verse(s) "
        "its COMMENTARY addresses. So when a lemma quotes several verses but the exposition that "
        "follows it in the first block addresses only the first of them, file that first block "
        "(lemma included, uncut) under that verse alone -- e.g. if the lemma headed \"2:3-4\" were "
        "followed by comment on 2:3 alone, that first block would go in \"Zephaniah 2_3\", not "
        "\"Zephaniah 2_3-4\". The lemma's span never widens a block's range. (The section \"1:1\" "
        "does comment on 1:1 itself -- the prophet's name and lineage, and the days of Josiah -- "
        "so it goes in \"Zephaniah 1_1\".) Jerome usually expounds a lemma twice -- first "
        "according to the history (the Chaldean invasion under Nebuchadnezzar, the Philistines, "
        "Moab, Ammon, the Ethiopians and Assyria), then spiritually, often following the LXX "
        "(\"These things according to tropology.\", \"let us see the anagogy as well\", \"Thus far "
        "according to the Hebrew. Now let us return to the LXX translators\") -- and each pass may "
        "cover the whole lemma range. Split by verse only where the text really moves verse by "
        "verse; don't chop it into tiny back-and-forth fragments -- use a range when a pass treats "
        "the verses as one argument. One pass reaches back a verse: \"3:1-7\" ends by deferring "
        "the LXX of 3:7b (\"Prepare yourself, rise up at dawn, all their foliage has been "
        "scattered, since it differs much from the Hebrew, and according to the LXX seems rather "
        "to agree with what follows, we will expound in what follows.\"), and in \"3:8-9\" the "
        "spiritual pass opens on it (\"But we, who follow not the letter that kills but the "
        "spirit that gives life, nor Jewish fables, hear from the Lord: Prepare yourself, rise at "
        "dawn: all their clusters have been scattered\") before returning to 3:8 (\"Wait for me on "
        "the day of my resurrection for a testimony\"): file that stretch by what it addresses "
        "(\"Zephaniah 3_7\", or \"Zephaniah 3_7-8\" if it can't be separated from the 3:8 comment).\n\n"
        "Earlier pieces of THIS run have already imported their sections, so you may find "
        "\"Commentary on Zephaniah\" blocks in the files you write to (e.g. a block from the piece "
        "before yours under the same verse). Those are NOT old imports or duplicates: leave them "
        "exactly as they are and append yours after them. Blocks from Jerome's other works already "
        "in \"Zephaniah 1_12\" (Homilies on Mark 82) and \"Zephaniah 2_11\" (Homily 24, on Psalm "
        "96) stay first, untouched.\n\n"
        "\"Zephaniah 1_1\" does not exist yet (the old import has been removed): create it with "
        "this work's Prologue as its first block -- the WHOLE Prologue, from \"Before I take up "
        "Zephaniah, who is ninth in the order of the twelve prophets\" to \"so that men might blush "
        "not to seek the one whom the frailer sex had already found.\", its words to Paula and "
        "Eustochium included -- followed by the 1:1 commentary as a second block (section \"1:1\", "
        "through \"Now let us see what the prophecy itself also contains.\").\n\n"
        "There is no closing note: the work ends in commentary on 3:19-20 (\"These things "
        "according to the Seventy. But since the Hebrew, except for the beginning, about which we "
        "spoke at the end of the preceding chapter, does not differ much from their translation, "
        "I do not think it needs exposition.\"), so import \"3:19-20\" to its end."
        ),
    },
    "Zechariah": {
        "html": "Jerome/Commentary on Zechariah.html",
        "book": "Zechariah",
        "source_title": "Commentary on Zechariah",
        # The translator's ⟦[Text supplied from Migne ..]  .. ⟧ markers around the stretch of
        # 7:7-14 taken from PL 25: the user wants it imported as plain text (#46).
        "strip": [r"⟦\[[^\]<]*\]\s*", "⟧"],
        "notes": (
            "Zechariah is numbered as in the KJV, in fourteen chapters: these headings follow the "
            "Vulgate/KJV verse numbering, not the Hebrew Bible's (which counts KJV 1:18-21 as 2:1-4 "
            "and KJV 2:1-13 as 2:5-17), so \"1:18-21\" (the four horns and the four smiths) is KJV "
            "1:18-21 and \"2:1-2\" (the man with the measuring line) is KJV 2:1-2. Every heading "
            "matches the KJV, but still identify the verses from the wording against the KJV.\n\n"
            "THE LEMMA. Each section opens with Zechariah in Jerome's own version from the Hebrew, "
            "in italics, and then, after \"LXX:\", in his Latin of the Septuagint: BOTH versions "
            "together are the lemma and stay together, uncut, at the start of the section's first "
            "block, and every section's first block starts exactly at the section start (but see "
            "LEMMAS THAT BEGIN BEFORE THEIR HEADING below): never join the end of one section and "
            "the next section's lemma in one block, even when both go in the same verse file -- "
            "append them as two blocks. Several lemmas are irregular. In \"8:7-8\" the LXX is just "
            "\"LXX: likewise.\". \"8:9\" has no LXX: the comment opens with it (\"The Seventy "
            "translated \"the Lord Almighty\" for \"the Lord of hosts\", the rest likewise.\"). In "
            "\"8:18-19\" and \"12:5\" the LXX is interrupted by a dashed gloss and then goes on "
            "(\"for good festivals; — for in Hebrew this is said tobim, that is, ἀγαθάς —, and "
            "rejoice, and love truth and peace\"; \"And the tribunes — that is, οἱ χιλίαρχοι —, of "
            "Judah shall say in their hearts\"), and in \"3:8-9\" and \"9:5-8\" by a Greek word "
            "glossed with \"that is\" (\"for the men τερατοσκόποι, that is, of portents, are "
            "beholders\"; \"and they shall be as a χιλίαρχος, that is, tribune, in Judah\"): in all "
            "four the whole LXX, to its end, is the lemma.\n\n"
            "THE TEXT SUPPLIED FROM MIGNE. The translator's note speaks of a stretch within 7:7-14 "
            "supplied from Migne between ⟦ ⟧ with a bracketed note: those brackets and notes have "
            "been removed from these pieces (the full source html still has them; don't import "
            "them). That stretch is ordinary text of the work: import it like any other.\n\n"
            "LEMMAS THAT BEGIN BEFORE THEIR HEADING. Seven sections END with a short paragraph of "
            "italic Scripture on its own, with no LXX and no comment. That paragraph is NOT the end "
            "of its own section: it is the Hebrew version of the OPENING of the NEXT section's lemma "
            "(the next section's LXX starts with the same words, and the commentary that follows "
            "takes them up). So do not import it at the end of its own section: it is the start of "
            "the next section's first block, followed by a blank line and then that section's "
            "lemma (Hebrew and LXX), whole and uncut. The seven are: end of \"3:1-5\": \"And the "
            "angel of the Lord was standing.\" (KJV 3:5b; it opens \"3:6-7\"); end of \"3:8-9\": "
            "\"Behold, I will engrave its carving, says the Lord of hosts, and I will take away the "
            "iniquity of that land in one day.\" (KJV 3:9b; it opens \"3:10\"); end of \"9:14-15\": "
            "\"And they shall devour and subdue with sling stones, and drinking they shall be made "
            "drunk as with wine, and they shall be filled like bowls, and like the horns of the "
            "altar.\" (KJV 9:15b; it opens \"9:16\"); end of \"10:3-5\": \"And the riders on horses "
            "shall be confounded.\" (KJV 10:5b; it opens \"10:6-7\"); end of \"11:6-7\": \"And I took "
            "for myself two staffs: one I called Beauty, and the other I called Cords; and I fed the "
            "flock.\" (KJV 11:7b; it opens \"11:8-9\"); end of \"14:3-4\": \"And the middle of the "
            "mountain shall be divided toward the north, and its middle toward the south.\" (KJV "
            "14:4b; it opens \"14:5\"); end of \"14:8-9\": \"On that day the Lord shall be one, and his "
            "name one.\" (KJV 14:9b; it opens \"14:10-11\"). Each pair is in the same piece. "
            "Otherwise every section's first block starts exactly at the section start. File such "
            "a first block, like any other, by the verse(s) its commentary addresses -- that may "
            "include the opening half-verse (e.g. the comment under \"3:10\" begins \"Above he had "
            "said: Behold the stone which I have given before Joshua, upon one stone are seven eyes. "
            "Now, consistently, he keeps the μεταφορὰν (metaphor) taken from the stone, and says: I "
            "will engrave its carving\", which is 3:9b).\n\n"
            "SUB-LEMMAS. Three sections have a second paragraph opening with a sub-lemma, Hebrew "
            "and LXX, followed by its own comment: in \"1:2-4\" KJV 1:4b (\"Thus says the Lord of "
            "hosts: Turn from your evil ways, and from your most wicked thoughts\"), in \"12:9-10\" "
            "KJV 12:10b (\"And they shall look upon me whom they pierced\"), and in \"14:20-21\" KJV "
            "14:21b (\"And all these shall come sacrificing, and taking from them\"): start a new "
            "block at each, with its sub-lemma (through its LXX) whole at its start, filed by the "
            "verse(s) its comment addresses. In \"1:18-21\" the second paragraph is a line of Vergil "
            "(\"Hence they fear and desire, grieve and rejoice.\") that ends Jerome's sentence on the "
            "four passions (\"of which the illustrious poet also gives indication:\"): keep it as its "
            "own paragraph, in the same block as the sentence that introduces it; never start a "
            "block with it. Most sections are one long paragraph, so you will cut inside "
            "paragraphs: cut between sentences.\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"προσεφώνησεν (dedicated)\", \"ἀνθρωποπάθως (in "
            "human fashion)\", \"ῥοῶνος (of the pomegranate grove)\"), the Greek glossed with \"that "
            "is\" (\"ἀνατολὴ, or ἀναφύη, or βλάστημα, that is, shoot\", \"ἐξεκέντησαν, that is, they "
            "pricked or they pierced\"), the Greek left unglossed (\"ἐπιδοξότης\", \"εὐπρέπεια\"), the "
            "Hebrew words in Jerome's own transliteration (\"tobim\", \"methnosasoth\", \"maphate "
            "phethee\", \"emsa li\", \"ataroth\", \"mesuloth\", \"ulo alehem eie\"), the Latin word kept "
            "beside its English (\"sword (framea)\"), the translator's \"(Iesus, the same name as "
            "Jesus)\", the dashes, the two pairs of double quotation marks in \"8:9\", the single "
            "quotation marks the text uses for words and renderings ('Almighty', 'day'), and the "
            "punctuation as printed. Italics simply become plain text; don't add quotation marks. "
            "Psalms carry the Latin (LXX) number with the Hebrew/KJV number in parentheses: \"Psalm "
            "109 (110)\" (\"The Lord said to my Lord: Sit at my right hand\") is KJV 110:1, \"Psalm 23 "
            "(24)\" (\"Lift up your gates, O princes\") is KJV 24:7, \"Psalm 44 (45)\" (\"Your arrows "
            "are sharp, most mighty\") is KJV 45:5, \"Psalm 21 (22)\" (\"Deliver my soul from the "
            "sword\") is KJV 22:20, \"Psalm 77 (78)\" (\"The sons of Ephraim, bending and shooting the "
            "bow\") is KJV 78:9. Jerome quotes many other psalms without a number: fix any Psalm "
            "cross-reference by matching the wording against the KJV. Cross-references go only to "
            "OTHER books: when Jerome quotes another verse of Zechariah, do not file that stretch "
            "under that verse as well -- no text is ever duplicated within Zechariah. Where Jerome "
            "discusses an evangelist's use of Zechariah (9:9 in the entry into Jerusalem, 12:10 in "
            "John, 13:7 in Matthew), only the stretch that genuinely expounds the Gospel passage may "
            "also go under that Gospel verse -- never the whole section.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, file "
            "that first block (lemma included, uncut) under that verse alone -- e.g. if the lemma "
            "headed \"6:9-15\" were followed by comment on 6:9-10 alone, that first block would go "
            "in \"Zechariah 6_9-10\", not \"Zechariah 6_9-15\". The lemma's span never widens a "
            "block's range. (The section \"1:1\" does comment on 1:1 itself -- the second year of "
            "Darius, the eighth month, Zechariah son of Berechiah son of Iddo -- so it goes in "
            "\"Zechariah 1_1\".) Jerome usually expounds a lemma twice -- first according to the "
            "history, often as the Hebrews explain it (Zerubbabel and Joshua son of Jehozadak, the "
            "building of the temple, the Maccabees and Antiochus), then spiritually (\"Before we come "
            "to the spiritual understanding, we must say succinctly and briefly how the Hebrews "
            "explain this passage.\", \"According to tropology\", \"According to allegory\", \"According "
            "to ἀναγωγὴν (anagogy)\", \"Let us pass to the spiritual understanding.\") -- and each pass "
            "may cover the whole lemma range. Split by verse only where the text really moves verse "
            "by verse; don't chop it into tiny back-and-forth fragments -- use a range when a pass "
            "treats the verses as one argument. (Long visions such as \"1:8-13\", \"4:2-7\" and "
            "\"6:1-8\" are often retold in one sweep and then expounded clause by clause; judge each "
            "pass by how it actually moves through the verses.)\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Zechariah\" blocks in the files you write to (e.g. a block from the "
            "piece before yours under the same verse). Those are NOT old imports or duplicates: "
            "leave them exactly as they are and append yours after them. Blocks from Jerome's other "
            "works already in \"Zechariah 1_8\" and \"Zechariah 1_12\" (Commentary on Daniel), "
            "\"Zechariah 1_9\", \"Zechariah 3_2\", \"Zechariah 3_3\", \"Zechariah 9_16\" and "
            "\"Zechariah 11_8\" (Homilies on the Psalms), \"Zechariah 1_18-19\" and \"Zechariah 6_1-5\" "
            "(Commentary on Joel), \"Zechariah 2_10-11\" (Commentary on Isaiah), \"Zechariah 8_5\" "
            "(Against Jovinianus) and \"Zechariah 9_9\" (Commentary on Zephaniah) stay first, "
            "untouched.\n\n"
            "\"Zechariah 1_1\" does not exist yet (the old import has been removed): create it with "
            "this work's Prologue as its first block -- the WHOLE Prologue, from \"Already at the very "
            "end of autumn our brother, your son the monk Sisinnius\" to \"we spread the sails of "
            "interpretation to the Holy Spirit.\", its words to Exsuperius included -- followed by "
            "the 1:1 commentary as a second block.\n\n"
            "BOOK PREFACES -- these decisions are already made; follow them rather than judging for "
            "yourself. The \"Book One\" heading has no text. The \"Book Two\" preface (\"We pass from "
            "obscure things to obscure things\" to \"but by the most abundant waters of the Gauls.\") "
            "and the \"Book Three\" preface (\"Brother Sisinnius is pressing me to send these things "
            "off unkempt and unpolished\" to \"with a frenzy of words.\") are dedicatory and "
            "autobiographical: skip each whole, and say so.\n\n"
            "There is no closing note: Book One ends in commentary on 6:8 (\"boasted had been handed "
            "over to himself.\"), Book Two in commentary on 10:12 (\"as Enoch walked, and pleased "
            "God, and was translated.\"), and the work in commentary on 14:21 (\"who, they assert, "
            "must be removed from the house of God.\"), so import \"6:1-8\", \"10:11-12\" and "
            "\"14:20-21\" to their ends."
        ),
    },
    "Matthew": {
        "html": "Jerome/Commentary on Matthew.html",
        "book": "Matthew",
        "source_title": "Commentary on Matthew",
        # The <h2> headings are chapters; inside them every paragraph opens with its lemma,
        # which is the unit the audit and import_checks.py check (as they do sections).
        "chapter_re": r"^Matthew (\d+)\b",
        "lemma_paragraphs": True,
        "notes": (
            "In this work, though, the <h2> headings are NOT labels of lemmas: they are only "
            "chapter headings (\"Matthew 5\"), or part-chapters where one of Jerome's four books "
            "begins inside a chapter (\"Matthew 11:2-30\", \"Matthew 16:1-12\" and \"Matthew 16:13-28\", "
            "\"Matthew 22:1-40\" and \"Matthew 22:41-46\"), and nothing in the text gives verse "
            "numbers. Inside each chapter, EVERY paragraph opens with its own lemma: a verse or part "
            "of a verse (sometimes several verses, sometimes ending \"and the rest.\"), in italics, "
            "followed by Jerome's comment. So identify the verse(s) of every lemma, and of the "
            "comment after it, from the wording against the KJV (look it up with `python3 .claude/skills/fresh-import/scripts/kjv_lookup.py \"Matthew 5:3\"`). Jerome's Gospel "
            "text is his own Latin, translated literally and not conformed to the KJV: e.g. \"Our "
            "supersubstantial bread give us today.\" is KJV 6:11, \"Do not be anxious about "
            "tomorrow.\" is KJV 6:34, and the genealogy has Latin name forms (\"And Judah begot Perez "
            "and Zerah of Tamar.\" is KJV 1:3, where the KJV has Judas, Phares, Zara, Thamar). His "
            "Bible's order also differs from the KJV's in places: in the beatitudes \"Blessed are "
            "the meek, for they shall possess the land.\" comes BEFORE \"Blessed are those who mourn, "
            "for they shall be comforted.\" -- the meek are KJV 5:5 and those who mourn KJV 5:4, so "
            "file each by its wording, not by its place. The Lord's Prayer ends with the lemma "
            "\"Amen.\" (KJV 6:13, which in his text has no doxology). Jerome passes over many verses "
            "without a lemma; that is fine. A range crossing chapters is written like \"Matthew "
            "26_75-27_1\".\n\n"
            "EVERY PARAGRAPH STARTS ITS OWN BLOCK. Each paragraph's lemma stays whole, uncut, at the "
            "start of that paragraph's first block, and a block never runs on from one paragraph "
            "into the next: even when consecutive paragraphs comment on the same verse (e.g. the "
            "three lemmas of 5:22), each is its own block, and they go in the same verse file one "
            "after the other. Some paragraphs end by leading into the next lemma (\"Then he was led "
            "in the desert by the Spirit. No doubt, by the Holy Spirit. For there follows:\" before "
            "\"To be tempted by the devil.\"; \"But as for what follows:\" before \"One iota or one apex "
            "shall not pass from the law until all things come to pass,\"), so that Jerome's "
            "sentence runs on into the next paragraph's lemma. That is the ONE exception: when "
            "such a lead-in paragraph and the paragraph it leads into go in the same verse file, "
            "join them in ONE block, the paragraph break kept as a blank line inside it (e.g. "
            "both of those examples: 4:1 and 5:18). If they belong to different verses, the "
            "lead-in stays at the end of its own paragraph's block and the next paragraph starts "
            "a new block. Most "
            "paragraphs are short and comment on one verse or one lemma, and are then one block. A "
            "long paragraph may be split further, between sentences, only where its comment really "
            "moves on to a later verse than its lemma; don't chop it into tiny back-and-forth "
            "fragments -- use a range when a stretch treats the verses as one argument (Jerome "
            "often gives the plain sense first and then the spiritual one, \"According to "
            "tropology\", over the same verses).\n\n"
            "We are interested in the commentary, not the lemma: file every block under the verse(s) "
            "its COMMENTARY addresses. So when a lemma quotes several verses but the comment after "
            "it addresses only the first of them, file that block (lemma included, uncut) under that "
            "verse alone -- e.g. if a lemma quoting 21:1-3 were followed by comment on 21:1 alone, "
            "that block would go in \"Matthew 21_1\", not \"Matthew 21_1-3\". The lemma's span never "
            "widens a block's range.\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"σύμβολον (symbol)\", \"Ἀπὸ κοινοῦ (from the shared "
            "clause)\", \"ἐκάκωσεν αὐτήν (she did her evil, i.e. ill-treated her)\"), the Greek glossed "
            "with \"that is\" (\"κενός, that is, empty or void\"), the Hebrew and Syriac words in "
            "Jerome's Latin letters (\"mammona\", \"salom lach\", \"phelmoni and helmoni\"), the "
            "translator's other parentheses (\"verse-by-verse (commatic)\"), the single quotation "
            "marks the text uses for words and renderings ('brainless'), the dashes, and the "
            "punctuation as printed. The text has no double quotation marks: italics simply become "
            "plain text; don't add quotation marks. Psalms carry the Latin (LXX) number with the "
            "Hebrew/KJV number in parentheses: \"Psalm 44 (45)\" (\"And press on, and proceed "
            "prosperously, and reign, for the sake of truth and meekness and justice.\") is KJV 45:4, "
            "\"Psalm 117 (118)\" (\"The stone which the builders rejected\") is KJV 118:22, \"Psalm 68 "
            "(69)\" (\"The zeal of your house has eaten me up\") is KJV 69:9. Jerome quotes many other "
            "psalms without a number: fix any Psalm cross-reference by matching the wording against "
            "the KJV.\n\n"
            "CROSS-REFERENCES. Where Jerome genuinely expounds an Old Testament text that Matthew "
            "quotes -- where it is found, how it reads in the Hebrew, what it means (e.g. the "
            "\"Nazarene\" of 2:23 and Isaiah, the Asaph title of Psalm 77 (78) at 13:35, the prophet "
            "of 27:9) -- that stretch may also be filed under the Old Testament verse. GOSPEL "
            "PARALLELS ARE WANTED TOO: wherever a block comments on a saying or event that Mark, "
            "Luke or John also tells (the same saying or the same episode, not just a similar "
            "theme), ALSO file that block, unchanged, under the parallel verse(s) of EACH of those "
            "Gospels, in its own file (e.g. a block on the beatitude of the poor in spirit also "
            "goes under \"Luke 6_20\"; one on the feeding of the five thousand also under the "
            "verses of Mark 6, Luke 9 and John 6 it parallels). Find the parallel verses by "
            "comparing the wording with the KJV, use the smallest range that matches what the "
            "block addresses, and skip a Gospel that has no real parallel. Where Jerome himself "
            "quotes another evangelist's own wording (e.g. to explain how the accounts differ), "
            "that stretch belongs under that verse as well. "
            "Cross-references go only to OTHER books: when Jerome quotes another verse of Matthew, "
            "do not file that stretch under that verse as well -- no text is ever duplicated within "
            "Matthew.\n\n"
            "Earlier pieces of THIS run have already imported their chapters, so you may find "
            "\"Commentary on Matthew\" blocks in the files you write to (e.g. a cross-reference, or "
            "a block from the piece before yours under the same verse). Those are NOT old imports or "
            "duplicates: leave them exactly as they are and append yours after them. Many Matthew "
            "files already hold blocks from other works, above all \"Catena Aurea by Aquinas\" "
            "excerpts (Aquinas quoting this same commentary, in an older translation), and also "
            "Jerome's letters, homilies and other commentaries: they stay first, untouched -- don't "
            "remove, merge or \"deduplicate\" them.\n\n"
            "THE PREFACE. The \"Preface\" (to Eusebius) is this work's Prologue. \"Matthew 1_1\" "
            "already holds a \"Catena Aurea by Aquinas\" block and one from Jerome's Lives of "
            "Illustrious Men: leave both first, and append this work's Preface after them, as its "
            "own block -- the WHOLE Preface, from \"That there were many who wrote gospels\" to "
            "\"that are later to be written for her.\", its words to Eusebius included -- followed by "
            "the 1:1 commentary (its first two paragraphs, \"The book of the generation of Jesus "
            "Christ.\" and \"The son of David, the son of Abraham.\", one block each). These "
            "decisions are already made; follow them rather than judging for yourself: the "
            "Preface's opening stretch, from \"That there were many who wrote gospels\" to \"the "
            "obedience of service.\", expounds Luke's \"Since indeed many have attempted to set in "
            "order a narrative\": ALSO file it as its own block under \"Luke 1_1\". Its stretch on the "
            "four living creatures, from \"That these four Gospels, then, were foretold long before\" "
            "to \"by living churchmen.\", expounds Ezekiel's four faces and the four living "
            "creatures of the Apocalypse: ALSO file that whole stretch, as its own block, under "
            "\"Ezekiel 1_10\" and under \"Revelation 4_7\". Nothing else of the Preface is "
            "cross-filed. The \"Book One\" to \"Book Four\" headings have no text.\n\n"
            "There is no closing note: Books One to Three end in commentary on 10:42, 16:12 and "
            "22:35-36, and the work ends in commentary on 28:20 (\"But he who promises his presence "
            "even to the consummation of the world is not ignorant of that day on which he knows he "
            "will be with the apostles.\"), so import every chapter to its end."
        ),
    },
    "Micah": {
        "html": "Jerome/Commentary on Micah.html",
        "book": "Micah",
        "source_title": "Commentary on Micah",
        "notes": (
            "Micah is numbered as in the KJV, in seven chapters: these headings follow the "
            "Vulgate/KJV verse numbering, not the Hebrew Bible's (which counts KJV 5:1 as 4:14 and "
            "KJV 5:2-15 as 5:1-14), so \"5:1\" (\"Now you shall be laid waste, daughter of the "
            "robber\") is KJV 5:1 and \"5:2\" (\"And you, Bethlehem Ephrathah\") is KJV 5:2. Every "
            "heading matches the KJV, but still identify the verses from the wording against the "
            "KJV. Three verses are split over two sections: \"5:5a\" and \"5:5b-6\" (KJV 5:5b, \"And "
            "we shall raise up against him seven shepherds, and eight principal men.\"), \"6:9a\" and "
            "\"6:9b-16\" (KJV 6:9b, \"Hear, O tribes, and who will approve it?\"), \"7:1-4a\" and "
            "\"7:4b-7\" (KJV 7:4b, \"The day of your watching, your visitation, comes; now shall be "
            "their devastation.\"). Our filenames never carry a/b, so file such a stretch under the "
            "whole verse number (each section still gets its own block(s), and both may go in the "
            "same file, one after the other).\n\n"
            "THE LEMMA. Each section opens with Micah in Jerome's own version from the Hebrew, in "
            "italics, and then, after \"LXX:\", in his Latin of the Septuagint: BOTH versions "
            "together are the lemma and stay together, uncut, at the start of the section's first "
            "block, and every section's first block starts exactly at the section start: never "
            "join the end of one section and the next section's lemma in one block, even when both "
            "go in the same verse file -- append them as two blocks. Four lemmas are irregular. In "
            "\"1:1\" the LXX is introduced by \"Or according to the Seventy:\" (\"Concerning the things "
            "which he saw concerning Samaria and Jerusalem.\"), and in \"6:1-2\" by \": LXX.\" (\"and "
            "with Israel: LXX. Hear what the Lord has spoken\"): in both the whole LXX, to its end, "
            "is part of the lemma. In \"6:9b-16\" and \"7:4b-7\" the first paragraph holds only the "
            "Hebrew of the opening half-verse (\"Hear, O tribes, and who will approve it?\"; \"The day "
            "of your watching, your visitation, comes; now shall be their devastation.\"), and the "
            "second paragraph goes on with the Hebrew of the following verses and then the LXX of "
            "the whole passage: both paragraphs, through the end of that LXX (\"and you shall "
            "receive the reproaches of the peoples.\"; \"My God will hearken to me.\"), are the lemma, "
            "and the section's first block starts with the first paragraph.\n\n"
            "LXX SUB-LEMMAS. In \"2:9-10\", \"2:11-13\" and \"3:1-4\" the first paragraph is the Hebrew "
            "lemma (with NO LXX after it) and Jerome's exposition according to the Hebrew; then "
            "each following paragraph opens with a piece of the LXX (\"LXX: The leaders of my people "
            "will be cast out of the houses of their delights\", \"LXX: Draw near to the eternal "
            "mountains.\", \"LXX: Arise and walk, for there is no rest for you here.\", \"LXX: Because "
            "of uncleanness you have been consumed with corruption.\", \"LXX: You have fled with no "
            "one pursuing.\" in \"2:9-10\"; six in \"2:11-13\", from \"LXX: The spirit has set a lie.\" "
            "to \"LXX: Before their face they divided and passed through the gate\"; two in \"3:1-4\", "
            "\"LXX: And he will say: Hear these things\" and \"LXX: Tearing away their skins from "
            "them\") followed by its own comment. Start a new block at each such paragraph, with "
            "its LXX sub-lemma whole at its start, filed by the KJV verse(s) its comment addresses "
            "-- match the LXX wording to the KJV verse it renders (e.g. \"You have fled with no one "
            "pursuing\" is the LXX's ending of 2:10, and Jerome's comment ties it to the "
            "uncleanness of 2:10). Several such blocks may go in the same file, one after another. "
            "The other sections with a second paragraph (\"2:1-5\", \"3:5-8\", \"5:5b-6\", \"7:4b-7\") "
            "simply continue the exposition there. Most sections are one long paragraph, so you "
            "will cut inside paragraphs: cut between sentences.\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"σώφρων (temperate)\", \"χοϊκοῖς (earthy)\", "
            "\"προσωποποιίαν (personification)\", \"ὁμώνυμος (of the same name)\", \"ἀποστροφὴ (a "
            "turning of address\"), the Greek glossed with \"that is\" (\"εὐθύνων, that is, reproving "
            "and rebuking\", \"σχῖνον, that is, the mastic\", \"κυλισμὸς, that is, rolling\") or with "
            "\"which we can render\" (\"ἐν παραξίφεσιν αὐτῶν, which we can render, with their "
            "daggers\"), the Greek left unglossed (\"μαρτυρία ἀντλήσεως αὐτῶν\", \"φάραγγες\"), whole "
            "Greek sentences (\"Ἔτι κληρονόμον ἄξω καί σοι κατοικία Μαρέσα\"), the Hebrew words in "
            "Jerome's own transliteration (\"ophel\", \"nesiche adam\", \"baphethee\", \"ethanim\", "
            "\"laed\"), the dashes, the single quotation marks the text uses for renderings ('strong "
            "foundations of the earth'), the double quotation marks in \"3:1-4\", \"7:4b-7\", "
            "\"7:14-17\" and \"7:18-20\" (\"any more\", \"forever\"), and the punctuation as printed. "
            "Italics simply become plain text; don't add quotation marks. Psalms carry the Latin "
            "(LXX) number with the Hebrew/KJV number in parentheses: \"Psalm 17 (18)\" (\"The pains "
            "of death surrounded me\") is KJV 18:4-5, \"Psalm 29 (30)\" (\"What profit is there in my "
            "blood\") is KJV 30:9. Jerome quotes many other psalms without a number: fix any Psalm "
            "cross-reference by matching the wording against the KJV. Cross-references go only to "
            "OTHER books: when Jerome quotes another verse of Micah, do not file that stretch under "
            "that verse as well -- no text is ever duplicated within Micah. Where Jerome discusses "
            "an evangelist's use of Micah (5:2 in Matthew's account of the Magi, 7:6 in the Lord's "
            "\"I came to divide a man against his father\"), only the stretch that genuinely "
            "expounds the Gospel passage may also go under that Gospel verse -- never the whole "
            "section.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, file "
            "that first block (lemma included, uncut) under that verse alone -- e.g. if the lemma "
            "headed \"1:3-5\" were followed by comment on 1:3 alone, that first block would go in "
            "\"Micah 1_3\", not \"Micah 1_3-5\". The lemma's span never widens a block's range. (The "
            "section \"1:1\" does comment on 1:1 itself -- the kings Jotham, Ahaz and Hezekiah, "
            "Samaria and Jerusalem -- so it goes in \"Micah 1_1\".) Jerome usually expounds a lemma "
            "twice -- first according to the history, often as the Hebrews explain it, then "
            "spiritually, often following the LXX (\"As far, therefore, as concerns the history\", "
            "\"But as far as concerns the mystical understandings\", \"let us first expound "
            "according to what has been handed down to us by the Hebrews\") -- and each pass may cover the whole lemma range. Split by "
            "verse only where the text really moves verse by verse; don't chop it into tiny "
            "back-and-forth fragments -- use a range when a pass treats the verses as one argument. "
            "(Long lemmas such as \"1:10-15\", \"4:1-7\", \"5:7-15\" and \"6:9b-16\" are often "
            "expounded clause by clause; judge each pass by how it actually moves through the "
            "verses.)\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Micah\" blocks in the files you write to (e.g. a block from the piece "
            "before yours under the same verse). Those are NOT old imports or duplicates: leave "
            "them exactly as they are and append yours after them. Blocks from Jerome's other works "
            "already in \"Micah 1_3-4\" and \"Micah 4_1-2\" (Commentary on Ezekiel), \"Micah 2_9-10\" "
            "(Homily 60, on Psalm 10), \"Micah 6_5\" (Commentary on Joel) and \"Micah 7_6\" "
            "(Commentary on Matthew) stay first, untouched.\n\n"
            "\"Micah 1_1\" does not exist yet (the old import has been removed): create it with this "
            "work's Prologue as its first block -- the WHOLE Prologue, from \"Micah, on whom I now "
            "desire to dictate commentaries\" to \"are given to children by their parents from the "
            "name of a virtue.\" (its passing quotations on humility are not cross-filed) -- "
            "followed by the 1:1 commentary as a second block.\n\n"
            "BOOK PREFACES -- these decisions are already made; follow them rather than judging for "
            "yourself. The \"Book One\" heading has no text. The \"Book Two\" preface (\"We are always "
            "answering the envious\" to \"with the prophetic ῥοπάλῳ (club).\") answers those who "
            "accuse Jerome of pillaging Origen and is autobiographical: skip it whole, and say "
            "so.\n\n"
            "There is no closing note to cut: Book One ends in commentary on 4:1-7 (\"but will "
            "reprove them as condemned.\"), and the work ends with Jerome's own prayer made from "
            "7:18-20 (\"I too will say at the end of the volume, sealing the labor of my little work "
            "with an invocation of the Lord: God, who is like you?\" to \"so that she may no longer "
            "build Egyptian cities out of mud and straw.\"), which is part of his commentary on "
            "7:18-20: import \"4:1-7\" and \"7:18-20\" to their ends."
        ),
    },
    "Hosea": {
        "html": "Jerome/Commentary on Hosea.html",
        "book": "Hosea",
        "source_title": "Commentary on Hosea",
        # A stray verse label left before the 7:5-7 lemma ("5-7. <i>The day of our king").
        "strip": [r"(?<=<h2>7:5-7</h2>\n)5-7\. "],
        "notes": (
            "These headings follow the verse numbering of English Bibles (the KJV), with the Latin "
            "(Vulgate) numbering added in parentheses where it differs: \"2:21-23 (Latin 2:21-24)\", "
            "\"13:16 (Latin 14:1)\", \"14:1-3 (Latin 14:2-4)\", \"14:4-8 (Latin 14:5-9)\" and \"14:9 "
            "(Latin 14:10)\". Always use the English/KJV number, never the Latin one (so \"13:16 "
            "(Latin 14:1)\", \"Let Samaria perish\", is KJV 13:16, in \"Hosea 13_16\"). Every heading "
            "matches the KJV, but still identify the verses from the wording against the KJV. Two "
            "lemmas open with the second half of the PREVIOUS KJV verse, as the Vulgate divides "
            "them: \"6:1-3\" opens with \"In their tribulation they will rise early to me\" (KJV 5:15b,"
            " \"in their affliction they will seek me early\"), and \"11:1-2\" opens with \"As the "
            "morning passes, the king of Israel has passed away\" (KJV 10:15b, \"in a morning shall "
            "the king of Israel utterly be cut off\"); in both, Jerome's exposition begins with that"
            " half-verse (in \"6:1-3\": \"Therefore God has handed Ephraim and Judah over to "
            "captivity\"; in \"11:1-2\": \"He sets out the same sense under different figures.\") before"
            " moving on, so file each stretch by the verse its comment addresses -- a block may "
            "start at 5:15 or 10:15, and a range that crosses the chapter is written \"Hosea "
            "5_15-6_1\" or \"Hosea 10_15-11_1\". Six verses are split over two sections: \"4:4-5a\" and "
            "\"4:5b-6\", \"4:13a\" and \"4:13b-14\", \"5:1-2a\" and \"5:2b-4\", \"7:13-14a\" and \"7:14b-16\", "
            "\"8:11-13a\" and \"8:13b-14\", \"10:13a\" and \"10:13b-15\". Our filenames never carry a/b, so"
            " file such a stretch under the whole verse number (each section still gets its own "
            "block(s), and both may go in the same file, one after the other). The section \"13:4\" "
            "is a short textual note on 13:4 alone (on the LXX's addition, marked with an obelus), "
            "ending \"Let us therefore pass on to the rest, joining the preceding section to what "
            "follows:\"; the next section, \"13:4-6\", gives 13:4 again with 13:5-6. They are two "
            "sections: each gets its own block(s), and \"13:4\" goes in \"Hosea 13_4\".\n\n"
            "THE LEMMA. Each section opens with Hosea in Jerome's own version from the Hebrew, in "
            "italics, and then, after \"LXX:\", in his Latin of the Septuagint (or \"LXX: likewise.\" "
            "when they agree): BOTH versions together are the lemma and stay together, uncut, at "
            "the start of the section's first block, and every section's first block starts exactly"
            " at the section start: never join the end of one section and the next section's lemma "
            "in one block, even when both go in the same verse file -- append them as two blocks. "
            "Irregular lemmas: In \"4:5b-6\", \"4:13b-14\", \"5:2b-4\", \"7:14b-16\", \"8:13b-14\", "
            "\"10:13b-15\" and \"13:4-6\" the first paragraph holds only the Hebrew of the opening "
            "half-verse (e.g. \"By night I have made your mother silent.\"; \"Because you have trusted"
            " in your ways, in the multitude of your mighty men,\"), and the second paragraph goes "
            "on with the Hebrew of the rest and then the LXX of the whole: both paragraphs, through"
            " the end of that LXX, are the lemma, and the section's first block starts with the "
            "first paragraph. In \"10:11\" the LXX is interrupted by Jerome's dashed remark (\"LXX: "
            "Ephraim is a heifer — or a cow; for what in Hebrew is called egla, that is, μόσχος "
            "(calf) and δάμαλις (heifer), signifies both —; Ephraim, then, is a heifer taught to "
            "love contention\"): the whole LXX, to \"Jacob will be strengthened for himself.\", is the"
            " lemma. In \"13:3\" the LXX is \"LXX: likewise; changing only this, which is at the end: "
            "and like vapor from locusts, or from tears\", and in \"13:4\" it is introduced by \"In "
            "place of which one reads in the LXX:\" and runs to \"And I brought you out of the land "
            "of Egypt.\" In \"8:8\" there is no LXX lemma; Jerome notes the difference at once (\"The "
            "Seventy translated \"useless\" for \"unclean\"; the rest likewise.\"). In the source html "
            "the \"7:5-7\" lemma is preceded by a stray verse label \"5-7.\"; it has been removed from "
            "your piece and is not to be imported.\n\n"
            "SUB-LEMMAS. In \"1:1\", \"1:2\", \"2:2-3\", \"2:14-15\", \"6:1-3\", \"6:8-9\", \"7:2-3\", \"9:15\" and"
            " \"13:14-15\" a later paragraph opens with a further lemma (the Hebrew in italics and, "
            "except in \"9:15\", its LXX) followed by its own comment. Where that sub-lemma moves on "
            "to a later verse or half-verse -- \"And I will make her like a wilderness\" (2:3b), \"And"
            " she will sing there according to the days of her youth\" (2:15b), \"His going forth is "
            "prepared like the dawn\" (6:3b), \"A partner of the priests who kill on the way\" (6:9b),"
            " \"In their wickedness they made the king glad\" (7:3), \"The Lord will bring a burning "
            "wind rising from the desert\" (13:15b) -- start a new block at that paragraph, with the"
            " sub-lemma (Hebrew and LXX) whole at its start, filed by the KJV verse(s) its comment "
            "addresses. Where it is the rest of the same verse -- \"In the days of Uzziah, Jotham, "
            "Ahaz, Hezekiah, kings of Judah\" (1:1), \"And the Lord said to Hosea: Go, take for "
            "yourself a wife of fornications\" (1:2), \"Because of the malice of their devices I will"
            " cast them out of my house\" (9:15b, whose first paragraph runs on into it: \"of whom he"
            " says in what follows:\") -- the paragraph continues the same block. The second "
            "paragraph of \"2:16-17\" has no lemma and simply continues the exposition. Most sections"
            " are one long paragraph, so you will cut inside paragraphs: cut between sentences.\n\n"
            "Keep everything in the text verbatim, including the Greek words and the English "
            "glosses in parentheses after them (\"παλάτας (cakes of pressed figs)\", \"ῥαβδομαντείαν "
            "(divination by rods)\", \"ἄπιν (Apis)\", \"μνεῦιν (Mnevis)\", \"ἀναγωγήν (anagogy)\", "
            "\"τυπικῶς (typologically)\"), the Greek glossed with \"that is\" (\"οὐκ ἠλεημένη, that is, "
            "without mercy\", \"ἱερατείαν, that is, priesthood\", \"ὑπακούσει, that is, 'will hear'\"), "
            "the Greek left unglossed (the translators' renderings in \"4:13b-14\": \"Aquila "
            "translated ἐνηλλαγμένων, Symmachus ἑταιρίδων, the Seventy τετελεσμένων, Theodotion "
            "κεχωρισμένων\"), whole Greek titles (\"Περὶ τοῦ πῶς ὠνομάσθη ἐν τῷ Ὠσηὲ Ἐφραΐμ\"), the "
            "Hebrew words in Jerome's own transliteration (\"cadesoth\", \"egla\", \"gaon\", \"recob\", "
            "\"Saon\", \"Issi\", \"Baali\", \"arbe\"), the Origenian obelus ÷ in \"8:13b-14\" and \"13:4\" (and"
            " the \":\" closing the obelized passage in \"13:4\"), the dashes, the single quotation "
            "marks the text uses for renderings ('effeminate', 'to oxen', 'chimney'), the double "
            "quotation marks in \"1:2\", \"2:16-17\", \"4:1-2\", \"4:15-16\", \"5:13\", \"5:14-15\", \"6:1-3\" "
            "and \"8:8\", and the punctuation as printed. Italics simply become plain text; don't add"
            " quotation marks. This work never cites a Psalm by number: when Jerome quotes a psalm "
            "(\"Unveil my eyes, and I will consider the wonders of your law\", \"As smoke fails, let "
            "them fail\"), identify any Psalm cross-reference by matching the wording against the "
            "KJV. Cross-references go only to OTHER books: when Jerome quotes another verse of "
            "Hosea, do not file that stretch under that verse as well -- no text is ever duplicated"
            " within Hosea. Where Jerome discusses an apostle's use of Hosea (11:1 \"Out of Egypt I "
            "called my son\" in Matthew's Gospel, which \"The emperor Julian\" slanders; 13:14 in the "
            "Apostle's \"Death is swallowed up in strife? Where, O death, is your strife? Where, O "
            "death, is your sting?\"), only the stretch that genuinely expounds the New Testament "
            "passage may also go under that verse -- never the whole section.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. So when a lemma quotes several verses but the "
            "exposition that follows it in the first block addresses only the first of them, file "
            "that first block (lemma included, uncut) under that verse alone -- e.g. if the lemma "
            "headed \"4:17-19\" were followed by comment on 4:17 alone, that first block would go in "
            "\"Hosea 4_17\", not \"Hosea 4_17-19\". The lemma's span never widens a block's range. "
            "Jerome often expounds a lemma twice -- first according to the history (the ten tribes,"
            " Samaria, Jeroboam, the Assyrian captivity), then spiritually, often of the heretics "
            "and the Church (\"according to the history and according to tropology\", \"According to "
            "the spiritual understanding\", \"Some, according to tropology, refer Ephraim and Judah "
            "to the heretics\") -- and each pass may cover the whole lemma range. Split by verse "
            "only where the text really moves verse by verse; don't chop it into tiny "
            "back-and-forth fragments -- use a range when a pass treats the verses as one argument."
            " (Long lemmas such as \"2:10-12\", \"4:7-9\", \"8:1-4\", \"12:2-6\" and \"14:4-8\" are often "
            "expounded clause by clause; judge each pass by how it actually moves through the "
            "verses.)\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on Hosea\" blocks in the files you write to (e.g. a block from the piece "
            "before yours under the same verse). Those are NOT old imports or duplicates: leave "
            "them exactly as they are and append yours after them. Blocks from Jerome's other works"
            " already in \"Hosea 1_2\" (Commentary on Ezekiel), \"Hosea 1_9\" (Homilies on the Psalms),"
            " \"Hosea 2_6-7\" (Commentary on Zephaniah, Commentary on Micah), \"Hosea 2_14-15\" and "
            "\"Hosea 13_9\" (Commentary on Isaiah), \"Hosea 3_2\" (Letter 123), \"Hosea 4_12\" (Homilies "
            "on Mark), \"Hosea 11_1\" (Commentary on Matthew) and \"Hosea 11_9\" (Against the "
            "Pelagians) stay first, untouched.\n\n"
            "\"Hosea 1_1\" does not exist yet (the old import has been removed): create it with this "
            "work's Prologue as its first block -- the WHOLE Prologue, from \"If in the explanations"
            " of all the prophets\" to \"we discuss what is written.\" (its quotations -- on Hosea's "
            "harlot wife, Tamar, Rahab, Jeremiah's loincloth -- and its account of Jerome's "
            "predecessors are not cross-filed) -- followed by the 1:1 commentary as a second "
            "block.\n\n"
            "BOOK PREFACES -- these decisions are already made; follow them rather than judging for"
            " yourself. The \"Book One\" heading has no text. The \"Book Two\" preface (\"He who sails "
            "often sometimes suffers a storm\" to \"but by the merit of his works.\") answers Jerome's"
            " detractors and is autobiographical: skip it whole, and say so (it stands at the end "
            "of the piece holding \"5:6-7\", just before the \"5:8-9\" section it precedes). The \"Book "
            "Three\" preface (\"I am not unaware, Pammachius, that I am hammering out\" to \"to the "
            "safest harbors.\") is dedicatory: skip it whole, and say so.\n\n"
            "There is no closing note to cut: Book One ends in commentary on 5:6-7 (\"Their lots "
            "will not profit them.\"), Book Two in commentary on 10:3-4 (\"those who had consolation "
            "may mourn.\"), and the work ends in commentary on 14:9 (\"Behold, this one is set for "
            "the fall and for the rising of many in Israel.\"): import \"5:6-7\", \"10:3-4\" and \"14:9 "
            "(Latin 14:10)\" to their ends."
        ),
    },
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file (path segments are
    double-encoded after the father folder, matching the existing source_urls)."""
    father, *rest = work["html"].split("/")
    inner = quote("/".join(rest), safe="")
    return (
        "https://historicalchristian.faith/by_father.php?file="
        f"{quote(father)}%2F{inner.replace('%', '%25')}"
    )


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"jerome_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
CHAPTER_RE = re.compile(r"^(\d+):\d")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn\d+" id="r\d+">\d+</a></sup>')
NOTES_SECTION_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">.*?</section>\s*', re.S)


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def load_work(work):
    """Return (preamble_html, sections). Each section keeps its raw html (heading
    included) plus the heading text and the chapter it belongs to (None if non-verse)."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Translator's footnotes (alternative Latin readings, corrected references) are
    # editorial apparatus, not Jerome: drop the inline markers and the notes section.
    text = FOOTNOTE_REF_RE.sub("", text)
    text = NOTES_SECTION_RE.sub("", text)
    # Other editorial marks a work asks to drop from its sections (not from the preamble).
    cut = text.find("<h2>")
    for pat in work.get("strip", []):
        text = text[:cut] + re.sub(pat, "", text[cut:])
    parts = H2_RE.split(text)
    preamble = parts[0]
    sections = []
    # Matthew's headings are whole chapters ("Matthew 5", "Matthew 11:2-30"), not lemmas.
    chapter_re = re.compile(work["chapter_re"]) if "chapter_re" in work else CHAPTER_RE
    for i in range(1, len(parts), 2):
        heading = _clean(parts[i])
        body = parts[i + 1].replace("</article>", "").rstrip() + "\n"
        m = chapter_re.match(heading)
        sections.append(
            {
                "heading": heading,
                "chapter": int(m.group(1)) if m else None,
                "html": parts[i] + "\n" + body.lstrip("\n"),
                "body": body,
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
    "We have Jerome's {title} here: \"{units_dir}/{first_unit}\" with the files continuing "
    "up to \"{units_dir}/{last_unit}\". These are consecutive pieces cut, in order, from our "
    "fresh, PUBLIC-DOMAIN English translation of the whole work, \"{html_path}\" (consult it "
    "if you need surrounding context). The work is Jerome's verse-by-verse commentary on "
    "the book of {book} -- file everything under the book \"{book}\", in the \"{father}/\" "
    "folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (Jerome's headings in it: {headings})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. Each "
    "piece repeats the work's title and translator's note at the top -- that note is "
    "background for you, not commentary; don't import it.\n\n"
    "VERSE KEYS. Each <h2> heading is Jerome's own label for the lemma (the Scripture "
    "passage, in italics, that opens the section). Treat these headings as HINTS ONLY: they "
    "follow the numbering of Jerome's Latin Bible and may be off. For each stretch of "
    "commentary, work out which KJV verse(s) it actually expounds -- compare the Scripture "
    "Jerome quotes and discusses with the KJV text, looking it up with `" + KJV_LOOKUP + "` -- and file "
    "it there, under KJV chapter/verse numbering.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. Jerome's "
    "sections are only where his lemmas happen to divide -- one may quote a long passage "
    "(e.g. nine verses) and then work through it verse by verse -- so do NOT simply file a "
    "section under the full range of its heading. Break it up wherever the exposition "
    "moves from one verse to the next: e.g. if a stretch comments on 2:5, insert it in "
    "2:5, not in 2:1-9. It's ok to use a range if necessary to avoid breaking up a coherent "
    "thought/piece (Jerome sometimes expounds several verses as one argument), just prefer "
    "smaller ranges/individual verses. When you split a section, its pieces together must "
    "still contain the WHOLE section, every word -- and you split ONLY by cutting the text "
    "into consecutive stretches: each block must be one continuous stretch of Jerome, in "
    "his order. Never cut up or move the lemma: when a section opens by quoting several "
    "verses, that whole quotation stays, uncut, at the start of the first block from the "
    "section. Do NOT duplicate the same stretch of "
    "commentary across several ADJACENT {book} verses -- put it ONCE, at its smallest "
    "accurate verse/range.\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the adjacent-{book}-verse "
    "duplication forbidden above). Jerome constantly quotes and expounds other Scripture. "
    "Whenever a stretch genuinely QUOTES AND EXPOUNDS a specific verse from another book "
    "-- a Psalm or other OT verse, a Gospel passage, or an Epistle passage -- you may ALSO "
    "file that portion under that verse in its own file (e.g. \"Isaiah 29_13\", \"Jude "
    "1_9\"), in addition to its {book} placement. File a cross-parallel only where Jerome "
    "genuinely expounds the passage, not for a passing mention or a bare one-line "
    "proof-text. Use KJV book/verse numbering for the target file -- note Jerome cites the "
    "Psalms by the Latin (LXX) numbering, which is often one lower (e.g. his \"Psalm 17\" "
    "= KJV Psalm 18).\n\n"
    "NON-VERSE SECTIONS. The \"Prologue\" introduces the whole work: file it under "
    "\"{book} 1_1\" as a block of its own, placed BEFORE the 1:1 commentary -- even if it "
    "discusses some later verse (don't file it under that verse). A \"Book N\" preface: "
    "file it under the verse(s) it substantively comments on, as a block of its own; if it "
    "is purely dedicatory or autobiographical, with nothing tied to particular verses, skip "
    "it and say so. Manuscript rubrics such as \"HERE BEGINS THE BOOK.\" are not "
    "Jerome's commentary; leave them out.\n\n"
    "THE TEXT. Copy Jerome's words VERBATIM -- nothing abridged, paraphrased, corrected, "
    "added or rearranged -- and keep the lemma where it stands in the source. Drop the html tags "
    "(italics simply become plain text; don't turn them into quotation marks) and separate "
    "paragraphs with a single blank line. Don't add headings, verse numbers or notes of "
    "your own. Don't write a python script to do this; process the file yourself "
    "manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- the whole work sits behind one page).\n\n"
    "EXISTING BLOCKS. The old imports of this work (an earlier machine translation, same "
    "source_url) have ALREADY been deleted, so you are only ADDING: if a verse file exists, "
    "append your [[commentary]] after its existing blocks; otherwise create it. Blocks from "
    "other works (letters, homilies, etc.) must be left exactly as they are."
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

    log_dir = os.path.join(WORK_DIR, f"jerome_{args.work.lower()}_import_logs")
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
