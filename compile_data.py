import sys
import os
import json
import sqlite3
import csv
from pathlib import Path
import rtoml
import uuid
from typing import NamedTuple, Dict
import re
import argparse


class VerseRange(NamedTuple):
    start_chapter: int
    start_verse: int
    end_chapter: int
    end_verse: int


def string_to_verse_range(verse_string: str) -> VerseRange:
    """

    :param verse_string: A verse string i.e. 1_57-58 or 1_57-2_32
    :return:
    """
    verse_pieces = re.split('[_-]', verse_string)
    start_chapter = verse_pieces[0]
    start_verse = verse_pieces[1]
    if len(verse_pieces) == 2:
        # i.e. 1_56
        end_chapter = start_chapter
        end_verse = start_verse
    elif len(verse_pieces) == 3:
        # i.e. 1_57-57
        end_chapter = start_chapter
        end_verse = verse_pieces[2]
    elif len(verse_pieces) == 4:
        # i.e. 1_57-2_32
        end_chapter = verse_pieces[2]
        end_verse = verse_pieces[3]
    else:
        raise ValueError(f'Unexpected format of verse_string: {verse_string}')

    return VerseRange(
        start_chapter=int(start_chapter),
        start_verse=int(start_verse),
        end_chapter=int(end_chapter),
        end_verse=int(end_verse)
    )


def encode_chapter_verse(chapter: int, verse: int) -> int:
    return (chapter * 1000000) + verse


def process_toml():
    file_list = [path for path in Path.cwd().glob('**/*') if path.is_file() and path.suffix == '.toml']

    father_meta_data = {}

    # First loop through all metadata files, build them up into default lookup table
    total_file_count = 0
    for file in file_list:
        # Pseudo-Jerome/Mark 6_35-44.toml
        short_file_name = file.relative_to(Path.cwd())
        if short_file_name.name == 'metadata.toml':
            toml_str = file.read_text()
            toml_obj = rtoml.load(toml_str)
            father_meta_data[file.parent.name] = toml_obj
        elif file.suffix == '.toml':
            total_file_count += 1

    data_values = []

    # Then loop through all files, load them into an object
    current_file_count = 0
    for file in file_list:
        try:
            if file.name == 'metadata.toml':
                continue

            for i in range(10):
                if current_file_count == int(total_file_count * (0.1 * i)):
                    print(f"{i}0% done ({current_file_count} / {total_file_count})")
            current_file_count += 1

            father_name = file.parent.name
            file_name = file.stem
            fn_pieces = file_name.split(" ")
            book_name = " ".join(fn_pieces[:-1])

            verse_range = string_to_verse_range(fn_pieces[-1])

            location_start = encode_chapter_verse(verse_range.start_chapter, verse_range.start_verse)
            location_end = encode_chapter_verse(verse_range.end_chapter, verse_range.end_verse)

            toml_str = file.read_text(encoding='utf-8')
            toml_obj = rtoml.load(toml_str)

            for c in toml_obj['commentary']:
                source_url = c.get('source_url', '')
                source_title = c.get('source_title', '')

                time = 9999999
                if father_name in father_meta_data:
                    time = father_meta_data[father_name]['default_year']
                if 'time' in c:
                    time = c['time']

                append_to_author_name = c.get('append_to_author_name', '')

                data_values.append([
                    str(uuid.uuid4()),
                    father_name,
                    file.name,
                    append_to_author_name,
                    time,
                    book_name.lower().replace(" ", ""),
                    location_start,
                    location_end,
                    c['quote'],
                    source_url,
                    source_title
                ])
        except BaseException as error:
            print("******Error in", file)
            print("Error Reads: ", error)
            raise
    print(f"*Files processed: {current_file_count}")

    formatted_father_meta_data = [
        [
            fn,
            father_meta_data[fn]['default_year'],
            father_meta_data[fn]['wiki'],
        ] for fn in father_meta_data
    ]
    return {
        "father_meta_data": formatted_father_meta_data,
        "commentary_data": data_values
    }


