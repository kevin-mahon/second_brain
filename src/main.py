import os
from vault import Vault 
from note import Note, generate_id
from config import SECOND_BRAIN_DIR
import datetime

#TODO:
# 1. Add a search functionality
# 2. Add link map functionality

def read_note(filename, id):
    note = Note(filename, id)
    with open(f"{SECOND_BRAIN_DIR}/{filename}.md", "r") as fd:
        content = fd.read()
        note.content = content
        tag_follows = False
        links_follows = False
        tags = []
        links = []
        for line in content.split("\n"):
            if line.startswith("# Tags:"):
                tag_follows = True
                continue
            if tag_follows:
                if line.startswith("# Links:"):
                    tag_follows = False
                    links_follows = True
                    continue
                else:
                    if line.startswith("-"):
                        tags.append(line[1:].strip())
            if links_follows:
                if line.startswith("-"):
                    links.append(line[1:].strip())

        for tag in tags:
            note.add_tag(tag)   
        for link in links:
            note.add_link(link)
    return note


def generate_note(filename="note"):
    with open(f"{SECOND_BRAIN_DIR}/{filename}.md", "w") as fd:
        content = f"# Title: {filename}\n" 
        date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content += f"# Date: {date} \n"
        id = generate_id()
        content += f"# ID: {id}\n"
        content += "\n\n\n\n\n\n\n"
        content += f"# Tags: \n"
        content += "-  \n"
        content += f"# Links: \n"
        content += "-  \n"
        fd.write(content)
    os.system(f"nvim {SECOND_BRAIN_DIR}/{filename}.md")
    note = read_note(filename,id) #here we read the note back into the note object
    vault.add_note(note)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="A note taking app for Software Engineers")
    parser.add_argument("--set_dir", help="set the directory for notes")
    parser.add_argument("-s", "--search", help="search for a note")
    parser.add_argument("-l", "--list", action="store_true", help="list all notes")
    parser.add_argument("-e", "--edit", help="edit a note")
    parser.add_argument("-b", "--backlink", help="find notes that link to this note")
    parser.add_argument("filename", nargs="?", help="name of the note")
    args = parser.parse_args()
    if args.set_dir:
        print("setting directory")
        SECOND_BRAIN_DIR = args.set_dir

    if not os.path.exists(SECOND_BRAIN_DIR):
        os.makedirs(SECOND_BRAIN_DIR)

    vault = Vault()

    if args.search:
        print("Searching for note .. .")
        vault.search(args.search)
    elif args.backlink:
        print("Finding backlinks .. .")
        vault.backlink(args.backlink)
    elif args.list:
        vault.list()
    elif args.edit:
        id = vault.get_id(args.edit)
        if id:
            os.system(f"nvim {SECOND_BRAIN_DIR}/{args.edit}.md")
            note = read_note(args.edit, id)
            vault.update(note)
        else:
            print(f"Note {args.edit} not found")
    else:
        generate_note(args.filename)

    vault.save()


