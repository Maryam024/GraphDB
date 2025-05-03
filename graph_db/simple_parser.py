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
            
            # Execute a simple match to find the nodes
            match_query = f"MATCH {match_part} RETURN {from_var}, {to_var}"
            match_result = self._execute_match(match_query)
            
            # Parse relationship properties
            rel_props = {}
            if props_str:
                prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", props_str)
                for key, value in prop_items:
                    rel_props[key] = self._parse_value(value.strip())
            
            # Create relationships between matched nodes
            created_rels = []
            
            # Process each match and create the relationship
            for row in match_result:
                if from_var not in row or to_var not in row:
                    continue
                    
                from_node = row[from_var]
                to_node = row[to_var]
                
                # Skip self-relationships
                if from_node.id == to_node.id:
                    continue
                
                # Create relationship
                rel = self.db.create_relationship(from_node, to_node, rel_type, rel_props)
                created_rels.append(rel)
            
            return {"created_relationships": len(created_rels)}
        
        # If we're here, it's an invalid query
        raise ValueError(f"Invalid CREATE query: {query}")
    
    def _execute_match(self, query):
        """Execute a MATCH query with improved relationship handling"""
        # Extract the match patterns and return clause
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