#!/usr/bin/env python3
"""Batch-dispatch claude -p runs to flesh out quote fragments.

Pops paths from fixme.md, writes them to fixme_in_progress.md,
and dispatches parallel `claude -p` invocations to find sources
and expand commentary fragments.
"""

import os
import subprocess
import sys

QUEUE = "/Users/seankooyman/Desktop/Commentaries-Database/fixme.md"
IN_PROGRESS = "/Users/seankooyman/Desktop/Commentaries-Database/fixme_in_progress.md"
PROMPT_FILE = "/Users/seankooyman/Desktop/Scripts/prompts/quote_fragment.txt"

BATCH_SIZE = 100
CHUNK_SIZE = 5
CONCURRENCY = 5

PREAMBLE = """The following files are potentially commentary fragments rather than full commentaries on the verse specified in the filename.

Your task is to examine these specific files, reading the commentaries in each one. For each one do a grep through the sources in /Users/seankooyman/Desktop/Writings-Database/ in the appropriate folder to see if you can find the source for the quote fragment. Then (if necessary) update the commentary file both with the correct source title/url. Most importantly, flesh out the quote fragment so it captures the author's full thought on the bible verse it's a commentary on."""

SUFFIX = """Do not use subagents.

Files for you to go through:
{file_list}"""

_cached_template = None


def load_prompt():
    global _cached_template
    if _cached_template is not None:
        return _cached_template

    if not os.path.isfile(PROMPT_FILE):
        print(f"Error: prompt file {PROMPT_FILE} not found")
        sys.exit(1)

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    middle_lines = []
    capture = False
    for line in lines:
        if line.startswith("Source urls should be"):
            capture = True
        if capture:
            if "delete the lines from" in line.lower():
                break
            middle_lines.append(line)

    middle = "\n".join(middle_lines).rstrip()
    _cached_template = f"{PREAMBLE}\n\n{middle}\n\n{SUFFIX}"
    return _cached_template


def pop_batch():
    try:
        with open(QUEUE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: {QUEUE} not found")
        sys.exit(1)

    popped = lines[:BATCH_SIZE]
    remaining = lines[BATCH_SIZE:]

    with open(QUEUE, "w", encoding="utf-8") as f:
        f.writelines(remaining)

    return [line.strip() for line in popped if line.strip()]


def write_in_progress(paths):
    with open(IN_PROGRESS, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(p + "\n")


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def build_prompt(chunk):
    file_list = "\n".join(f"- {p}" for p in chunk)
    template = load_prompt()
    return template.format(file_list=file_list)


def run_wave(chunks, wave_index):
    print(f"\n=== Wave {wave_index + 1}: launching {len(chunks)} concurrent claude -p runs ===")
    procs = []
    for i, chunk in enumerate(chunks):
        prompt = build_prompt(chunk)
        label = f"wave {wave_index + 1}, chunk {i + 1}/{len(chunks)}"
        print(f"[{label}] starting ({len(chunk)} files)")
        p = subprocess.Popen(
            ["claude", "-p", "--model", "claude-opus-4-8", "--dangerously-skip-permissions", prompt],
        )
        procs.append((label, p))

    failures = 0
    for label, p in procs:
        rc = p.wait()
        if rc != 0:
            print(f"[{label}] FAILED (exit {rc})")
            failures += 1
        else:
            print(f"[{label}] done")
    return failures


def main():
    load_prompt()

    popped = pop_batch()
    if not popped:
        print(f"{QUEUE} is empty. Nothing to do.")
        return

    write_in_progress(popped)
    print(f"Popped {len(popped)} paths from {QUEUE} and wrote to {IN_PROGRESS}")

    chunks = list(chunked(popped, CHUNK_SIZE))
    print(f"Split into {len(chunks)} chunks of up to {CHUNK_SIZE} files each")

    waves = list(chunked(chunks, CONCURRENCY))
    total_failures = 0
    for wave_index, wave in enumerate(waves):
        total_failures += run_wave(wave, wave_index)

    print(f"\nAll waves complete. Chunks: {len(chunks)}, failures: {total_failures}")


if __name__ == "__main__":
    main()
