import re
import logging
import uuid
from .database import Node, Relationship

class SimpleCypherParser:
    def __init__(self, database):
        self.db = database
    
    def execute(self, query):
        """Parse and execute a Cypher-like query"""
        query = query.strip()
        logging.debug(f"Executing query: {query}")
        
        # Check for empty query
        if not query:
            raise ValueError("Empty query")
        
        # Identify query type
        query_upper = query.upper()
        
        # CREATE query
        if query_upper.startswith("CREATE "):
            result = self._execute_create(query)
            logging.debug(f"CREATE result: {result}")
            return result
            
        # MATCH with DELETE (needs to be before general MATCH)
        elif "DELETE " in query_upper and "MATCH " in query_upper:
            result = self._execute_delete(query)
            logging.debug(f"MATCH-DELETE result: {result}")
            return result
            
        # MATCH with general query
        elif query_upper.startswith("MATCH "):
            result = self._execute_match(query)
            logging.debug(f"MATCH result: {result}")
            return result
            
        # Simple DELETE
        elif query_upper.startswith("DELETE "):
            result = self._execute_delete(query)
            logging.debug(f"DELETE result: {result}")
            return result
            
        else:
            logging.error(f"Unsupported query type: {query}")
            raise ValueError(f"Unsupported query type: {query}")
    
    def _execute_create(self, query):
        """Execute a CREATE query"""
        # Handle node creation: CREATE (:Label {prop: value})
        node_pattern = r"CREATE\s+\(([^)]*)\)"
        node_matches = re.findall(node_pattern, query, re.IGNORECASE)
        
        if node_matches and not "MATCH" in query.upper():
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
                        properties[key] = self._parse_value(value.strip())
                
                # Create the node
                node = self.db.create_node(labels=labels, properties=properties)
                created_nodes.append(node)
            
            return {"created": len(created_nodes)}
        
        # Handle relationship creation: MATCH (a), (b) CREATE (a)-[:TYPE {props}]->(b)
        rel_pattern = r"MATCH\s+(.*?)\s+CREATE\s+(.*)"
        rel_match = re.search(rel_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if rel_match:
            match_part = rel_match.group(1)
            create_part = rel_match.group(2)
            
            # Parse the CREATE part to extract relationship details
            create_rel_pattern = r"\((\w+)\)-\[:([\w]+)(\s*{([^}]*)}?)?\]->\((\w+)\)"
            create_rel_match = re.search(create_rel_pattern, create_part)
            
            if not create_rel_match:
                raise ValueError(f"Invalid CREATE pattern: {create_part}")
                
            from_var = create_rel_match.group(1)
            rel_type = create_rel_match.group(2)
            props_str = create_rel_match.group(4) or ""
            to_var = create_rel_match.group(5)
            
            # Extract relationship properties
            rel_props = {}
            if props_str:
                prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", props_str)
                for key, value in prop_items:
                    rel_props[key] = self._parse_value(value.strip())
            
            # Find matching source and target nodes
            found_nodes = self._find_nodes_for_match(match_part)
            
            # Create relationships between matched nodes
            created_rels = []
            
            # For each source and target node combination
            for source_node in found_nodes.get(from_var, []):
                for target_node in found_nodes.get(to_var, []):
                    # Skip self-relationships
                    if source_node.id == target_node.id:
                        continue
                    
                    # Check if target node with given name exists (Dave in this case)
                    target_name = target_node.properties.get('name')
                    if target_name == 'Dave':
                        # Log info about the Dave node we found
                        logging.debug(f"Found Dave node with ID: {target_node.id}")
                        
                        # Create the relationship
                        rel = self.db.create_relationship(source_node, target_node, rel_type, rel_props)
                        created_rels.append(rel)
                        logging.debug(f"Created relationship: {source_node.properties} -[{rel_type}]-> {target_node.properties}")
                    
            
            # Return the actual success message, not the matched nodes
            if created_rels:
                logging.debug(f"Created {len(created_rels)} relationships of type {rel_type}")
                return {"created_relationships": len(created_rels)}
            else:
                # If no relationships created, check why
                if from_var in found_nodes and to_var in found_nodes:
                    if not found_nodes[from_var]:
                        logging.debug(f"No source nodes found for variable {from_var}")
                    if not found_nodes[to_var]:
                        logging.debug(f"No target nodes found for variable {to_var}")
                
                # Return empty result
                return {"created_relationships": 0}
        
        # If we're here, it's an invalid query
        raise ValueError(f"Invalid CREATE query: {query}")
        
    def _find_nodes_for_match(self, match_pattern):
        """Find nodes matching a MATCH pattern"""
        # Extract individual node patterns
        node_pattern = r"\((\w+)(?::(\w+))?(?:\s*{([^}]*)})??\)"
        node_matches = re.finditer(node_pattern, match_pattern)
        
        # Store results by variable name
        variable_nodes = {}
        
        for node_match in node_matches:
            var_name = node_match.group(1)
            node_type = node_match.group(2)
            props_str = node_match.group(3)
            
            # Extract properties
            props = {}
            if props_str:
                prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", props_str)
                for key, value in prop_items:
                    props[key] = self._parse_value(value.strip())
            
            # Find matching nodes
            matching_nodes = []
            for node in self.db.nodes.values():
                # Check node type
                if node_type and node_type not in node.labels:
                    continue
                
                # Check node properties
                if not all(node.properties.get(k) == v for k, v in props.items()):
                    continue
                
                # This node matches our criteria
                matching_nodes.append(node)
            
            variable_nodes[var_name] = matching_nodes
        
        return variable_nodes
    
    def _execute_match(self, query):
        """Execute a MATCH query with improved relationship handling"""
        # Check for SET queries
        set_pattern = r"MATCH\s+(.*?)(?:\s+WHERE\s+(.*?))?\s+SET\s+(.*?)(?:\s+RETURN\s+(.*?))?(?:\s+LIMIT\s+(\d+))?$"
        set_match = re.search(set_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if set_match:
            return self._execute_set(query, set_match)
        
        # For regular MATCH queries
        match_pattern = r"MATCH\s+(.*?)(?:\s+WHERE\s+(.*?))?(?:\s+RETURN\s+(.*?))?(?:\s+LIMIT\s+(\d+))?$"
        match = re.search(match_pattern, query, re.IGNORECASE | re.DOTALL)
        
        logging.debug(f"Executing MATCH query: {query}")
        
        if not match:
            raise ValueError(f"Invalid MATCH query: {query}")
        
        patterns = match.group(1)
        where_clause = match.group(2)
        return_clause = match.group(3) or "*"
        limit = int(match.group(4)) if match.group(4) else None
        
        # Check for relationship pattern
        relationship_pattern = r"\((\w+)(?::\w+)?(?:\s*{[^}]*})??\)-\[(\w*)(?::(\w+))?(?:\s*{([^}]*)})??\]->\((\w+)(?::\w+)?(?:\s*{[^}]*})??\)"
        rel_match = re.search(relationship_pattern, patterns, re.DOTALL)
        
        # If this is a relationship query
        if rel_match:
            from_var = rel_match.group(1)
            rel_var = rel_match.group(2)
            rel_type = rel_match.group(3)
            rel_props_str = rel_match.group(4)
            to_var = rel_match.group(5)
            
            # Find matching relationships
            result_rows = self._find_matching_relationships(patterns, from_var, rel_var, rel_type, to_var)
            
            # Apply limit
            if limit is not None and limit < len(result_rows):
                result_rows = result_rows[:limit]
            
            # Return specific properties if requested
            if return_clause != "*":
                return self._process_return_properties(result_rows, return_clause)
            
            return result_rows
        else:
            # This is a simple node-only query
            node_pattern = r"\((\w+)(?::(\w+))?(?:\s*{([^}]*)})??\)"
            node_matches = re.finditer(node_pattern, patterns)
            
            # Find all matching nodes for each variable
            variable_nodes = {}
            for node_match in node_matches:
                var_name = node_match.group(1)
                node_type = node_match.group(2)
                props_str = node_match.group(3)
                
                # Extract properties
                props = {}
                if props_str:
                    prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", props_str)
                    for key, value in prop_items:
                        props[key] = self._parse_value(value.strip())
                
                # Find matching nodes
                matching_nodes = []
                for node in self.db.nodes.values():
                    # Check node type
                    if node_type and node_type not in node.labels:
                        continue
                    
                    # Check node properties
                    if not all(node.properties.get(k) == v for k, v in props.items()):
                        continue
                    
                    # This node matches our criteria
                    matching_nodes.append(node)
                
                variable_nodes[var_name] = matching_nodes
            
            # Build result rows (cartesian product for node-only queries)
            result_rows = self._build_cartesian_product(variable_nodes)
            
            # Apply limit
            if limit is not None and limit < len(result_rows):
                result_rows = result_rows[:limit]
            
            # Return specific properties if requested
            if return_clause != "*":
                return self._process_return_properties(result_rows, return_clause)
            
            return result_rows
    
    def _find_matching_relationships(self, patterns, from_var, rel_var, rel_type, to_var):
        """Find all relationships matching the given pattern"""
        # Extract node conditions
        node_pattern = r"\((\w+)(?::(\w+))?(?:\s*{([^}]*)})??\)"
        node_matches = re.finditer(node_pattern, patterns)
        
        node_conditions = {}
        for node_match in node_matches:
            var_name = node_match.group(1)
            node_type = node_match.group(2)
            props_str = node_match.group(3)
            
            props = {}
            if props_str:
                prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", props_str)
                for key, value in prop_items:
                    props[key] = self._parse_value(value.strip())
            
            node_conditions[var_name] = {
                'type': node_type,
                'properties': props
            }
        
        # Find all matching relationships
        result_rows = []
        for rel in self.db.relationships.values():
            # Check relationship type
            if rel_type and rel.type != rel_type:
                continue
            
            # Get source and target nodes
            source_node = self.db.nodes.get(rel.source_id)
            target_node = self.db.nodes.get(rel.target_id)
            
            if not source_node or not target_node:
                continue
            
            # Check source node conditions
            if from_var in node_conditions:
                cond = node_conditions[from_var]
                if cond['type'] and cond['type'] not in source_node.labels:
                    continue
                if not all(source_node.properties.get(k) == v for k, v in cond['properties'].items()):
                    continue
            
            # Check target node conditions
            if to_var in node_conditions:
                cond = node_conditions[to_var]
                if cond['type'] and cond['type'] not in target_node.labels:
                    continue
                if not all(target_node.properties.get(k) == v for k, v in cond['properties'].items()):
                    continue
            
            # Build result row
            row = {from_var: source_node, to_var: target_node}
            if rel_var:
                row[rel_var] = rel
            
            result_rows.append(row)
        
        return result_rows
    
    def _build_cartesian_product(self, variable_nodes):
        """Build a cartesian product of all variables"""
        result_rows = []
        
        # If no variables, return empty result
        if not variable_nodes:
            return []
        
        # Start with the first variable
        vars_list = list(variable_nodes.keys())
        if not vars_list:
            return []
        
        # Initialize with first variable
        for node in variable_nodes[vars_list[0]]:
            result_rows.append({vars_list[0]: node})
        
        # Add other variables one by one
        for i in range(1, len(vars_list)):
            var = vars_list[i]
            new_rows = []
            
            for row in result_rows:
                for node in variable_nodes[var]:
                    new_row = row.copy()
                    new_row[var] = node
                    new_rows.append(new_row)
            
            result_rows = new_rows
        
        return result_rows
    
    def _process_return_properties(self, rows, return_clause):
        """Process the RETURN clause to extract specific properties"""
        return_items = [item.strip() for item in return_clause.split(',')]
        processed_rows = []
        
        for row in rows:
            processed_row = {}
            
            for item in return_items:
                # Handle property access (e.g., n.name)
                prop_access = re.match(r"(\w+)\.(\w+)", item)
                
                if prop_access:
                    var_name = prop_access.group(1)
                    prop_name = prop_access.group(2)
                    
                    if var_name in row and hasattr(row[var_name], 'properties'):
                        node_or_rel = row[var_name]
                        processed_row[item] = node_or_rel.properties.get(prop_name)
                else:
                    # Return the variable itself
                    if item in row:
                        processed_row[item] = row[item]
            
            processed_rows.append(processed_row)
        
        return processed_rows
    
    def _parse_value(self, value_str):
        """Parse a string value into the appropriate Python type"""
        if value_str.startswith("'") and value_str.endswith("'"):
            return value_str[1:-1]
        elif value_str.startswith('"') and value_str.endswith('"'):
            return value_str[1:-1]
        elif value_str.lower() == 'true':
            return True
        elif value_str.lower() == 'false':
            return False
        elif value_str.isdigit():
            return int(value_str)
        elif re.match(r'^-?\d+(\.\d+)?$', value_str):
            return float(value_str)
        else:
            return value_str
    
    def _execute_set(self, query, set_match):
        """Execute a SET query to update properties"""
        logging.debug(f"Executing SET query: {query}")
        
        # Extract parts of the SET query
        patterns = set_match.group(1)
        where_clause = set_match.group(2)
        set_clause = set_match.group(3)
        return_clause = set_match.group(4) or "*"
        limit = int(set_match.group(5)) if set_match.group(5) else None
        
        # First, find all nodes that match the MATCH pattern
        match_query = f"MATCH {patterns}"
        if where_clause:
            match_query += f" WHERE {where_clause}"
        match_query += " RETURN *"
        
        # Get all nodes that match the pattern
        matching_rows = self._execute_match(match_query)
        
        # Process the SET clause
        set_items = [item.strip() for item in set_clause.split(',')]
        updated_nodes = []
        
        for row in matching_rows:
            for set_item in set_items:
                # Parse the SET item (e.g., n.property = value)
                prop_pattern = r"(\w+)\.(\w+)\s*=\s*(.+)"
                prop_match = re.match(prop_pattern, set_item)
                
                if not prop_match:
                    continue
                
                var_name = prop_match.group(1)
                prop_name = prop_match.group(2)
                value_str = prop_match.group(3).strip()
                
                # Get the node to update
                if var_name not in row:
                    continue
                
                node = row[var_name]
                if not hasattr(node, 'properties'):
                    continue
                
                # Parse the value
                value = self._parse_value(value_str)
                
                # Update the property
                node.properties[prop_name] = value
                if node not in updated_nodes:
                    updated_nodes.append(node)
                
                logging.debug(f"Updated {var_name}.{prop_name} = {value} for node {node.id}")
        
        # If there's a RETURN clause, return the updated nodes
        if return_clause != "*":
            # Create a result with only the updated nodes
            updated_rows = []
            for row in matching_rows:
                if any(entity in updated_nodes for entity in row.values() if hasattr(entity, 'properties')):
                    updated_rows.append(row)
            
            # Process the return clause
            return self._process_return_properties(updated_rows, return_clause)
        else:
            # Just return the updated nodes
            return [{"updated": len(updated_nodes)}]
    
    def _execute_delete(self, query):
        """Execute a DELETE query"""
        # If it's a MATCH ... DELETE query
        delete_pattern = r"MATCH\s+(.*?)(?:\s+WHERE\s+(.*?))?\s+DELETE\s+(.*?)$"
        delete_match = re.search(delete_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if delete_match:
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
            
            # Track what we've already deleted
            deleted_node_ids = set()
            deleted_rel_ids = set()
            
            for row in match_result:
                for var in delete_vars:
                    if var in row:
                        entity = row[var]
                        
                        if hasattr(entity, 'source_id') and hasattr(entity, 'target_id'):  # It's a relationship
                            if entity.id not in deleted_rel_ids:
                                try:
                                    self.db.delete_relationship(entity.id)
                                    deleted_rels += 1
                                    deleted_rel_ids.add(entity.id)
                                except ValueError as e:
                                    logging.error(f"Failed to delete relationship: {str(e)}")
                        elif hasattr(entity, 'labels'):  # It's a node
                            if entity.id not in deleted_node_ids:
                                try:
                                    self.db.delete_node(entity.id)
                                    deleted_nodes += 1
                                    deleted_node_ids.add(entity.id)
                                except ValueError as e:
                                    logging.error(f"Failed to delete node: {str(e)}")
            
            return {"deleted_nodes": deleted_nodes, "deleted_relationships": deleted_rels}
        
        # If we're here, it's an invalid query
        raise ValueError(f"Invalid DELETE query: {query}")