def to_sqlite(toml_data: Dict, out_path: Path):
    if out_path.is_file():
        os.remove(out_path)

    sqlite_connection = None

    try:
        sqlite_connection = sqlite3.connect(out_path)
        cursor = sqlite_connection.cursor()

        cursor.execute('''CREATE TABLE IF NOT EXISTS "father_meta" (
            "name" VARCHAR,
            "default_year" VARCHAR,
            "wiki_url" VARCHAR
        )
        ;''')
        cursor.execute('''CREATE UNIQUE INDEX idx_father_meta_name ON father_meta (name);''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS "commentary" (
            "id" VARCHAR,
            "father_name" VARCHAR,
            "file_name" VARCHAR,
            "append_to_author_name" VARCHAR,
            "ts" INTEGER,
            "book" VARCHAR,
            "location_start" INTEGER,
            "location_end" INTEGER,
            "txt" TEXT,
            "source_url" VARCHAR,
            "source_title" VARCHAR
        )
        ;''')
        cursor.execute('''CREATE UNIQUE INDEX idx_commentary_id ON commentary (id);''')
        cursor.execute('''CREATE INDEX idx_commentary_book ON commentary (book);''')
        cursor.execute('''CREATE INDEX idx_commentary_location_start ON commentary (location_start);''')
        cursor.execute('''CREATE INDEX idx_commentary_location_end ON commentary (location_end);''')

        sqlite_insert_query = """INSERT INTO father_meta
                            (name, default_year, wiki_url) 
                            VALUES (?, ?, ?);"""
        cursor.executemany(sqlite_insert_query, toml_data['father_meta_data'])
        sqlite_insert_query = """INSERT INTO commentary
                            (id, father_name, file_name, append_to_author_name, ts, book, location_start, location_end, txt, source_url, source_title) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"""
        cursor.executemany(sqlite_insert_query, toml_data['commentary_data'])
        sqlite_connection.commit()
        print("Total", cursor.rowcount, "Records inserted successfully")
        sqlite_connection.commit()
        cursor.close()

    except sqlite3.Error as error:
        print("Error:", error)
    finally:
        if sqlite_connection:
            sqlite_connection.close()


def to_json(toml_data: Dict, out_path: Path):
    final_data = []
    for d in toml_data['commentary_data']:
        final_data.append({
            "id": d[0],
            "father_name": d[1],
            "file_name": d[2],
            "append_to_author_name": d[3],
            "ts": d[4],
            "book": d[5],
            "location_start": d[6],
            "location_end": d[7],
            "txt": d[8],
            "source_url": d[9],
            "source_title": d[10],
        })
    with out_path.open('w') as f:
        json.dump(final_data, f)


def to_csv(toml_data: Dict, out_path: Path):
    data = toml_data['commentary_data']
    writer = csv.writer(out_path.open('w', encoding='utf-8'))
    writer.writerow(["id", "father_name", "file_name", "append_to_author_name", "ts", "book", "location_start", "location_end", "txt", "source_url",
                     "source_title"])
    for row in data:
        writer.writerow(row)


def parse_arguments():
    parser = argparse.ArgumentParser(
        prog='CompileData',
        description='Compiles the Commentaries Database into various formats'
    )

    parser.add_argument('output_format', choices=['json', 'csv', 'sqlite', 'dryrun'], default='dryrun')
    parser.add_argument('-o', '--out', type=Path, default=Path('data.out'))
    return parser.parse_args()


def main():
    args = parse_arguments()

    print('Starting to Compile')
    toml_data = process_toml()
    if args.output_format == 'json':
        print("Saving into JSON...")
        to_json(toml_data, args.out)
    elif args.output_format == 'csv':
        print("Saving into CSV...")
        to_csv(toml_data, args.out)
    elif args.output_format == 'sqlite':
        print("Saving into SQLITE...")
        to_sqlite(toml_data, args.out)
    else:  # dryrun
        print("Dryrun finished")


if __name__ == '__main__':
    main()
