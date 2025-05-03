import re
import logging
from .cypher import evaluate_condition
from .database import Node, Relationship

class CypherParser:
    def __init__(self, database):
        self.db = database
    
    def execute(self, query):
        """Parse and execute a Cypher-like query"""
        query = query.strip()
        
        # Identify query type
        if query.upper().startswith("CREATE "):
            return self._execute_create(query)
        elif query.upper().startswith("MATCH "):
            return self._execute_match(query)
        elif query.upper().startswith("DELETE "):
            return self._execute_delete(query)
        else:
            raise ValueError(f"Unsupported query type: {query}")
    
    def _execute_create(self, query):
        """Execute a CREATE query"""
        # Handle node creation: CREATE (:Label {prop: value})
        node_pattern = r"CREATE\s+\(([^)]*)\)"
        node_matches = re.findall(node_pattern, query, re.IGNORECASE)
        
        if node_matches:
            created_nodes = []
            for node_match in node_matches:
                # Parse labels
                labels = []
                label_pattern = r":(\w+)"
                label_matches = re.findall(label_pattern, node_match)
                labels.extend(label_matches)
                
                # Parse properties
                properties = {}
                prop_pattern = r"{([^}]*)}"
                prop_matches = re.findall(prop_pattern, node_match)
                
                if prop_matches:
                    # Process properties like name: 'value', age: 30
                    prop_str = prop_matches[0]
                    prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", prop_str)
                    
                    for key, value in prop_items:
                        # Convert property values to appropriate types
                        value = value.strip()
                        if value.startswith("'") and value.endswith("'"):
                            # String
                            properties[key] = value[1:-1]
                        elif value.startswith('"') and value.endswith('"'):
                            # String
                            properties[key] = value[1:-1]
                        elif value.lower() == 'true':
                            # Boolean
                            properties[key] = True
                        elif value.lower() == 'false':
                            # Boolean
                            properties[key] = False
                        elif value.isdigit():
                            # Integer
                            properties[key] = int(value)
                        elif re.match(r'^-?\d+(\.\d+)?$', value):
                            # Float
                            properties[key] = float(value)
                        else:
                            # Default to string
                            properties[key] = value
                
                # Create the node
                node = self.db.add_node(Node(labels=labels, properties=properties))
                created_nodes.append(node)
            
            return {"created": len(created_nodes)}
        
        # Handle relationship creation: MATCH (a), (b) CREATE (a)-[:TYPE {props}]->(b)
        rel_pattern = r"MATCH\s+(.*?)\s+CREATE\s+(.*)"
        rel_match = re.search(rel_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if rel_match:
            match_part = rel_match.group(1)
            create_part = rel_match.group(2)
            
            # Execute the MATCH part
            match_result = self._execute_match(f"MATCH {match_part} RETURN *")
            
            # Parse the CREATE part
            create_rel_pattern = r"\((\w+)\)-\[:([\w]+)(\s*{([^}]*)}?)?\]->\((\w+)\)"
            create_rel_match = re.search(create_rel_pattern, create_part)
            
            if create_rel_match:
                from_var = create_rel_match.group(1)
                rel_type = create_rel_match.group(2)
                props_str = create_rel_match.group(4) or ""
                to_var = create_rel_match.group(5)
                
                # Parse relationship properties
                rel_props = {}
                if props_str:
                    prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", props_str)
                    for key, value in prop_items:
                        value = value.strip()
                        if value.startswith("'") and value.endswith("'"):
                            rel_props[key] = value[1:-1]
                        elif value.startswith('"') and value.endswith('"'):
                            rel_props[key] = value[1:-1]
                        elif value.lower() == 'true':
                            rel_props[key] = True
                        elif value.lower() == 'false':
                            rel_props[key] = False
                        elif value.isdigit():
                            rel_props[key] = int(value)
                        elif re.match(r'^-?\d+(\.\d+)?$', value):
                            rel_props[key] = float(value)
                        else:
                            rel_props[key] = value
                
                # Create relationships between matched nodes
                created_rels = []
                
                for row in match_result:
                    if from_var in row and to_var in row:
                        from_node = row[from_var]
                        to_node = row[to_var]
                        
                        rel = Relationship(from_node, to_node, type_=rel_type, properties=rel_props)
                        self.db.add_relationship(rel)
                        created_rels.append(rel)
                
                return {"created_relationships": len(created_rels)}
        
        raise ValueError(f"Invalid CREATE query: {query}")
    
    def _execute_match(self, query):
        """Execute a MATCH query"""
        # Extract the match patterns and return clause
        match_pattern = r"MATCH\s+(.*?)(?:\s+WHERE\s+(.*?))?(?:\s+RETURN\s+(.*?))?(?:\s+LIMIT\s+(\d+))?$"
        match = re.search(match_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if not match:
            raise ValueError(f"Invalid MATCH query: {query}")
        
        patterns = match.group(1)
        where_clause = match.group(2)
        return_clause = match.group(3) or "*"
        limit = int(match.group(4)) if match.group(4) else None
        
        # Check if we need to handle setting properties
        set_pattern = r"MATCH\s+(.*?)(?:\s+WHERE\s+(.*?))?(?:\s+SET\s+(.*?))(?:\s+RETURN\s+(.*?))?(?:\s+LIMIT\s+(\d+))?$"
        set_match = re.search(set_pattern, query, re.IGNORECASE | re.DOTALL)
        
        is_set_query = False
        set_clause = None
        
        if set_match:
            is_set_query = True
            patterns = set_match.group(1)
            where_clause = set_match.group(2)
            set_clause = set_match.group(3)
            return_clause = set_match.group(4) or "*"
            limit = int(set_match.group(5)) if set_match.group(5) else None
        
        # Parse pattern nodes and relationships
        node_pattern = r"\((\w*)((?::\w+)*)(?:\s*{([^}]*)})??\)"
        relationship_pattern = r"\((\w+)\)-\[(\w*)((?::\w+)*)(?:\s*{([^}]*)})??\]->\((\w+)\)"
        
        # Find all node patterns
        node_matches = re.finditer(node_pattern, patterns)
        
        # Track variables
        variable_bindings = {}
        
        # Process each node pattern
        for node_match in node_matches:
            var_name = node_match.group(1)
            if not var_name:
                continue  # Skip unnamed nodes for now
                
            labels = []
            if node_match.group(2):
                labels = [l.strip(':') for l in node_match.group(2).split(':') if l]
            
            properties = {}
            if node_match.group(3):
                prop_str = node_match.group(3)
                prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", prop_str)
                
                for key, value in prop_items:
                    value = value.strip()
                    if value.startswith("'") and value.endswith("'"):
                        properties[key] = value[1:-1]
                    elif value.startswith('"') and value.endswith('"'):
                        properties[key] = value[1:-1]
                    elif value.lower() == 'true':
                        properties[key] = True
                    elif value.lower() == 'false':
                        properties[key] = False
                    elif value.isdigit():
                        properties[key] = int(value)
                    elif re.match(r'^-?\d+(\.\d+)?$', value):
                        properties[key] = float(value)
                    else:
                        properties[key] = value
            
            # Find nodes matching the pattern
            matching_nodes = self.db.find_nodes(labels=labels, properties=properties)
            
            if var_name in variable_bindings:
                # If variable already bound, filter to nodes that match both patterns
                variable_bindings[var_name] = [node for node in variable_bindings[var_name] if node in matching_nodes]
            else:
                variable_bindings[var_name] = matching_nodes
        
        # Find all relationship patterns
        rel_matches = re.finditer(relationship_pattern, patterns)
        
        # Process each relationship pattern
        for rel_match in rel_matches:
            from_var = rel_match.group(1)
            rel_var = rel_match.group(2)
            rel_type = rel_match.group(3).strip(':') if rel_match.group(3) else None
            
            rel_props = {}
            if rel_match.group(4):
                prop_str = rel_match.group(4)
                prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", prop_str)
                
                for key, value in prop_items:
                    value = value.strip()
                    if value.startswith("'") and value.endswith("'"):
                        rel_props[key] = value[1:-1]
                    elif value.startswith('"') and value.endswith('"'):
                        rel_props[key] = value[1:-1]
                    elif value.lower() == 'true':
                        rel_props[key] = True
                    elif value.lower() == 'false':
                        rel_props[key] = False
                    elif value.isdigit():
                        rel_props[key] = int(value)
                    elif re.match(r'^-?\d+(\.\d+)?$', value):
                        rel_props[key] = float(value)
                    else:
                        rel_props[key] = value
            
            to_var = rel_match.group(5)
            
            # Initialize variables if not already bound, but with appropriate constraints
            if from_var not in variable_bindings:
                # Find all source nodes that have relationships of this type
                source_node_ids = set()
                for rel in self.db.find_relationships(type_=rel_type, properties=rel_props):
                    source_node_ids.add(rel.source_id)
                
                # Only include nodes that are sources of this relationship type
                source_nodes = [node for node in self.db.nodes.values() if node.id in source_node_ids]
                variable_bindings[from_var] = source_nodes
            
            if to_var not in variable_bindings:
                # Find all target nodes that have relationships of this type
                target_node_ids = set()
                for rel in self.db.find_relationships(type_=rel_type, properties=rel_props):
                    target_node_ids.add(rel.target_id)
                
                # Only include nodes that are targets of this relationship type
                target_nodes = [node for node in self.db.nodes.values() if node.id in target_node_ids]
                variable_bindings[to_var] = target_nodes
            
            # Find matching paths
            matching_paths = []
            
            # First find all relationships of the specified type
            all_rels_of_type = self.db.find_relationships(type_=rel_type, properties=rel_props)
            
            # Then match them with nodes
            for rel in all_rels_of_type:
                from_node = self.db.nodes.get(rel.source_id)
                to_node = self.db.nodes.get(rel.target_id)
                
                # Check if these nodes match our variable bindings
                if from_node in variable_bindings[from_var] and to_node in variable_bindings[to_var]:
                    if rel_var:
                        matching_paths.append({from_var: from_node, rel_var: rel, to_var: to_node})
                    else:
                        matching_paths.append({from_var: from_node, to_var: to_node})
            
            # Update variable bindings based on relationship matches
            if matching_paths:
                # Create a new set of variable bindings based on the paths
                new_bindings = {}
                
                for var in variable_bindings.keys():
                    new_bindings[var] = []
                
                for path in matching_paths:
                    for var, value in path.items():
                        if var not in new_bindings:
                            new_bindings[var] = []
                        new_bindings[var].append(value)
                
                # Update variable bindings
                for var, values in new_bindings.items():
                    if values:  # Only update if we found matches
                        variable_bindings[var] = values
        
        # Process WHERE clause
        if where_clause:
            # Convert variable bindings to rows for easier filtering
            rows = []
            
            # Get all unique combinations of variable bindings
            if len(variable_bindings) == 1:
                var = list(variable_bindings.keys())[0]
                for value in variable_bindings[var]:
                    rows.append({var: value})
            else:
                # For multiple variables, we need to find valid combinations
                # This is a simplified approach that works for our basic implementation
                # In a real graph DB, this would use more sophisticated pattern matching
                
                # Start with the first variable
                vars_list = list(variable_bindings.keys())
                for value in variable_bindings[vars_list[0]]:
                    rows.append({vars_list[0]: value})
                
                # Add other variables one by one
                for i in range(1, len(vars_list)):
                    var = vars_list[i]
                    new_rows = []
                    
                    for row in rows:
                        for value in variable_bindings[var]:
                            new_row = row.copy()
                            new_row[var] = value
                            new_rows.append(new_row)
                    
                    rows = new_rows
            
            # Apply WHERE filter
            filtered_rows = []
            for row in rows:
                if evaluate_condition(row, where_clause):
                    filtered_rows.append(row)
            
            rows = filtered_rows
            
            # Update variable bindings based on filtered rows
            new_bindings = {}
            for var in variable_bindings.keys():
                new_bindings[var] = []
            
            for row in rows:
                for var, value in row.items():
                    if var not in new_bindings:
                        new_bindings[var] = []
                    if value not in new_bindings[var]:
                        new_bindings[var].append(value)
            
            variable_bindings = new_bindings
        
        # Handle SET clause if present
        if is_set_query and set_clause:
            set_items = set_clause.split(',')
            updated_nodes = 0
            
            for item in set_items:
                item = item.strip()
                assignment_match = re.match(r"(\w+)\.(\w+)\s*=\s*(.+)", item)
                
                if not assignment_match:
                    continue
                
                var_name = assignment_match.group(1)
                prop_name = assignment_match.group(2)
                value_str = assignment_match.group(3).strip()
                
                # Parse the value
                if value_str.startswith("'") and value_str.endswith("'"):
                    value = value_str[1:-1]
                elif value_str.startswith('"') and value_str.endswith('"'):
                    value = value_str[1:-1]
                elif value_str.lower() == 'true':
                    value = True
                elif value_str.lower() == 'false':
                    value = False
                elif value_str.isdigit():
                    value = int(value_str)
                elif re.match(r'^-?\d+(\.\d+)?$', value_str):
                    value = float(value_str)
                else:
                    value = value_str
                
                # Update the properties of matching nodes
                if var_name in variable_bindings:
                    for node in variable_bindings[var_name]:
                        if hasattr(node, 'properties'):  # It's a node
                            node.properties[prop_name] = value
                            updated_nodes += 1
            
            if return_clause == "*":
                return variable_bindings
            
            # Process the RETURN clause
            return_vars = [v.strip() for v in return_clause.split(',')]
            result = []
            
            # Get all combinations of variable bindings
            if len(variable_bindings) == 1:
                var = list(variable_bindings.keys())[0]
                for value in variable_bindings[var]:
                    result.append({var: value})
            else:
                # Similar to what we did for WHERE processing
                vars_list = list(variable_bindings.keys())
                for value in variable_bindings[vars_list[0]]:
                    result.append({vars_list[0]: value})
                
                for i in range(1, len(vars_list)):
                    var = vars_list[i]
                    new_result = []
                    
                    for row in result:
                        for value in variable_bindings[var]:
                            new_row = row.copy()
                            new_row[var] = value
                            new_result.append(new_row)
                    
                    result = new_result
            
            # Apply limit if specified
            if limit is not None and limit < len(result):
                result = result[:limit]
            
            return result
        
        # Process the RETURN clause
        if return_clause == "*":
            # Return all variable bindings
            result_rows = []
            
            # Get all combinations of variable bindings
            if len(variable_bindings) == 1:
                var = list(variable_bindings.keys())[0]
                for value in variable_bindings[var]:
                    result_rows.append({var: value})
            else:
                # Similar to what we did for WHERE processing
                vars_list = list(variable_bindings.keys())
                for value in variable_bindings[vars_list[0]]:
                    result_rows.append({vars_list[0]: value})
                
                for i in range(1, len(vars_list)):
                    var = vars_list[i]
                    new_rows = []
                    
                    for row in result_rows:
                        for value in variable_bindings[var]:
                            new_row = row.copy()
                            new_row[var] = value
                            new_rows.append(new_row)
                    
                    result_rows = new_rows
            
            # Apply limit if specified
            if limit is not None and limit < len(result_rows):
                result_rows = result_rows[:limit]
            
            return result_rows
        else:
            # Return specific variables or expressions
            return_items = [item.strip() for item in return_clause.split(',')]
            result_rows = []
            
            # Get all combinations of variable bindings
            if len(variable_bindings) == 1:
                var = list(variable_bindings.keys())[0]
                for value in variable_bindings[var]:
                    result_rows.append({var: value})
            else:
                # Similar to what we did for WHERE processing
                vars_list = list(variable_bindings.keys())
                if vars_list:
                    for value in variable_bindings[vars_list[0]]:
                        result_rows.append({vars_list[0]: value})
                    
                    for i in range(1, len(vars_list)):
                        var = vars_list[i]
                        new_rows = []
                        
                        for row in result_rows:
                            for value in variable_bindings[var]:
                                new_row = row.copy()
                                new_row[var] = value
                                new_rows.append(new_row)
                        
                        result_rows = new_rows
            
            # Process return items (handle property access)
            processed_rows = []
            
            for row in result_rows:
                processed_row = {}
                
                for item in return_items:
                    # Check if it's a property access (e.g., n.name)
                    prop_access = re.match(r"(\w+)\.(\w+)", item)
                    
                    if prop_access:
                        var_name = prop_access.group(1)
                        prop_name = prop_access.group(2)
                        
                        if var_name in row and hasattr(row[var_name], 'properties'):
                            node = row[var_name]
                            if prop_name in node.properties:
                                processed_row[item] = node.properties[prop_name]
                            else:
                                processed_row[item] = None
                    else:
                        # Just return the variable itself
                        if item in row:
                            processed_row[item] = row[item]
                
                processed_rows.append(processed_row)
            
            # Apply limit if specified
            if limit is not None and limit < len(processed_rows):
                processed_rows = processed_rows[:limit]
            
            return processed_rows
    
    def _execute_delete(self, query):
        """Execute a DELETE query"""
        # Parse DELETE query: MATCH (n) [WHERE ...] DELETE n
        delete_pattern = r"MATCH\s+(.*?)(?:\s+WHERE\s+(.*?))?\s+DELETE\s+(.*?)$"
        delete_match = re.search(delete_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if not delete_match:
            raise ValueError(f"Invalid DELETE query: {query}")
        
        match_pattern = delete_match.group(1)
        where_clause = delete_match.group(2)
        delete_vars = [v.strip() for v in delete_match.group(3).split(',')]
        
        # First, execute a MATCH to find what to delete
        match_query = f"MATCH {match_pattern}"
        if where_clause:
            match_query += f" WHERE {where_clause}"
        match_query += " RETURN " + ", ".join(delete_vars)
        
        match_result = self._execute_match(match_query)
        
        # Delete the matched nodes/relationships
        deleted_nodes = 0
        deleted_rels = 0
        
        for row in match_result:
            for var in delete_vars:
                if var in row:
                    entity = row[var]
                    
                    if hasattr(entity, 'source_id'):  # It's a relationship
                        self.db.delete_relationship(entity.id)
                        deleted_rels += 1
                    else:  # It's a node
                        self.db.delete_node(entity.id)
                        deleted_nodes += 1
        
        return {"deleted_nodes": deleted_nodes, "deleted_relationships": deleted_rels}


# Imports moved to the top of the file
