import os
import json
import logging
import uuid
from flask import Flask, render_template, request, jsonify, session

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(message)s')
from graph_db.database import GraphDatabase
from graph_db.parser import CypherParser

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev_secret_key")

# Initialize the graph database
graph_db = GraphDatabase()
parser = CypherParser(graph_db)

# Example database for demo purposes
def initialize_example_db():
    # Reset the database
    graph_db.nodes = {}
    graph_db.relationships = {}
    
    # Create some nodes and relationships
    logging.debug("Creating example database")
    
    # Create Person nodes
    parser.execute("CREATE (:Person {name: 'Alice', age: 30})")
    parser.execute("CREATE (:Person {name: 'Bob', age: 40})")
    parser.execute("CREATE (:Person {name: 'Charlie', age: 25})")
    
    # Create Movie nodes
    parser.execute("CREATE (:Movie {title: 'The Matrix', year: 1999})")
    parser.execute("CREATE (:Movie {title: 'Inception', year: 2010})")
    
    logging.debug(f"Created nodes: {len(graph_db.nodes)}")
    
    # Create KNOWS relationships between people
    parser.execute("MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) CREATE (a)-[:KNOWS {since: 2015}]->(b)")
    parser.execute("MATCH (a:Person {name: 'Bob'}), (c:Person {name: 'Charlie'}) CREATE (a)-[:KNOWS {since: 2018}]->(c)")
    
    # Create WATCHED relationships between people and movies
    parser.execute("MATCH (a:Person {name: 'Alice'}), (m:Movie {title: 'The Matrix'}) CREATE (a)-[:WATCHED {rating: 5}]->(m)")
    parser.execute("MATCH (b:Person {name: 'Bob'}), (m:Movie {title: 'Inception'}) CREATE (b)-[:WATCHED {rating: 4}]->(m)")
    parser.execute("MATCH (b:Person {name: 'Bob'}), (m:Movie {title: 'The Matrix'}) CREATE (b)-[:WATCHED {rating: 3}]->(m)")
    parser.execute("MATCH (c:Person {name: 'Charlie'}), (m:Movie {title: 'The Matrix'}) CREATE (c)-[:WATCHED {rating: 4}]->(m)")
    
    logging.debug(f"Created relationships: {len(graph_db.relationships)}")
    
    # Validate Alice's relationships
    alice_node = None
    for node in graph_db.nodes.values():
        if 'Person' in node.labels and node.properties.get('name') == 'Alice':
            alice_node = node
            break
    
    if alice_node:
        alice_rels = graph_db.find_relationships_from(alice_node.id)
        logging.debug(f"Alice has {len(alice_rels)} relationships")

# Initialize example database
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
        result = parser.execute(query)
        logging.info(f"Query result: {result}")
        
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
            return jsonify({'result': serialized_results})
        
        # If it's operation results like create/delete counts
        logging.info(f"Returning operation result: {result}")
        return jsonify({'result': result})
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
    try:
        # Make sure filename is defined and safe
        filename = request.json.get('filename', 'graph_db.json')
        safe_filename = os.path.basename(filename)  # Only use the base name, not paths
        
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

@app.route('/example_queries')
def example_queries():
    examples = [
        "MATCH (n) RETURN n LIMIT 10",
        "MATCH (p:Person) RETURN p",
        "MATCH (m:Movie) RETURN m",
        "MATCH (p:Person)-[r:KNOWS]->(friend) RETURN p, r, friend",
        "MATCH (p:Person)-[r:WATCHED]->(m:Movie) RETURN p.name, m.title, r.rating",
        "MATCH (p:Person) WHERE p.age > 25 RETURN p",
        "MATCH (p:Person)-[:WATCHED]->(m:Movie) WHERE m.title = 'The Matrix' RETURN p.name",
        "CREATE (:Person {name: 'Dave', age: 35})",
        "MATCH (a:Person {name: 'Alice'}), (d:Person {name: 'Dave'}) CREATE (a)-[:KNOWS {since: 2020}]->(d)",
        "MATCH (p:Person {name: 'Alice'}) SET p.job = 'Developer' RETURN p",
        "MATCH (p:Person {name: 'Dave'}) DELETE p"
    ]
    return jsonify({'examples': examples})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
