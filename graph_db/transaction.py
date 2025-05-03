import logging
import json
import os
import copy
from .database import GraphDatabase

class Transaction:
    """
    Transaction management for graph database operations
    """
    def __init__(self, graph_db):
        """Initialize a new transaction"""
        self.db = graph_db
        self.snapshot = None
        self.is_active = False
        self.log = []
    
    def begin(self):
        """Start a new transaction by taking a snapshot of the current state"""
        if self.is_active:
            raise ValueError("Transaction already in progress")
        
        # Create a deep copy of the database state
        self.snapshot = {
            "nodes": copy.deepcopy(self.db.nodes),
            "relationships": copy.deepcopy(self.db.relationships),
            "constraints": copy.deepcopy(self.db.constraints)
        }
        
        self.is_active = True
        self.log = []
        logging.debug("Transaction started")
        return True
    
    def log_operation(self, operation, details):
        """Log an operation in the current transaction"""
        if not self.is_active:
            raise ValueError("No active transaction")
        
        self.log.append({"operation": operation, "details": details})
        logging.debug(f"Transaction log: {operation} - {details}")
    
    def commit(self):
        """Commit the transaction by persisting changes to disk"""
        if not self.is_active:
            raise ValueError("No active transaction to commit")
        
        try:
            # Save the database state to a JSON file
            self._save_database_to_disk()
            # Reset transaction state
            self.snapshot = None
            self.is_active = False
            logging.debug(f"Transaction committed with {len(self.log)} operations")
            return True
        except Exception as e:
            logging.error(f"Error committing transaction: {str(e)}")
            return False
    
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