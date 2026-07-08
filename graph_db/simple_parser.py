import re
import logging
import uuid
from .database import Node, Relationship
from .transaction import Transaction, TransactionError
from .cypher import evaluate_condition
import ast

class SimpleCypherParser:
    def __init__(self, database):
        self.db = database
        self.transaction = Transaction(database)
        self.active_transaction = False
    
    def execute(self, query): 
        query = query.strip()
        logging.debug(f"Executing query: {query}")
        
        if not query:
            raise ValueError("Empty query")
        
        query_upper = query.upper()
        
        # Transaction commands must be standalone
        if query_upper.startswith("BEGIN"):
            if self.active_transaction:
                raise TransactionError("Transaction already in progress")
            return self._begin_transaction()
        elif query_upper.startswith("COMMIT"):
            if not self.active_transaction:
                raise TransactionError("No active transaction to commit")
            return self._commit_transaction()
        elif query_upper.startswith("ROLLBACK"):
            if not self.active_transaction:
                raise TransactionError("No active transaction to rollback")
            return self._rollback_transaction()
        
        # All other operations require an active transaction
        if not self.active_transaction:
            raise TransactionError("No active transaction. Use BEGIN to start a transaction")
        
        try:
            # Schema operations
            if query_upper.startswith("CREATE CONSTRAINT"):
                return self._execute_create_constraint(query)
            elif query_upper.startswith("DROP CONSTRAINT"):
                return self._execute_drop_constraint(query)
            elif query_upper.startswith("CREATE INDEX"):
                return self._execute_create_index(query)
            elif query_upper.startswith("DROP INDEX"):
                return self._execute_drop_index(query)
            
            # Data operations
            elif query_upper.startswith("CREATE "):
                return self._execute_create(query)
            elif "DELETE " in query_upper and "MATCH " in query_upper:
                return self._execute_delete(query)
            elif query_upper.startswith("MATCH "):
                if "CREATE" in query_upper:
                    return self._execute_create(query)
                else:
                    return self._execute_match(query)
            elif query_upper.startswith("DELETE "):
                return self._execute_delete(query)
            else:
                raise ValueError(f"Unsupported query type: {query}")
        except Exception as e:
            # On error, rollback the transaction
            self._rollback_transaction()
            raise e

    def _begin_transaction(self):
        """Begin a new transaction"""
        self.transaction.begin()
        self.active_transaction = True
        return [{"success": "Transaction started"}]
    
    def _commit_transaction(self):
        """Commit the current transaction"""
        result = self.transaction.commit()
        self.active_transaction = False
        return [{"success": "Transaction committed"}]
    
    def _rollback_transaction(self):
        """Rollback the current transaction"""
        result = self.transaction.rollback()
        self.active_transaction = False
        return [{"success": "Transaction rolled back"}]
    
    def _execute_create_constraint(self, query):
        """Execute a CREATE CONSTRAINT query"""
        constraint_pattern = r"CREATE\s+CONSTRAINT\s+ON\s+\((\w+):(\w+)\)\s+ASSERT\s+\1\.(\w+)\s+IS\s+UNIQUE"
        constraint_match = re.search(constraint_pattern, query, re.IGNORECASE)
        
        if not constraint_match:
            raise ValueError("Invalid constraint syntax. Expected: CREATE CONSTRAINT ON (n:Label) ASSERT n.property IS UNIQUE")
        
        label = constraint_match.group(2)
        property_name = constraint_match.group(3)
        
        try:
            self.transaction.log_operation("CREATE_CONSTRAINT", {
                "label": label,
                "property": property_name,
                "type": "UNIQUE"
            })
            
            return [{"success": f"Added unique constraint on {label}.{property_name}"}]
        except Exception as e:
            raise TransactionError(f"Failed to create constraint: {str(e)}")

    def _execute_drop_constraint(self, query):
        """Execute a DROP CONSTRAINT query"""
        constraint_pattern = r"DROP\s+CONSTRAINT\s+ON\s+\((\w+):(\w+)\)\s+ASSERT\s+\1\.(\w+)\s+IS\s+UNIQUE"
        constraint_match = re.search(constraint_pattern, query, re.IGNORECASE)
        
        if not constraint_match:
            raise ValueError("Invalid constraint syntax. Expected: DROP CONSTRAINT ON (n:Label) ASSERT n.property IS UNIQUE")
        
        label = constraint_match.group(2)
        property_name = constraint_match.group(3)
        
        try:
            # Check if constraint exists
            exists = (label, property_name) in self.db.constraints.get('unique', [])
            
            self.transaction.log_operation("DROP_CONSTRAINT", {
                "label": label,
                "property": property_name,
                "type": "UNIQUE"
            })
            
            if exists:
                return [{"success": f"Dropped unique constraint on {label}.{property_name}"}]
            else:
                return [{"message": f"No constraint found on {label}.{property_name}"}]
        except Exception as e:
            raise TransactionError(f"Failed to drop constraint: {str(e)}")

    def _execute_create_index(self, query):
        """Execute a CREATE INDEX query"""
        index_pattern = r"CREATE\s+INDEX\s+ON\s+:(\w+)\((\w+)\)"
        index_match = re.search(index_pattern, query, re.IGNORECASE)
        
        if not index_match:
            raise ValueError("Invalid index syntax. Expected: CREATE INDEX ON :Label(property)")
        
        label = index_match.group(1)
        property_name = index_match.group(2)
        
        try:
            exists = (label, property_name) in self.db.indexed_properties
            
            self.transaction.log_operation("CREATE_INDEX", {
                "label": label,
                "property": property_name
            })
            
            if exists:
                return [{"message": f"Index on {label}.{property_name} already exists"}]
            else:
                return [{"success": f"Created index on {label}.{property_name}"}]
        except Exception as e:
            raise TransactionError(f"Failed to create index: {str(e)}")

    def _execute_drop_index(self, query):
        """Execute a DROP INDEX query"""
        index_pattern = r"DROP\s+INDEX\s+ON\s+:(\w+)\((\w+)\)"
        index_match = re.search(index_pattern, query, re.IGNORECASE)
        
        if not index_match:
            raise ValueError("Invalid index syntax. Expected: DROP INDEX ON :Label(property)")
        
        label = index_match.group(1)
        property_name = index_match.group(2)
        
        try:
            exists = (label, property_name) in self.db.indexed_properties
            
            self.transaction.log_operation("DROP_INDEX", {
                "label": label,
                "property": property_name
            })
            
            if exists:
                return [{"success": f"Dropped index on {label}.{property_name}"}]
            else:
                return [{"message": f"No index found on {label}.{property_name}"}]
        except Exception as e:
            raise TransactionError(f"Failed to drop index: {str(e)}")

    def _execute_create(self, query):
        """Execute a CREATE query within a transaction"""
        # Handle direct node-relationship-node creation: CREATE (a:Label)-[:TYPE]->(b:Label)
        direct_rel_pattern = r"CREATE\s+\(([^)]*)\)-\[(?:[^:]*):(\w+)(?:\s*{([^}]*)}?)?\]->\(([^)]*)\)"
        direct_rel_match = re.search(direct_rel_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if direct_rel_match and not "MATCH" in query.upper():
            # Extract the pattern components
            from_node_str = direct_rel_match.group(1)
            rel_type = direct_rel_match.group(2)
            rel_props_str = direct_rel_match.group(3) or ""
            to_node_str = direct_rel_match.group(4)
            
            logging.debug(f"Direct relationship creation: {from_node_str} -[:{rel_type}]-> {to_node_str}")
            
            # Parse source node labels and properties
            from_labels = []
            from_label_pattern = r":(\w+)"
            from_label_matches = re.findall(from_label_pattern, from_node_str)
            from_labels.extend(from_label_matches)
            
            from_properties = {}
            from_prop_pattern = r"{([^}]*)}"
            from_prop_matches = re.findall(from_prop_pattern, from_node_str)
            
            if from_prop_matches:
                from_prop_str = from_prop_matches[0]
                from_prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", from_prop_str)
                for key, value in from_prop_items:
                    from_properties[key] = self._parse_value(value.strip())
            
            # Parse target node labels and properties
            to_labels = []
            to_label_pattern = r":(\w+)"
            to_label_matches = re.findall(to_label_pattern, to_node_str)
            to_labels.extend(to_label_matches)
            
            to_properties = {}
            to_prop_pattern = r"{([^}]*)}"
            to_prop_matches = re.findall(to_prop_pattern, to_node_str)
            
            if to_prop_matches:
                to_prop_str = to_prop_matches[0]
                to_prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", to_prop_str)
                for key, value in to_prop_items:
                    to_properties[key] = self._parse_value(value.strip())
            
            # Parse relationship properties
            rel_props = {}
            if rel_props_str:
                rel_prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", rel_props_str)
                for key, value in rel_prop_items:
                    rel_props[key] = self._parse_value(value.strip())
            
            source_id = str(uuid.uuid4())
            target_id = str(uuid.uuid4())
            
            self.transaction.log_operation("CREATE_NODE", {
                "node_id": source_id,
                "labels": list(from_labels),
                "properties": from_properties
            })

            self.transaction.log_operation("CREATE_NODE", {
                "node_id": target_id,
                "labels": list(to_labels),
                "properties": to_properties
            })

            self.transaction.log_operation("CREATE_RELATIONSHIP", {
                "relationship_id": str(uuid.uuid4()),
                "source_id": source_id,
                "target_id": target_id,
                "type": rel_type,
                "properties": rel_props
            })

            logging.debug(f"Deferred creation of relationship: ({source_id})-[:{rel_type}]->({target_id})")

            return {"created": 1}
            
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
                    prop_str = prop_matches[0]
                    prop_items = re.findall(r"(\w+)\s*:\s*([^,]+)", prop_str)
                    for key, value in prop_items:
                        properties[key] = self._parse_value(value.strip())
                
                # Generate ID and log operation
                node_id = str(uuid.uuid4())
                self.transaction.log_operation("CREATE_NODE", {
                    "node_id": node_id,
                    "labels": list(labels),
                    "properties": properties
                })
                created_nodes.append(node_id)
                
            return {"created": len(created_nodes)}
        
        # Handle relationship creation: MATCH (a), (b) CREATE (a)-[:TYPE {props}]->(b)
        rel_pattern = r"MATCH\s+(.*?)\s+CREATE\s+(.*)"
        rel_match = re.search(rel_pattern, query, re.IGNORECASE | re.DOTALL)
        
        if rel_match:
            match_part = rel_match.group(1)
            create_part = rel_match.group(2)
            
            # Parse the CREATE part to extract relationship details
            create_rel_pattern = r"\((\w+)\)-\[(?:\w+)?:([\w]+)(\s*{([^}]*)}?)?\]->\((\w+)\)"
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
            
            # Find source and target nodes
            variable_nodes = self._find_nodes_for_match(match_part)
            
            if from_var not in variable_nodes or to_var not in variable_nodes:
                return [{"message": "No matching nodes found for relationship creation"}]
            
            src_nodes = variable_nodes[from_var]
            dst_nodes = variable_nodes[to_var]
            
            # Create relationships between matched nodes
            created_rels = []
            
            for source_node in src_nodes:
                for target_node in dst_nodes:
                    if source_node.id == target_node.id:
                        continue
                    
                    rel_id = str(uuid.uuid4())
                    self.transaction.log_operation("CREATE_RELATIONSHIP", {
                        "relationship_id": rel_id,
                        "source_id": source_node.id,
                        "target_id": target_node.id,
                        "type": rel_type,
                        "properties": rel_props
                    })
                    created_rels.append(rel_id)
            
            if created_rels:
                return [{"success": f"Created {len(created_rels)} relationships"}]
            else:
                return [{"message": "No relationships created"}]
        
        raise ValueError(f"Invalid CREATE query: {query}")

    # ... [rest of the methods remain unchanged] ...
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
            
            # Debug logging
            logging.debug(f"Looking for {var_name} with props: {props}")
            
            # Find matching nodes - Check if we can use an index for optimization
            matching_nodes = []
            
            # Check if we can use an index for this query
            if node_type and len(props) == 1:
                # Only one property and we have a label - check if it's indexed
                prop_name, prop_value = next(iter(props.items()))
                if (node_type, prop_name) in self.db.indexed_properties:
                    # Use the index for faster lookup
                    logging.debug(f"Using index on {node_type}.{prop_name} for efficient lookup")
                    matching_nodes = self.db.find_nodes_by_index(node_type, prop_name, prop_value)
                    variable_nodes[var_name] = matching_nodes
                    
                    # Extra debug info
                    if not matching_nodes:
                        logging.debug(f"No nodes found using index on {node_type}.{prop_name}")
                    else:
                        logging.debug(f"Found {len(matching_nodes)} nodes using index")
                    
                    continue  # Skip the full scan for this variable
            
            # If we can't use an index or need to check multiple properties, do a full scan
            for node in self.db.nodes.values():
                # Check node type
                if node_type and node_type not in node.labels:
                    continue
                
                # Check node properties
                props_match = True
                for k, v in props.items():
                    node_value = node.properties.get(k)
                    if node_value != v:
                        props_match = False
                        break
                
                if not props_match:
                    continue
                
                # This node matches our criteria
                matching_nodes.append(node)
                logging.debug(f"Found matching node: {node.properties}")
            
            variable_nodes[var_name] = matching_nodes
            
            # Extra debug info
            if not matching_nodes:
                logging.debug(f"No nodes found matching {var_name} with props: {props}")
            else:
                logging.debug(f"Found {len(matching_nodes)} nodes for {var_name}")
        
        # Further debug info
        for var, nodes in variable_nodes.items():
            logging.debug(f"Variable {var} has {len(nodes)} matching nodes")
            for node in nodes:
                logging.debug(f"  Node: {node.properties}")
        
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
            
            # Apply WHERE clause filtering if present
            if where_clause:
                filtered_rows = []
                for row in result_rows:
                    if evaluate_condition(row, where_clause):
                        filtered_rows.append(row)
                result_rows = filtered_rows
                logging.debug(f"Applied WHERE filter: {where_clause}. Rows after filtering: {len(result_rows)}")
            
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
                
                # Find matching nodes - Check if we can use an index for optimization
                matching_nodes = []
                
                # Check if we can use an index for this query
                if node_type and len(props) == 1:
                    # Only one property and we have a label - check if it's indexed
                    prop_name, prop_value = next(iter(props.items()))
                    if (node_type, prop_name) in self.db.indexed_properties:
                        # Use the index for faster lookup
                        logging.debug(f"Using index on {node_type}.{prop_name} for efficient lookup")
                        matching_nodes = self.db.find_nodes_by_index(node_type, prop_name, prop_value)
                        variable_nodes[var_name] = matching_nodes
                        continue
                
                # If we can't use an index, do a full scan
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
            
            # Apply WHERE clause filtering if present
            if where_clause:
                filtered_rows = []
                for row in result_rows:
                    if evaluate_condition(row, where_clause):
                        filtered_rows.append(row)
                result_rows = filtered_rows
                logging.debug(f"Applied WHERE filter: {where_clause}. Rows after filtering: {len(result_rows)}")
            
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
        elif value_str.lower() == 'null':
            return None
        else:
            try:
                if '.' in value_str:
                    return float(value_str)
                else:
                    return int(value_str)
            except ValueError:
                return value_str
    
    def _execute_set(self, query, set_match):
        """Execute a SET query to update properties"""
        match_part = set_match.group(1)
        where_clause = set_match.group(2)
        set_clause = set_match.group(3)
        return_clause = set_match.group(4)
        
        # Find matching nodes
        variable_nodes = self._find_nodes_for_match(match_part)
        
        # Extract the node variable and properties to set
        set_pattern = r"(\w+)\.(\w+)\s*=\s*([^,]+)"
        set_matches = re.findall(set_pattern, set_clause)
        
        if not set_matches:
            raise ValueError(f"Invalid SET clause: {set_clause}")
        
        # Group property assignments by variable
        updates_by_var = {}
        for var_name, prop_name, prop_value in set_matches:
            if var_name not in updates_by_var:
                updates_by_var[var_name] = {}
            
            updates_by_var[var_name][prop_name] = self._parse_value(prop_value.strip())
        
        # Apply updates
        updated_nodes = []
        for var_name, props in updates_by_var.items():
            if var_name not in variable_nodes:
                continue
            
            for node in variable_nodes[var_name]:
                # Apply property updates
                for prop_name, prop_value in props.items():
                    node.properties[prop_name] = prop_value
                
                updated_nodes.append(node)
                
                # Log operation if in transaction
                if self.active_transaction:
                    self.transaction.log_operation("UPDATE_NODE", {
                        "node_id": node.id,
                        "properties": props
                    })
        
        # Return updated nodes if requested
        if return_clause:
            result_rows = []
            for var_name in variable_nodes:
                for node in variable_nodes[var_name]:
                    result_rows.append({var_name: node})
            
            if return_clause != "*":
                return self._process_return_properties(result_rows, return_clause)
            
            return result_rows
        
        return {"updated": len(updated_nodes)}
    
    def _execute_delete(self, query):
        """Execute a DELETE query"""
        # Check if it's a MATCH...DELETE query
        if "MATCH " in query.upper():
            match_pattern = r"MATCH\s+(.*?)(?:\s+WHERE\s+(.*?))?\s+DELETE\s+(.*?)$"
            match = re.search(match_pattern, query, re.IGNORECASE | re.DOTALL)
            
            if not match:
                raise ValueError(f"Invalid MATCH DELETE query: {query}")
            
            match_part = match.group(1)
            where_clause = match.group(2)
            delete_items = match.group(3).split(',')
            delete_items = [item.strip() for item in delete_items]
            
            # Find matching nodes
            variable_nodes = self._find_nodes_for_match(match_part)
            
            # Collect nodes and relationships to delete
            deleted_node_count = 0
            deleted_rel_count = 0
            
            for item in delete_items:
                if item in variable_nodes:
                    for node in variable_nodes[item]:
                        # Check if this node should be deleted
                        # First, we need to delete all relationships involving this node
                        related_rels = []
                        for rel_id, rel in self.db.relationships.items():
                            if rel.source_id == node.id or rel.target_id == node.id:
                                related_rels.append(rel_id)
                        
                        # Delete the relationships
                        for rel_id in related_rels:
                            del self.db.relationships[rel_id]
                            deleted_rel_count += 1
                            
                            # Log operation if in transaction
                            if self.active_transaction:
                                self.transaction.log_operation("DELETE_RELATIONSHIP", {
                                    "relationship_id": rel_id
                                })
                        
                        # Now delete the node
                        del self.db.nodes[node.id]
                        deleted_node_count += 1
                        
                        # Log operation if in transaction
                        if self.active_transaction:
                            self.transaction.log_operation("DELETE_NODE", {
                                "node_id": node.id
                            })
            
            return {"deleted_nodes": deleted_node_count, "deleted_relationships": deleted_rel_count}
        else:
            # Simple DELETE, directly targeting node IDs
            raise ValueError("Direct DELETE without MATCH not supported yet")