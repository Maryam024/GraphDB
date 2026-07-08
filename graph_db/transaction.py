import logging
import json
import os
import copy
import threading
import time
from .database import GraphDatabase
import uuid
from .models import Node, Relationship  # Adjust the import path based on your project structure


# Global transaction lock for concurrency control
transaction_lock = threading.RLock()
# Global lock for database file I/O operations
db_file_lock = threading.RLock()

class TransactionError(Exception):
    """Base exception for transaction errors"""
    pass

class ConcurrencyError(TransactionError):
    """Exception raised when concurrent operations conflict"""
    pass

class DeadlockError(TransactionError):
    """Exception raised when a deadlock situation is detected"""
    pass

class ConstraintViolationError(TransactionError):
    """Exception raised when a constraint is violated"""
    pass

class Transaction:
   
    active_transactions = {}
    tx_id_counter = 0
    tx_counter_lock = threading.Lock()
    
    @classmethod
    def get_next_tx_id(cls):
        """Get a unique transaction ID"""
        with cls.tx_counter_lock:
            cls.tx_id_counter += 1
            return cls.tx_id_counter
    
    def __init__(self, graph_db):
        """Initialize a new transaction"""
        self.db = graph_db
        self.snapshot = None
        self.is_active = False
        self.log = []
        self.tx_id = None
        self.modified_nodes = set()  # Track modified nodes for conflict detection
        self.modified_rels = set()   # Track modified relationships
        
    def begin(self):
        """Start a new transaction by taking a snapshot of the current state"""
        # Use a lock to ensure thread safety
        with transaction_lock:
            if self.is_active:
                raise TransactionError("Transaction already in progress")
            
            # Generate transaction ID
            self.tx_id = self.get_next_tx_id()
            
            # Create a deep copy of the database state (for Atomicity)
            self.snapshot = {
                "nodes": copy.deepcopy(self.db.nodes),
                "relationships": copy.deepcopy(self.db.relationships),
                "constraints": copy.deepcopy(self.db.constraints)
            }
            
            self.is_active = True
            self.log = []
            Transaction.active_transactions[self.tx_id] = time.time()
            logging.debug(f"Transaction {self.tx_id} started")
            return True
    
    def log_operation(self, operation, details):
        """Log an operation to be performed when the transaction commits"""
        if not self.is_active:
            raise TransactionError("Cannot perform operations outside of an active transaction")
            
        # Validate operation types
        valid_operations = {
            'CREATE_NODE', 'DELETE_NODE', 'UPDATE_NODE',
            'CREATE_RELATIONSHIP', 'DELETE_RELATIONSHIP', 'UPDATE_RELATIONSHIP',
            'CREATE_CONSTRAINT', 'DROP_CONSTRAINT',
            'CREATE_INDEX', 'DROP_INDEX'
        }
        if operation not in valid_operations:
            raise TransactionError(f"Invalid operation type: {operation}")
            
        # Check constraints for relevant operations
        if operation in ('CREATE_NODE', 'UPDATE_NODE'):
            if not self._check_constraints(details):
                raise ConstraintViolationError("Operation would violate constraints")
        
        # Check for uniqueness violations
        if operation == 'CREATE_CONSTRAINT':
            self._validate_constraint_creation(details.get('label'), details.get('property'))
        
        self.log.append({"operation": operation, "details": details})
        
    def commit(self):
        """Commit the transaction by applying all logged operations"""
        with transaction_lock:
            if not self.is_active:
                raise TransactionError("No active transaction to commit")
                
            try:
                # Apply all operations in order
                self._apply_operations()
                
                # Persist to disk
                self._save_database_to_disk()
                
                # Clear transaction state
                self._cleanup()
                
                return {"status": "success", "message": "Transaction committed"}
                
            except Exception as e:
                # On any error, rollback and re-raise
                self._cleanup()
                raise e
                
    def rollback(self):
        """Rollback the transaction by discarding all changes"""
        with transaction_lock:
            if not self.is_active:
                raise TransactionError("No active transaction to rollback")
                
            try:
                # Restore from snapshot
                if self.snapshot:
                    self.db.nodes = self.snapshot["nodes"]
                    self.db.relationships = self.snapshot["relationships"]
                    self.db.constraints = self.snapshot["constraints"]
                    self.db.indexed_properties = self.snapshot.get("indexed_properties", [])
                    self.db.indexes = self.snapshot.get("indexes", {})
                
                # Clear transaction state
                self._cleanup()
                
                return {"status": "success", "message": "Transaction rolled back"}
                
            except Exception as e:
                logging.error(f"Error during rollback: {str(e)}")
                self._cleanup()
                raise TransactionError("Failed to rollback transaction")
    
    def _cleanup(self):
        """Clean up transaction state"""
        self.is_active = False
        self.log = []
        self.tx_id = None
        self.snapshot = None
        if self.tx_id in Transaction.active_transactions:
            del Transaction.active_transactions[self.tx_id]
    def _check_constraints(self, details):
        """Verify that an operation doesn't violate constraints"""
        # For node creation/update, check uniqueness constraints
        if 'labels' in details and 'properties' in details:
            labels = details['labels']
            props = details['properties']
            
            for label, prop_name in self.db.constraints.get('unique', []):
                if label in labels and prop_name in props:
                    # Check all nodes (except the one being updated) for uniqueness violations
                    value = props[prop_name]
                    for node_id, node in self.db.nodes.items():
                        if (node_id != details.get('node_id') and  # Skip the node itself if updating
                            label in node.labels and 
                            prop_name in node.properties and
                            node.properties[prop_name] == value):
                            logging.error(f"Constraint violation: {label}.{prop_name}='{value}' already exists")
                            return False
        return True
        
    def _validate_constraint_creation(self, label, property_name):
        """Validate that a constraint can be created without violating data integrity"""
        # Validate existing data to ensure no duplicates would violate the constraint
        property_values = {}
        duplicates = []
        
        for node in self.db.nodes.values():
            if label in node.labels and property_name in node.properties:
                value = node.properties[property_name]
                if value in property_values:
                    duplicates.append((value, node.id, property_values[value]))
                property_values[value] = node.id
        
        # If duplicates found, provide detailed error
        if duplicates:
            error_msg = "Found duplicate values:\n"
            for value, node_id1, node_id2 in duplicates:
                error_msg += f"  Value '{value}' exists in nodes {node_id1} and {node_id2}\n"
            raise ConstraintViolationError(error_msg)
    
    def _apply_operations(self):
       
        if not self.is_active:
            raise TransactionError("Cannot apply operations without an active transaction.")
        
        for entry in self.log:
            operation = entry['operation']
            details = entry['details']

            if operation == 'CREATE_NODE':
                node = Node(
                    labels=details.get('labels', []),
                    properties=details.get('properties', {})
                )
                node.id = details['node_id']
                self.db.add_node(node)

            elif operation == 'DELETE_NODE':
                self.db.delete_node(details['node_id'])

            elif operation == 'CREATE_RELATIONSHIP':
                source = self.db.nodes.get(details['source_id'])
                target = self.db.nodes.get(details['target_id'])
                if source and target:
                    rel = Relationship(
                        source,
                        target,
                        type_=details['type'],
                        properties=details.get('properties', {})
                    )
                    rel.id = details.get('relationship_id', str(uuid.uuid4()))
                    self.db.add_relationship(rel)

            elif operation == 'CREATE_CONSTRAINT':
                self.db.add_unique_constraint(
                    details['label'],
                    details['property']
                )

            elif operation == 'DROP_CONSTRAINT':
                self.db.drop_constraint(
                    details['label'],
                    details['property']
                )

            elif operation == 'CREATE_INDEX':
                # Placeholder for actual index creation logic
                pass  # TODO: implement index creation logic

            elif operation == 'DROP_INDEX':
                # Placeholder for actual index dropping logic
                pass  # TODO: implement index dropping logic

            else:
                raise TransactionError(f"Unsupported operation: {operation}")

    
     

        
    def _detect_deadlocks(self):
        """Detect potential deadlocks using a timeout approach"""
        # Check if other transactions have been active too long
        # This is a simple timeout-based approach
        current_time = time.time()
        deadlock_timeout = 30.0  # 30 seconds max transaction time
        
        for tx_id, start_time in Transaction.active_transactions.items():
            if tx_id != self.tx_id and (current_time - start_time) > deadlock_timeout:
                logging.warning(f"Potential deadlock detected with transaction {tx_id}")
                # In a more sophisticated system, we would analyze the dependency graph
                # For now, we'll abort this transaction as it might be part of a deadlock
                return True
        return False
        
    def _save_database_to_disk(self):
        """Save the current database state to disk"""
        try:
            # Check for potential deadlocks before attempting to save
            if self._detect_deadlocks():
                raise DeadlockError("Transaction aborted to prevent deadlock")
            
            # Use a dedicated file lock for disk operations
            with db_file_lock:
                # Only save to db.json on explicit COMMIT operations
                # This ensures changes are not persisted during auto-transactions
                data = self.db.serialize()
                
                # Save to root db.json
                # First write to a temporary file
                temp_file = 'db.json.tmp'
                with open(temp_file, 'w') as f:
                    json.dump(data, f, indent=2)
                
                # Then atomically rename to ensure durability even if system crashes
                os.replace(temp_file, 'db.json')
                
                # Also save to data directory for consistency with UI operations
                data_dir = 'data'
                os.makedirs(data_dir, exist_ok=True)
                data_temp_file = os.path.join(data_dir, 'graph_db.json.tmp')
                data_file = os.path.join(data_dir, 'graph_db.json')
                
                with open(data_temp_file, 'w') as f:
                    json.dump(data, f, indent=2)
                
                # Then atomically rename to ensure durability
                os.replace(data_temp_file, data_file)
                
            logging.debug("Database state saved to disk (both root and data directory)")
            return True
        except Exception as e:
            logging.error(f"Error saving database to disk: {str(e)}")
            return False
    
    def load_database_from_disk(self):
        """Load the database state from disk"""
        # Use the file lock to ensure safe reading
        with db_file_lock:
            try:
                # First check if a temp file exists - might indicate an incomplete write
                temp_file = 'db.json.tmp'
                db_file = 'db.json'
                data_dir = 'data'
                data_temp_file = os.path.join(data_dir, 'graph_db.json.tmp')
                data_file = os.path.join(data_dir, 'graph_db.json')
                
                # Check both root and data directory files
                # Root directory recovery
                if os.path.exists(temp_file) and os.path.exists(db_file):
                    # Both exist, check which is newer
                    temp_mtime = os.path.getmtime(temp_file)
                    db_mtime = os.path.getmtime(db_file)
                    
                    if temp_mtime > db_mtime:
                        # Temp file is newer, the system must have crashed during a save
                        # Attempt recovery by promoting the temp file
                        try:
                            os.replace(temp_file, db_file)
                            logging.info("Recovered from previous incomplete save operation")
                        except Exception:
                            logging.warning("Failed to recover from incomplete save, using last known good state")
                    else:
                        # Main file is newer or same age, remove stale temp file
                        try:
                            os.remove(temp_file)
                        except Exception:
                            pass
                elif os.path.exists(temp_file) and not os.path.exists(db_file):
                    # Only temp file exists, promote it
                    try:
                        os.rename(temp_file, db_file)
                        logging.info("Recovered database from temporary file")
                    except Exception:
                        logging.error("Failed to recover database from temporary file")
                
                # Data directory recovery
                if os.path.exists(data_dir):
                    if os.path.exists(data_temp_file) and os.path.exists(data_file):
                        # Both exist, check which is newer
                        temp_mtime = os.path.getmtime(data_temp_file)
                        data_mtime = os.path.getmtime(data_file)
                        
                        if temp_mtime > data_mtime:
                            # Temp file is newer
                            try:
                                os.replace(data_temp_file, data_file)
                                logging.info("Recovered from previous incomplete save in data directory")
                            except Exception:
                                logging.warning("Failed to recover from incomplete save in data directory")
                        else:
                            # Main file is newer, remove stale temp
                            try:
                                os.remove(data_temp_file)
                            except Exception:
                                pass
                    elif os.path.exists(data_temp_file) and not os.path.exists(data_file):
                        # Only temp exists
                        try:
                            os.rename(data_temp_file, data_file)
                            logging.info("Recovered database from data directory temporary file")
                        except Exception:
                            logging.error("Failed to recover database from data directory temporary file")
                
                # Try to load the database
                # First try root directory file
                loaded = False
                if os.path.exists(db_file):
                    try:
                        with open(db_file, 'r') as f:
                            data = json.load(f)
                        self.db.deserialize(data)
                        logging.debug("Database state loaded from root directory file")
                        loaded = True
                    except json.JSONDecodeError:
                        logging.error("Corrupted database file found in root directory")
                
                # If root didn't work, try data directory
                if not loaded and os.path.exists(data_dir) and os.path.exists(data_file):
                    try:
                        with open(data_file, 'r') as f:
                            data = json.load(f)
                        self.db.deserialize(data)
                        logging.debug("Database state loaded from data directory file")
                        
                        # If we loaded from data directory, sync back to root
                        with open(db_file, 'w') as f:
                            json.dump(data, f, indent=2)
                        
                        loaded = True
                    except json.JSONDecodeError:
                        logging.error("Corrupted database file found in data directory")
                
                if loaded:
                    return True
                else:
                    logging.debug("No saved database state found")
                    return False
            except Exception as e:
                logging.error(f"Error loading database from disk: {str(e)}")
                return False