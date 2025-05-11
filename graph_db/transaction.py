import logging
import json
import os
import copy
import threading
import time
from .database import GraphDatabase

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
    """
    Transaction management for graph database operations with ACID properties:
    - Atomicity: All operations succeed or all fail (guaranteed by snapshot and rollback)
    - Consistency: Database remains valid after transaction (enforced by constraints)
    - Isolation: Transactions don't interfere with each other (managed by locks)
    - Durability: Committed changes are permanently stored (via JSON persistence)
    """
    # Class-level active transactions tracking for deadlock prevention
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
        """Log an operation in the current transaction"""
        if not self.is_active:
            raise TransactionError("No active transaction")
        
        # Track modified objects for conflict detection
        if 'node_id' in details:
            self.modified_nodes.add(details['node_id'])
        if 'relationship_id' in details:
            self.modified_rels.add(details['relationship_id'])
        
        # Check constraints for node operations
        if operation == 'CREATE_NODE' and not self._check_constraints(details):
            self.rollback()
            raise ConstraintViolationError(f"Node creation would violate constraints")
        
        # Handle constraint operations
        if operation == 'CREATE_CONSTRAINT':
            try:
                # Validate that no existing data violates the constraint
                self._validate_constraint_creation(details.get('label'), details.get('property'))
            except Exception as e:
                self.rollback()
                raise ConstraintViolationError(f"Cannot create constraint: {str(e)}")
            
        # Add operation to log
        self.log.append({"operation": operation, "details": details})
        logging.debug(f"Transaction {self.tx_id} log: {operation} - {details}")
    
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
        """Apply all operations in the log to the database"""
        for entry in self.log:
            operation = entry['operation']
            details = entry['details']
            
            # Apply each operation based on its type
            if operation == 'CREATE_CONSTRAINT':
                label = details.get('label')
                property_name = details.get('property')
                constraint_type = details.get('type', 'UNIQUE')
                
                if constraint_type == 'UNIQUE':
                    # Add the constraint directly to the database
                    self.db.add_unique_constraint(label, property_name)
                    logging.debug(f"Applied CREATE_CONSTRAINT: {label}.{property_name} IS UNIQUE")
            
            elif operation == 'DROP_CONSTRAINT':
                label = details.get('label')
                property_name = details.get('property')
                constraint_type = details.get('type', 'UNIQUE')
                
                if constraint_type == 'UNIQUE':
                    # Remove the constraint from the database
                    self.db.drop_constraint(label, property_name)
                    logging.debug(f"Applied DROP_CONSTRAINT: {label}.{property_name} IS UNIQUE")
            
            elif operation == 'CREATE_INDEX':
                label = details.get('label')
                property_name = details.get('property')
                
                # Create the index
                self.db.create_index(label, property_name)
                logging.debug(f"Applied CREATE_INDEX: {label}.{property_name}")
            
            elif operation == 'DROP_INDEX':
                label = details.get('label')
                property_name = details.get('property')
                
                # Drop the index
                self.db.drop_index(label, property_name)
                logging.debug(f"Applied DROP_INDEX: {label}.{property_name}")
    
    def commit(self):
        """Commit the transaction by persisting changes to disk"""
        with transaction_lock:
            if not self.is_active:
                raise TransactionError("No active transaction to commit")
            
            try:
                # Verify constraints again before committing (for Consistency)
                for entry in self.log:
                    operation = entry['operation']
                    details = entry['details']
                    
                    # For node operations, validate against constraints
                    if operation in ['CREATE_NODE', 'UPDATE_NODE'] and not self._check_constraints(details):
                        self.rollback()
                        raise ConstraintViolationError("Cannot commit - constraint violation")
                    
                    # For constraint creation, validate again
                    if operation == 'CREATE_CONSTRAINT':
                        try:
                            self._validate_constraint_creation(details.get('label'), details.get('property'))
                        except Exception as e:
                            self.rollback()
                            raise ConstraintViolationError(f"Cannot commit constraint creation: {str(e)}")
                
                # Apply operations for constraints and indexes
                self._apply_operations()
                
                # Save the database state to a JSON file (for Durability)
                self._save_database_to_disk()
                
                # Reset transaction state
                self.snapshot = None
                self.is_active = False
                if self.tx_id in Transaction.active_transactions:
                    del Transaction.active_transactions[self.tx_id]
                    
                logging.debug(f"Transaction {self.tx_id} committed with {len(self.log)} operations")
                return True
            except Exception as e:
                logging.error(f"Error committing transaction {self.tx_id}: {str(e)}")
                self.rollback()
                raise
    
    def rollback(self):
        """Rollback the transaction by restoring the database state from the snapshot"""
        if not self.is_active:
            raise ValueError("No active transaction to rollback")
        
        try:
            if self.snapshot:
                # Restore database state from snapshot
                self.db.nodes = self.snapshot["nodes"]
                self.db.relationships = self.snapshot["relationships"]
                self.db.constraints = self.snapshot["constraints"]
            
            # Reset transaction state
            self.snapshot = None
            self.is_active = False
            logging.debug(f"Transaction rolled back, discarding {len(self.log)} operations")
            return True
        except Exception as e:
            logging.error(f"Error rolling back transaction: {str(e)}")
            return False
    
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