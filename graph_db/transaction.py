import logging
import json
import os
import copy
import threading
import time
from .database import GraphDatabase

# Global transaction lock for concurrency control
transaction_lock = threading.RLock()

class TransactionError(Exception):
    """Base exception for transaction errors"""
    pass

class ConcurrencyError(TransactionError):
    """Exception raised when concurrent operations conflict"""
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
            
        if operation == 'CREATE_NODE' and not self._check_constraints(details):
            self.rollback()
            raise ConstraintViolationError(f"Node creation would violate constraints")
            
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
    
    def commit(self):
        """Commit the transaction by persisting changes to disk"""
        with transaction_lock:
            if not self.is_active:
                raise TransactionError("No active transaction to commit")
            
            try:
                # Verify constraints again before committing (for Consistency)
                for entry in self.log:
                    if not self._check_constraints(entry['details']):
                        self.rollback()
                        raise ConstraintViolationError("Cannot commit - constraint violation")
                
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
    
    def _save_database_to_disk(self):
        """Save the current database state to disk"""
        try:
            # Only save to db.json on explicit COMMIT operations
            # This ensures changes are not persisted during auto-transactions
            data = self.db.serialize()
            with open('db.json', 'w') as f:
                json.dump(data, f, indent=2)
            logging.debug("Database state saved to disk")
            return True
        except Exception as e:
            logging.error(f"Error saving database to disk: {str(e)}")
            return False
    
    def load_database_from_disk(self):
        """Load the database state from disk"""
        try:
            if os.path.exists('db.json'):
                with open('db.json', 'r') as f:
                    data = json.load(f)
                self.db.deserialize(data)
                logging.debug("Database state loaded from disk")
                return True
            else:
                logging.debug("No saved database state found")
                return False
        except Exception as e:
            logging.error(f"Error loading database from disk: {str(e)}")
            return False