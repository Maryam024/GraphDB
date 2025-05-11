import os
import json
import logging
import uuid
from flask import Flask, render_template, request, jsonify, session

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(message)s')
from graph_db.database import GraphDatabase
from graph_db.simple_parser import SimpleCypherParser

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev_secret_key")

# Initialize the graph database
graph_db = GraphDatabase()
parser = SimpleCypherParser(graph_db)

# Example database for demo purposes
def initialize_example_db():
    # Reset the database
    graph_db.clear()
    
    logging.debug("Creating example database")
    
    # First create all nodes
    alice = graph_db.create_node(["Person"], {"name": "Alice", "age": 30})
    bob = graph_db.create_node(["Person"], {"name": "Bob", "age": 40})
    charlie = graph_db.create_node(["Person"], {"name": "Charlie", "age": 25})
    dave = graph_db.create_node(["Person"], {"name": "Dave", "age": 35})
    matrix = graph_db.create_node(["Movie"], {"title": "The Matrix", "year": 1999})
    inception = graph_db.create_node(["Movie"], {"title": "Inception", "year": 2010})
    
    logging.debug(f"Created {len(graph_db.nodes)} nodes")
    
    # Then create relationships directly
    rel1 = graph_db.create_relationship(alice, bob, "KNOWS", {"since": 2015})
    rel2 = graph_db.create_relationship(bob, charlie, "KNOWS", {"since": 2018})
    rel3 = graph_db.create_relationship(alice, matrix, "WATCHED", {"rating": 5})
    rel4 = graph_db.create_relationship(bob, inception, "WATCHED", {"rating": 4})
    rel5 = graph_db.create_relationship(bob, matrix, "WATCHED", {"rating": 3})
    rel6 = graph_db.create_relationship(charlie, matrix, "WATCHED", {"rating": 4})
    
    # Create a FRIEND relationship
    friend_rel = graph_db.create_relationship(alice, bob, "FRIEND", {"since": 2010})
    
    # Create a dummy Dave for testing
    dave = graph_db.create_node(["Person"], {"name": "Dave", "age": 35})
    
    logging.debug(f"Created {len(graph_db.relationships)} relationships")
    
    # Log all relationships for debugging
    for rel_id, rel in graph_db.relationships.items():
        source_node = graph_db.nodes[rel.source_id]
        target_node = graph_db.nodes[rel.target_id]
        source_name = source_node.properties.get('name', '') or source_node.properties.get('title', '')
        target_name = target_node.properties.get('name', '') or target_node.properties.get('title', '')
        logging.debug(f"Relationship {rel_id}: {source_name} -[{rel.type}]-> {target_name}")

    # Test query to verify FRIENDS relationship works
    result = parser.execute("MATCH (p:Person)-[r:FRIEND]->(friend) RETURN p.name, friend.name, r.since")
    logging.debug(f"FRIEND relationship test: {result}")
    
    # Save initial database state to db.json
    try:
        db_state = graph_db.serialize()
        with open('db.json', 'w') as f:
            json.dump(db_state, f, indent=2)
        logging.info("Initial database state saved to db.json")
    except Exception as e:
        logging.error(f"Error saving initial database state: {str(e)}")

# Try to load existing database from db.json, or initialize example database if not found
try:
    # Create a transaction for loading
    tx = Transaction(graph_db)
    if tx.load_database_from_disk():
        logging.info("Loaded existing database from db.json")
    else:
        logging.info("No existing database found, initializing example database")
        initialize_example_db()
except Exception as e:
    logging.error(f"Error loading database, initializing example database: {str(e)}")
    initialize_example_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/execute', methods=['POST'])
