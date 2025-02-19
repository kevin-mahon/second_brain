This repository is a personal project to create a note taking app.
The application heavily mirrors the Zettelkasten method of note taking. 
Each note has some metadata (id, title, tags, date created) and a body.
These notes are then linked via tags and backlinks. The entire app is designed
to be a CLI tool for managing 'personal knowledge storage.' It should work well
with vim-like editors.

Currently all the note metadata is aggregated into a vault stored in
`~/second_brain/notes.json`. The notes themselves are stored in 
`~/second_brain/notes/` as markdown files. The vault uses encryption to store 
the metadata securely, the key for this is generated on first use and stored in 
`~/.second_brain_key`.

## Features
- [X] Add notes
- [X] Markdown support
- [ ] Graph view
- [X] Tagging
- [X] Search
- [X] Backlinks
- [ ] Drawing support
- [ ] Mobile app ???
- [ ] Sync 
- [ ] Export 
- [ ] Import 

## Installation
1. Clone the repository
2. Run `chmod +x setup.sh && ./setup.sh`
3. Run `source bin/activate` to start the virtual environment
    - To deactivate the virtual environment run `deactivate`
4. Run `pip install -r requirements.txt`
5. (Optional) Alias the script to a command in your shell i.e.
    `alias sb="<path to repo>/sb.sh"`

## Usage
- `sb <note name>` - Add a new note
- `sb -l` - List all notes
- `sb -s <tag>` - Search for notes with a tag 
- `sb -b <note name>` - List all notes that link to this note 
- `sb -e <note name>` - Edit a note


