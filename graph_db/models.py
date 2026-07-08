# models.py

import uuid

class Node:
    def __init__(self, labels=None, properties=None):
        self.id = str(uuid.uuid4())
        self.labels = labels if labels else []
        self.properties = properties if properties else {}

class Relationship:
    def __init__(self, source, target, type_, properties=None):
        self.id = str(uuid.uuid4())
        self.source = source
        self.target = target
        self.type = type_
        self.properties = properties if properties else {}