def execute_query():
    query = request.json.get('query', '')
    
    if not query.strip():
        return jsonify({'error': 'Query is empty'}), 400
    
    logging.info(f"Executing query: {query}")
    
    try:
        # Measure execution time
        import time
        start_time = time.time()
        
        # Execute the query
        result = parser.execute(query)
        
        # Calculate execution time
        execution_time = time.time() - start_time
        execution_time_ms = round(execution_time * 1000, 2)  # Convert to milliseconds with 2 decimal places
        
        logging.info(f"Query result: {result}")
        logging.info(f"Execution time: {execution_time_ms} ms")
        
        # Serialize the results if it's a list of objects
        if isinstance(result, list):
            serialized_results = []
            for item in result:
                serialized_item = {}
                for key, value in item.items():
                    # Check if it's a Node or Relationship
                    if hasattr(value, 'serialize'):
                        serialized_item[key] = value.serialize()
                    else:
                        serialized_item[key] = value
                serialized_results.append(serialized_item)
            logging.info(f"Serialized results: {serialized_results}")
            return jsonify({
                'result': serialized_results, 
                'execution_time_ms': execution_time_ms
            })
        
        # If it's operation results like create/delete counts
        logging.info(f"Returning operation result: {result}")
        return jsonify({
            'result': result,
            'execution_time_ms': execution_time_ms
        })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logging.error(f"Query execution error: {str(e)}\n{error_trace}")
        return jsonify({'error': str(e)}), 400

