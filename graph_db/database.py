import uuid
import logging

class Node:
    def __init__(self, labels=None, properties=None):
        self.id = str(uuid.uuid4())
        self.labels = set(labels or [])
        self.properties = properties or {}
    
    def __str__(self):
        label_str = ':'.join(self.labels) if self.labels else ''
        props_str = ', '.join(f"{k}: {repr(v)}" for k, v in self.properties.items())
        return f"({label_str} {{{props_str}}})"
    
    def matches(self, labels=None, properties=None):
        """Check if this node matches the given labels and properties filter"""
        # Check labels
        if labels and not all(label in self.labels for label in labels):
            return False
        
        # Check properties
        if properties:
            for key, value in properties.items():
                if key not in self.properties or self.properties[key] != value:
                    return False
        
        return True
    
    def serialize(self):
        """Convert node to a serializable dictionary"""
        return {
            'id': self.id,
            'labels': list(self.labels),
            'properties': self.properties
        }
    
    @classmethod
    def deserialize(cls, data):
        """Create a node from serialized data"""
        node = cls(labels=data['labels'], properties=data['properties'])
        node.id = data['id']
        return node

class Relationship:
    def __init__(self, source_node, target_node, type_=None, properties=None):
        self.id = str(uuid.uuid4())
        self.source_id = source_node.id
        self.target_id = target_node.id
        self.type = type_ or ''
        self.properties = properties or {}
    
    def __str__(self):
        props_str = ', '.join(f"{k}: {repr(v)}" for k, v in self.properties.items())
        return f"[:{self.type} {{{props_str}}}]"
    
    def matches(self, type_=None, properties=None):
        """Check if this relationship matches the given type and properties filter"""
        # Check type
        if type_ and self.type != type_:
            return False
        
        # Check properties
        if properties:
            for key, value in properties.items():
                if key not in self.properties or self.properties[key] != value:
                    return False
        
        return True
        
    def check_nodes(self, source_id=None, target_id=None):
        """Check if this relationship connects the specified nodes"""
        if source_id is not None and self.source_id != source_id:
            return False
        if target_id is not None and self.target_id != target_id:
            return False
        return True
    
    def serialize(self):
        """Convert relationship to a serializable dictionary"""
        return {
            'id': self.id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'type': self.type,
            'properties': self.properties
        }
    
    @classmethod
    def deserialize(cls, data, source_node, target_node):
        """Create a relationship from serialized data"""
        rel = cls(source_node, target_node, type_=data['type'], properties=data['properties'])
        rel.id = data['id']
        return rel

