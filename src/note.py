import uuid
import json

#this is the atom of the system
#each note has tags and links
#tags are used for searching
#links are used for connecting notes

def generate_id():
    return uuid.uuid4().int

class Note:
    def __init__(self, title, content, id=None):
        self.id = uuid.uuid4().int if id is None else id 
        self.title = title 
        self.content = content
        # TODO: tag itself??
        self.tags = []
        self.links = []

    def __str__(self):
        return f"{self.id}: {self.title}"

    def __repr__(self):
        return json.dumps(
            self,
            default=lambda o: o.__dict__,
            sort_keys=True,
            indent=0
        )

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    @property
    def importance(self):
        return len(self.links)

    def add_tag(self, tag):
        self.tags.append(tag)

    def add_link(self, link):
        self.links.append(link)

    def edit(self, new_content):
        self.content = new_content

    def append(self, new_content):
        self.content += new_content
