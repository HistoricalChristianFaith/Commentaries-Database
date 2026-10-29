#!/usr/bin/env python3
"""
Bible Verse Lookup Script
Looks up KJV Bible verses from SQLite database.

Usage:
    python lookup.py "John 3:16"
    python lookup.py "Genesis 1:1-3"
    python lookup.py "1 Corinthians 13:4-7"
"""

import sqlite3
import sys
import re
import os

# Database path (relative to this script's location)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, 'kjv.sqlite')

# Book name normalization mapping
BOOK_ALIASES = {
    # Common variations -> database name
    'gen': 'genesis',
    'exod': 'exodus',
    'ex': 'exodus',
    'lev': 'leviticus',
    'num': 'numbers',
    'deut': 'deuteronomy',
    'josh': 'joshua',
    'judg': 'judges',
    'sam': 'samuel',
    'kgs': 'kings',
    'chron': 'chronicles',
    'chr': 'chronicles',
    'neh': 'nehemiah',
    'est': 'esther',
    'ps': 'psalms',
    'psalm': 'psalms',
    'prov': 'proverbs',
    'eccl': 'ecclesiastes',
    'eccles': 'ecclesiastes',
    'song': 'songofsolomon',
    'songs': 'songofsolomon',
    'songofsongs': 'songofsolomon',
    'canticles': 'songofsolomon',
    'isa': 'isaiah',
    'jer': 'jeremiah',
    'lam': 'lamentations',
    'ezek': 'ezekiel',
    'eze': 'ezekiel',
    'dan': 'daniel',
    'hos': 'hosea',
    'ob': 'obadiah',
    'jon': 'jonah',
    'mic': 'micah',
    'nah': 'nahum',
    'hab': 'habakkuk',
    'zeph': 'zephaniah',
    'hag': 'haggai',
    'zech': 'zechariah',
    'zec': 'zechariah',
    'mal': 'malachi',
    'matt': 'matthew',
    'mat': 'matthew',
    'mt': 'matthew',
    'mk': 'mark',
    'lk': 'luke',
    'jn': 'john',
    'joh': 'john',
    'rom': 'romans',
    'cor': 'corinthians',
    'gal': 'galatians',
    'eph': 'ephesians',
    'phil': 'philippians',
    'php': 'philippians',
    'col': 'colossians',
    'thess': 'thessalonians',
    'thes': 'thessalonians',
    'tim': 'timothy',
    'tit': 'titus',
    'phlm': 'philemon',
    'phm': 'philemon',
    'heb': 'hebrews',
    'jas': 'james',
    'jam': 'james',
    'pet': 'peter',
    'jude': 'jude',
    'rev': 'revelation',
    'apoc': 'revelation',
    'apocalypse': 'revelation',
}


def normalize_book_name(book: str) -> str:
    """
    Normalize book name to match database format.
    Examples:
        "John" -> "john"
        "1 Corinthians" -> "1corinthians"
        "Song of Solomon" -> "songofsolomon"
        "1 John" -> "1john"
    """
    # Extract leading number if present (e.g., "1 John" -> "1", "John")
    match = re.match(r'^(\d+)\s*(.+)$', book.strip())
    if match:
        number = match.group(1)
        name = match.group(2)
    else:
        number = ''
        name = book.strip()

    # Normalize the name part
    name_lower = name.lower().replace(' ', '').replace('-', '')

    # Check aliases
    if name_lower in BOOK_ALIASES:
        name_lower = BOOK_ALIASES[name_lower]

    return f"{number}{name_lower}"


def parse_verse_reference(reference: str) -> tuple:
    """
    Parse a verse reference string.
    Returns: (book, chapter, start_verse, end_verse)

    Examples:
        "John 3:16" -> ("john", 3, 16, 16)
        "Genesis 1:1-3" -> ("genesis", 1, 1, 3)
        "1 Corinthians 13:4-7" -> ("1corinthians", 13, 4, 7)
    """
    # Pattern: [number] Book Chapter:Verse[-EndVerse]
    pattern = r'^(.+?)\s+(\d+):(\d+)(?:-(\d+))?$'
    match = re.match(pattern, reference.strip())

    if not match:
        raise ValueError(f"Invalid verse reference format: '{reference}'. Expected format: 'Book Chapter:Verse' or 'Book Chapter:Start-End'")

    book = normalize_book_name(match.group(1))
    chapter = int(match.group(2))
    start_verse = int(match.group(3))
    end_verse = int(match.group(4)) if match.group(4) else start_verse

    return book, chapter, start_verse, end_verse


def lookup_verses(book: str, chapter: int, start_verse: int, end_verse: int) -> list:
    """
    Look up verses from the database.
    Returns list of (verse_number, text) tuples.
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    results = []
    for verse in range(start_verse, end_verse + 1):
        # txt_location encoding: chapter * 1000000 + verse
        txt_location = chapter * 1000000 + verse

        cursor.execute(
            "SELECT txt FROM bible_kjv WHERE book = ? AND txt_location = ?",
            (book, txt_location)
        )
        row = cursor.fetchone()

        if row:
            results.append((verse, row[0].strip()))

    conn.close()
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python lookup.py \"Book Chapter:Verse[-EndVerse]\"")
        print("Examples:")
        print("  python lookup.py \"John 3:16\"")
        print("  python lookup.py \"Genesis 1:1-3\"")
        print("  python lookup.py \"1 Corinthians 13:4-7\"")
        sys.exit(1)

    reference = sys.argv[1]

    try:
        book, chapter, start_verse, end_verse = parse_verse_reference(reference)
        verses = lookup_verses(book, chapter, start_verse, end_verse)

        if not verses:
            print(f"No verses found for {reference}")
            print(f"(Searched for book='{book}', chapter={chapter}, verses {start_verse}-{end_verse})")
            sys.exit(1)

        for verse_num, text in verses:
            print(f"{verse_num} {text}")

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