@app.route('/save', methods=['POST'])
def save_database():
    try:
        db_state = graph_db.serialize()
        # Make sure filename is defined and safe
        filename = request.json.get('filename', 'graph_db.json')
        safe_filename = os.path.basename(filename)  # Only use the base name, not paths
        
        # Save to a dedicated data directory
        data_dir = 'data'
        os.makedirs(data_dir, exist_ok=True)
        file_path = os.path.join(data_dir, safe_filename)
        
        with open(file_path, 'w') as f:
            json.dump(db_state, f, indent=2)
        
        return jsonify({'message': f'Database saved as {safe_filename}'})
    except Exception as e:
        logging.error(f"Save error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/load', methods=['POST'])
def load_database():
    # Define safe_filename outside the try block so it's available in all exception handlers
    filename = request.json.get('filename', 'graph_db.json')
    safe_filename = os.path.basename(filename)  # Only use the base name, not paths
    
    try:
        # Load from the dedicated data directory
        data_dir = 'data'
        file_path = os.path.join(data_dir, safe_filename)
        
        with open(file_path, 'r') as f:
            db_state = json.load(f)
        
        graph_db.deserialize(db_state)
        
        return jsonify({'message': f'Database loaded from {safe_filename}'})
    except FileNotFoundError:
        return jsonify({'error': f'File {safe_filename} not found'}), 404
    except Exception as e:
        logging.error(f"Load error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/constraints', methods=['GET'])
def get_constraints():
    try:
        # Get the current database constraints
        constraints = graph_db.constraints
        
        # Format constraints for display
        formatted_constraints = []
        
        for label, property_name in constraints.get('unique', []):
            formatted_constraints.append({
                'type': 'UNIQUE',
                'label': label,
                'property': property_name
            })
            
        return jsonify({'constraints': formatted_constraints})
    except Exception as e:
        logging.error(f"Error getting constraints: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/indexes', methods=['GET'])
def get_indexes():
    try:
        # Get the current index metadata
        indexes = []
        for label, prop in graph_db.indexed_properties:
            indexes.append({
                'label': label,
                'property': prop
            })
        
        return jsonify({'indexes': indexes})
    except Exception as e:
        logging.error(f"Error getting indexes: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/index_stats', methods=['GET'])
def get_index_stats():
    try:
        # Get detailed index statistics
        stats = graph_db.get_index_statistics()
        
        # Format date/time values for display
        for stat in stats:
            if 'creation_time' in stat and stat['creation_time']:
                stat['creation_time'] = format_timestamp(stat['creation_time'])
            if 'last_used' in stat and stat['last_used']:
                stat['last_used'] = format_timestamp(stat['last_used'])
        
        return jsonify({'index_statistics': stats})
    except Exception as e:
        logging.error(f"Error getting index statistics: {str(e)}")
        return jsonify({'error': str(e)}), 500

def format_timestamp(timestamp):
    """Format a timestamp into a human-readable string"""
    from datetime import datetime
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

@app.route('/example_queries')
def example_queries():
    examples = [
        # Basic Queries
        "MATCH (n) RETURN n LIMIT 10",
        "MATCH (p:Person) RETURN p",
        "MATCH (m:Movie) RETURN m",
        "MATCH (p:Person)-[r:KNOWS]->(friend) RETURN p, r, friend",
        "MATCH (p:Person)-[r:WATCHED]->(m:Movie) RETURN p.name, m.title, r.rating",
        
        # WHERE Clause with Comparison Operators
        "MATCH (p:Person) WHERE p.age > 25 RETURN p",
        "MATCH (p:Person) WHERE p.age < 35 RETURN p",
        "MATCH (p:Person) WHERE p.age >= 30 RETURN p",
        "MATCH (p:Person) WHERE p.age <= 30 RETURN p",
        "MATCH (m:Movie) WHERE m.year > 2000 RETURN m.title, m.year",
        
        # WHERE Clause with Logical Operators
        "MATCH (p:Person) WHERE p.age > 25 AND p.age < 40 RETURN p",
        "MATCH (p:Person) WHERE p.name = 'Alice' OR p.name = 'Bob' RETURN p",
        "MATCH (p:Person) WHERE p.age > 30 OR p.name = 'Charlie' RETURN p",
        "MATCH (p:Person) WHERE NOT p.age = 25 RETURN p",
        "MATCH (p:Person)-[:WATCHED]->(m:Movie) WHERE m.title = 'The Matrix' AND p.age > 30 RETURN p.name",
        
        # Complex WHERE Clauses with Nested Conditions
        "MATCH (p:Person) WHERE (p.age > 30 AND p.name = 'Bob') OR (p.age < 30 AND p.name = 'Charlie') RETURN p",
        "MATCH (p:Person)-[r:WATCHED]->(m:Movie) WHERE (m.year > 2000 OR m.title = 'The Matrix') AND r.rating > 3 RETURN p.name, m.title, r.rating",
        
        # Node and Relationship Creation
        "CREATE (:Person {name: 'Dave', age: 35})",
        "MATCH (a:Person {name: 'Alice'}), (d:Person {name: 'Dave'}) CREATE (a)-[:KNOWS {since: 2020}]->(d)",
        
        # Updates and Deletions
        "MATCH (p:Person {name: 'Alice'}) SET p.job = 'Developer' RETURN p",
        "MATCH (p:Person {name: 'Dave'}) DELETE p",
        "MATCH (p:Person) WHERE p.age < 30 SET p.status = 'Junior' RETURN p",
        "MATCH (p:Person) WHERE p.age >= 30 AND p.age < 40 SET p.status = 'Senior' RETURN p",
        
        # Transaction Management
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "BEGIN\nCREATE (:Person {name: 'Eve', age: 28})\nCOMMIT",
        
        # Constraint Operations
        "CREATE CONSTRAINT ON (p:Person) ASSERT p.name IS UNIQUE",
        "DROP CONSTRAINT ON (p:Person) ASSERT p.name IS UNIQUE",
        "CREATE CONSTRAINT ON (m:Movie) ASSERT m.title IS UNIQUE",
        
        # Index Operations
        "CREATE INDEX ON :Person(name)",
        "CREATE INDEX ON :Movie(title)",
        "CREATE INDEX ON :Person(age)",
        "DROP INDEX ON :Person(name)",
        
        # Using Indexed Properties for Efficient Queries
        "MATCH (p:Person {name: 'Alice'}) RETURN p",
        "MATCH (m:Movie {title: 'The Matrix'}) RETURN m",
        "MATCH (p:Person)-[:WATCHED]->(m:Movie {title: 'The Matrix'}) RETURN p.name",
        "MATCH (p:Person) WHERE p.age > 30 AND p.age < 45 RETURN p",  # Can use index on age
        
        # Complex Transactions with Indexes
        "BEGIN\nCREATE INDEX ON :Person(email)\nCREATE INDEX ON :Person(age)\nCOMMIT",
        
        # Advanced Transaction Examples
        "BEGIN\nCREATE CONSTRAINT ON (p:Person) ASSERT p.email IS UNIQUE\nCOMMIT",
        "BEGIN\nCREATE (:Person {name: 'Frank', email: 'frank@example.com'})\nCREATE (:Person {name: 'Grace', email: 'grace@example.com'})\nCOMMIT"
    ]
    return jsonify({'examples': examples})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
