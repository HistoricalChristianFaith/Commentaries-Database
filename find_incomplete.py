#!/usr/bin/env python3
"""Find commentary quotes that appear to be incomplete fragments (cut off mid-sentence)."""

import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "incomplete.md")

STARTS_MID_SENTENCE = re.compile(
    r'^[,;]'            # starts with comma or semicolon
    r'|^\.{3}'         # starts with ellipsis
    r'|^—'             # starts with em-dash continuation
)

# Lowercase start is mid-sentence UNLESS it's a known abbreviation
LOWERCASE_START = re.compile(r'^[a-z]')
ABBREVIATION_START = re.compile(r'^(i\.\s*e\.|e\.\s*g\.|viz\.|cf\.|etc\.)')

# Words/patterns at the very end that strongly suggest cut-off
TRAILING_CONNECTORS = re.compile(
    r'\b(and|but|or|nor|for|yet|so|that|which|who|whom|whose|where|when|'
    r'while|although|because|since|if|unless|until|than|whether|'
    r'the|a|an|his|her|its|their|our|my|your|this|that|these|those|'
    r'to|of|in|on|at|by|with|from|into|upon|about|through|after|before|'
    r'not|also|even|shall|will|should|would|could|may|might|must|can)$',
    re.IGNORECASE
)

TERMINAL_PUNCT = re.compile("[.!?:'\u2018\u2019\u201c\u201d)\\]]$")

# Patterns that look like source titles or footnote markers at the end (false positives)
FALSE_POSITIVE_END = re.compile(
    r'\.[a-z]$'                  # footnote marker like ".a" or ".c"
    r'|(?:City of God|On the Psalms|On Man\'s|Com\. on|Homil)',  # source titles
    re.IGNORECASE
)


def extract_quotes(filepath):
    """Extract all quote texts from a TOML commentary file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except (UnicodeDecodeError, IOError):
        return []

    quotes = []
    pattern = re.compile(r"quote\s*=\s*'''(.*?)'''", re.DOTALL)
    for match in pattern.finditer(content):
        text = match.group(1).strip()
        if text:
            quotes.append(text)

    pattern2 = re.compile(r'quote\s*=\s*"""(.*?)"""', re.DOTALL)
    for match in pattern2.finditer(content):
        text = match.group(1).strip()
        if text:
            quotes.append(text)

    pattern3 = re.compile(r'''quote\s*=\s*['"]([^'"\n]+)['"]''')
    for match in pattern3.finditer(content):
        text = match.group(1).strip()
        if text:
            quotes.append(text)

    return quotes


def is_incomplete(text):
    """Determine if a quote appears to be an incomplete fragment."""
    reasons = []

    # Check if it starts mid-sentence
    if STARTS_MID_SENTENCE.match(text):
        reasons.append("starts_mid_sentence")
    elif LOWERCASE_START.match(text) and not ABBREVIATION_START.match(text):
        reasons.append("starts_mid_sentence")

    # Analyze the ending
    cleaned_end = text.rstrip()
    # Remove trailing scripture references in brackets like [John 1:2]
    cleaned_end = re.sub(r'\s*\[[^\]]*\d+[:\d]*[^\]]*\]\s*$', '', cleaned_end).rstrip()
    # Remove trailing ellipsis (deliberate truncation, still incomplete)
    had_ellipsis = cleaned_end.endswith('…') or cleaned_end.endswith('...')
    if had_ellipsis:
        reasons.append("ends_with_ellipsis")

    if not cleaned_end:
        return reasons if reasons else None

    # Skip known false positive patterns
    if FALSE_POSITIVE_END.search(cleaned_end):
        return reasons if reasons else None

    last_char = cleaned_end[-1]

    # Ends with comma or semicolon - very strong signal
    if last_char in ',;':
        reasons.append("ends_with_comma_or_semicolon")
    # Ends without terminal punctuation
    elif not TERMINAL_PUNCT.search(cleaned_end[-1:]):
        last_word_match = re.search(r'(\S+)\s*$', cleaned_end)
        if last_word_match:
            last_word = last_word_match.group(1).rstrip('.,;:!?')
            if TRAILING_CONNECTORS.search(last_word):
                reasons.append("ends_with_connector_word")
            else:
                reasons.append("no_terminal_punctuation")

    return reasons if reasons else None


def main():
    results = []
    file_count = 0

    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for fname in files:
            if not fname.endswith('.toml'):
                continue

            filepath = os.path.join(root, fname)
            file_count += 1

            quotes = extract_quotes(filepath)
            for i, quote in enumerate(quotes):
                reasons = is_incomplete(quote)
                if reasons:
                    results.append(filepath)
                    break  # only list each file once

    results.sort()
    # Deduplicate (a file might appear once already due to break, but just in case)
    results = list(dict.fromkeys(results))

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for filepath in results:
            f.write(f"{filepath}\n")

    print(f"Done. Found {len(results)} files with incomplete fragments (out of {file_count} total files).")
    print(f"Results written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