class GraphDatabase:
    def __init__(self):
        self.nodes = {}  # id -> Node
        self.relationships = {}  # id -> Relationship
        self.constraints = {
            'unique': []  # List of (label, property) pairs that must be unique
        }
        self.indexes = {}  # {'label': {'property': {value: [node_ids]}}}
        self.indexed_properties = []  # List of (label, property) tuples that are indexed
        
    def clear(self):
        """Clear all nodes and relationships from the database"""
        self.nodes = {}
        self.relationships = {}
        self.constraints = {'unique': []}
        self.indexes = {}
        self.indexed_properties = []
        
    def create_node(self, labels, properties):
        """Create and add a node to the database"""
        node = Node(labels=labels, properties=properties)
        self.add_node(node)
        # Note: Persistence handled by transaction system
        return node
        
    def create_relationship(self, source_node, target_node, type_, properties):
        """Create and add a relationship to the database"""
        rel = Relationship(source_node, target_node, type_=type_, properties=properties)
        self.add_relationship(rel)
        # Note: Persistence handled by transaction system
        return rel
    
    def add_node(self, node):
        """Add a node to the database with constraint checking"""
        # Check uniqueness constraints
        for label, prop in self.constraints.get('unique', []):
            if label in node.labels and prop in node.properties:
                # Check if another node with same label and property value exists
                for existing_node in self.nodes.values():
                    if (label in existing_node.labels and 
                        prop in existing_node.properties and 
                        existing_node.properties[prop] == node.properties[prop]):
                        raise ValueError(f"Constraint violation: Node with {label}.{prop}='{node.properties[prop]}' already exists")
        
        # Add the node to the database
        self.nodes[node.id] = node
        
        # Update all relevant indexes
        self.update_indexes_for_node(node)
        
        return node
    
    def add_relationship(self, relationship):
        """Add a relationship to the database"""
        if relationship.source_id not in self.nodes:
            raise ValueError(f"Source node with id {relationship.source_id} does not exist")
        
        if relationship.target_id not in self.nodes:
            raise ValueError(f"Target node with id {relationship.target_id} does not exist")
        
        self.relationships[relationship.id] = relationship
        return relationship
    
    def find_nodes(self, labels=None, properties=None):
        """Find nodes matching labels and properties"""
        return [node for node in self.nodes.values() if node.matches(labels, properties)]
    
    def find_relationships(self, type_=None, properties=None):
        """Find relationships matching type and properties"""
        return [rel for rel in self.relationships.values() if rel.matches(type_, properties)]
    
    def find_relationships_between(self, source_id, target_id, type_=None, properties=None):
        """Find relationships between specific nodes"""
        return [
            rel for rel in self.relationships.values() 
            if rel.source_id == source_id and rel.target_id == target_id and rel.matches(type_, properties)
        ]
    
    def find_relationships_from(self, source_id, type_=None, properties=None):
        """Find outgoing relationships from a node"""
        return [
            rel for rel in self.relationships.values() 
            if rel.source_id == source_id and rel.matches(type_, properties)
        ]
    
    def find_relationships_to(self, target_id, type_=None, properties=None):
        """Find incoming relationships to a node"""
        return [
            rel for rel in self.relationships.values() 
            if rel.target_id == target_id and rel.matches(type_, properties)
        ]
    
    def delete_node(self, node_id):
        """Delete a node and all its relationships"""
        if node_id not in self.nodes:
            raise ValueError(f"Node with id {node_id} does not exist")
        
        # Remove from indexes before deleting
        self.remove_node_from_indexes(node_id)
        
        # Delete all relationships involving this node
        rel_ids_to_delete = []
        for rel_id, rel in self.relationships.items():
            if rel.source_id == node_id or rel.target_id == node_id:
                rel_ids_to_delete.append(rel_id)
        
        for rel_id in rel_ids_to_delete:
            del self.relationships[rel_id]
        
        # Delete the node
        del self.nodes[node_id]
    
    def delete_relationship(self, relationship_id):
        """Delete a relationship"""
        if relationship_id not in self.relationships:
            raise ValueError(f"Relationship with id {relationship_id} does not exist")
        
        del self.relationships[relationship_id]
    
    def add_unique_constraint(self, label, property_name):
        """Add a uniqueness constraint on label and property"""
        constraint = (label, property_name)
        if constraint not in self.constraints['unique']:
            # Validate existing data to ensure no duplicates exist
            property_values = {}
            duplicates = []
            
            for node in self.nodes.values():
                if label in node.labels and property_name in node.properties:
                    value = node.properties[property_name]
                    if value in property_values:
                        duplicates.append((value, node.id, property_values[value]))
                    property_values[value] = node.id
            
            # If duplicates found, provide detailed error
            if duplicates:
                error_msg = "Cannot add constraint: Found duplicate values:\n"
                for value, node_id1, node_id2 in duplicates:
                    error_msg += f"  Value '{value}' exists in nodes {node_id1} and {node_id2}\n"
                raise ValueError(error_msg)
            
            # No duplicates found, add the constraint
            self.constraints['unique'].append(constraint)
            logging.debug(f"Added unique constraint on {label}.{property_name}")
            
    def drop_constraint(self, label, property_name):
        """Remove a uniqueness constraint"""
        constraint = (label, property_name)
        if constraint in self.constraints['unique']:
            self.constraints['unique'].remove(constraint)
            logging.debug(f"Dropped constraint on {label}.{property_name}")
            return True
        else:
            logging.debug(f"Constraint on {label}.{property_name} not found")
            return False
    
    def create_index(self, label, property_name):
        """Create an index on a label and property combination"""
        index_key = (label, property_name)
        if index_key in self.indexed_properties:
            logging.debug(f"Index on {label}.{property_name} already exists")
            return False
            
        # Initialize the index structure if needed
        if label not in self.indexes:
            self.indexes[label] = {}
        if property_name not in self.indexes[label]:
            self.indexes[label][property_name] = {}
            
        # Populate the index with existing data
        for node_id, node in self.nodes.items():
            if label in node.labels and property_name in node.properties:
                value = node.properties[property_name]
                if value not in self.indexes[label][property_name]:
                    self.indexes[label][property_name][value] = []
                self.indexes[label][property_name][value].append(node_id)
                
        # Add to the list of indexed properties
        self.indexed_properties.append(index_key)
        logging.debug(f"Created index on {label}.{property_name}")
        return True
        
    def drop_index(self, label, property_name):
        """Drop an index on a label and property combination"""
        index_key = (label, property_name)
        if index_key not in self.indexed_properties:
            logging.debug(f"Index on {label}.{property_name} does not exist")
            return False
            
        # Remove from indexes
        if label in self.indexes and property_name in self.indexes[label]:
            del self.indexes[label][property_name]
            if not self.indexes[label]:  # If no more properties indexed for this label
                del self.indexes[label]
                
        # Remove from indexed properties list
        self.indexed_properties.remove(index_key)
        logging.debug(f"Dropped index on {label}.{property_name}")
        return True
        
    def update_indexes_for_node(self, node):
        """Update all indexes for a node"""
        for label, property_name in self.indexed_properties:
            if label in node.labels and property_name in node.properties:
                value = node.properties[property_name]
                
                # Add to index
                if label not in self.indexes:
                    self.indexes[label] = {}
                if property_name not in self.indexes[label]:
                    self.indexes[label][property_name] = {}
                if value not in self.indexes[label][property_name]:
                    self.indexes[label][property_name][value] = []
                    
                # Ensure no duplicates in the index
                if node.id not in self.indexes[label][property_name][value]:
                    self.indexes[label][property_name][value].append(node.id)
                    
    def remove_node_from_indexes(self, node_id):
        """Remove a node from all indexes when it's deleted"""
        node = self.nodes.get(node_id)
        if not node:
            return
            
        for label, property_name in self.indexed_properties:
            if label in node.labels and property_name in node.properties:
                value = node.properties[property_name]
                
                if (label in self.indexes and 
                    property_name in self.indexes[label] and 
                    value in self.indexes[label][property_name]):
                    
                    # Remove node ID from this index
                    if node_id in self.indexes[label][property_name][value]:
                        self.indexes[label][property_name][value].remove(node_id)
                        
                    # Clean up empty entries
                    if not self.indexes[label][property_name][value]:
                        del self.indexes[label][property_name][value]
                        
    def find_nodes_by_index(self, label, property_name, value):
        """Find nodes using an index for better performance"""
        if ((label, property_name) in self.indexed_properties and
            label in self.indexes and
            property_name in self.indexes[label] and
            value in self.indexes[label][property_name]):
            
            # Use the index to directly get matching node IDs
            node_ids = self.indexes[label][property_name][value]
            return [self.nodes[node_id] for node_id in node_ids if node_id in self.nodes]
        else:
            # Fall back to full scan if no index or value not found
            return [
                node for node in self.nodes.values()
                if label in node.labels and property_name in node.properties and node.properties[property_name] == value
            ]
    
    def serialize(self):
        """Convert the database to a serializable dictionary"""
        return {
            'nodes': [node.serialize() for node in self.nodes.values()],
            'relationships': [rel.serialize() for rel in self.relationships.values()],
            'constraints': self.constraints,
            'indexes': self.indexed_properties
        }
    
    def deserialize(self, data):
        """Restore database from serialized data"""
        # Clear current database
        self.nodes = {}
        self.relationships = {}
        self.constraints = data.get('constraints', {'unique': []})
        self.indexes = {}
        self.indexed_properties = []
        
        # Restore nodes
        for node_data in data.get('nodes', []):
            node = Node.deserialize(node_data)
            self.nodes[node.id] = node
        
        # Restore relationships
        for rel_data in data.get('relationships', []):
            source_node = self.nodes.get(rel_data['source_id'])
            target_node = self.nodes.get(rel_data['target_id'])
            
            if source_node and target_node:
                rel = Relationship(source_node, target_node, type_=rel_data['type'], properties=rel_data['properties'])
                rel.id = rel_data['id']
                self.relationships[rel.id] = rel
                
        # Restore indexes if present in the data
        if 'indexes' in data:
            # Restore indexed properties list
            self.indexed_properties = data['indexes']
            
            # Rebuild the indexes from the node data
            for label_prop in self.indexed_properties:
                label, prop = label_prop
                self.create_index(label, prop)
