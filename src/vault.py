import os
import json
from note import Note
from cryptography.fernet import Fernet
from config import SECOND_BRAIN_DIR, KEY_FILE

class Vault:

    def __init__(self):
        self.store = {}
        self.hubs = {} #dict of tags with notes of highest linkage
        self.tags = [] #list of topics / tags
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "rb") as f:
                self.key = f.read()
        else:
            self.key = Fernet.generate_key()
            with open(KEY_FILE, "wb") as f:
                f.write(self.key)
        self.cipher = Fernet(self.key)
        self.root_of_all_knowledge = Note("Root of All Knowledge", "This is the root of all knowledge", id=0) 
        self.load()

    def add_note(self, note):
        self.store[note.id] = note
        #update tags, add tags to tags list and
        #only use note with highest importance as hub
        #TODO: should use note with highest PER tag importance
        for tag in note.tags:
            if tag not in self.hubs:
                self.hubs[tag] = note
            else:
                if self.hubs[tag].importance < note.importance:
                    self.hubs[tag] = note
            if tag not in self.tags:
                self.tags.append(tag)

    def backlink(self, title):
        #search for notes that link to note
        for id in self.store:
            if (title + ".md") in self.store[id].links:
                print(f"{self.store[id].title} : {self.store[id].tags}")
                return
        print("No backlinks found")
        return

    def search(self, query):
        #search for notes with query in title or tags
        for id in self.store:
            note = self.store[id]
            if query in note.title or query in note.tags:
                print(f"{note.title} : {note.tags}")

    def list(self):
        #list all notes in store 
        #format: note_id: note_title : note_tags
        print("ID: Title : Tags : Links")
        for id in self.store:
            print(f"{id}: {self.store[id].title} : {self.store[id].tags} : {self.store[id].links}")

    def get_id(self, title):
        for id in self.store:
            if self.store[id].title == title:
                return id
        return None

    def update(self, note):
        self.store[note.id] = note

    def save(self):
        with open(SECOND_BRAIN_DIR + "/vault.json", "wb") as f:
            f.write(self.cipher.encrypt(b"N"))
            f.write(os.linesep.encode("ascii"))
            for note in self.store.values():
                f.write(self.cipher.encrypt(json.dumps(note.__dict__).encode("ascii")))
                f.write(os.linesep.encode("ascii"))

    def load(self):
        try:
            notes_flag = False
            with open(SECOND_BRAIN_DIR + "/vault.json", "rb") as f:
                lines = f.readlines()
                lines = [self.cipher.decrypt(line.strip()) for line in lines]
                for line in lines:
                    if line == b'N':
                        notes_flag = True
                        continue
                    if notes_flag:
                        note = json.loads(line.decode("ascii"))
                        note_obj = Note(None, None)
                        note_obj.__dict__ = note
                        self.add_note(note_obj)

        except FileNotFoundError:
            pass

