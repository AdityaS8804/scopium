import os
import json
from arango import ArangoClient
from dotenv import load_dotenv

def diagnose_database_issues():
    """
    Diagnose why the symbol index may be empty by checking the database
    structure, collections, and data format.
    """
    # Load environment variables
    load_dotenv()
    
    # Database connection parameters - update these with your actual values
    db_name = "_system"
    username = "root"
    password = "cUZ0YaNdcwfUTw6VjRny"
    host = "https://d2eeb8083350.arangodb.cloud:8529"
    
    # Collection names to check
    node_collection = "FlaskRepv1_node"
    edge_collection = "FlaskRepv1_node_to_FlaskRepv1_node"
    graph_name = "FlaskRepv1"
    
    # Connect to ArangoDB
    print(f"Connecting to {host}...")
    client = ArangoClient(hosts=host)
    
    try:
        db = client.db(db_name, username=username, password=password)
        print(f"✓ Successfully connected to database: {db_name}")
    except Exception as e:
        print(f"✗ Failed to connect to database: {str(e)}")
        return
    
    # Step 1: Check if collections exist
    print("\nChecking collections...")
    all_collections = [c['name'] for c in db.collections()]
    print(f"All collections in database: {all_collections}")
    
    if node_collection in all_collections:
        print(f"✓ Node collection exists: {node_collection}")
    else:
        print(f"✗ Node collection does not exist: {node_collection}")
        print("   Available collections: " + ", ".join(all_collections))
    
    if edge_collection in all_collections:
        print(f"✓ Edge collection exists: {edge_collection}")
    else:
        print(f"✗ Edge collection does not exist: {edge_collection}")
    
    # Step 2: Check if the graph exists
    print("\nChecking graph...")
    all_graphs = [g['name'] for g in db.graphs()]
    print(f"All graphs in database: {all_graphs}")
    
    if graph_name in all_graphs:
        print(f"✓ Graph exists: {graph_name}")
        # Check graph definition
        graph = db.graph(graph_name)
        edge_definitions = graph.edge_definitions()
        print(f"  Graph edge definitions: {edge_definitions}")
    else:
        print(f"✗ Graph does not exist: {graph_name}")
    
    # Step 3: Check node collection content
    print("\nChecking node collection content...")
    if node_collection in all_collections:
        collection = db.collection(node_collection)
        count = collection.count()
        print(f"Node collection has {count} documents")
        
        if count > 0:
            # Check for the presence of symbols (keys containing "::")
            aql = f"""
            FOR v IN {node_collection}
                FILTER CONTAINS(v._key, "::")
                LIMIT 10
                RETURN {{
                    "key": v._key,
                    "symbol_type": v.symbol_type,
                    "line_number": v.line_number
                }}
            """
            try:
                cursor = db.aql.execute(aql)
                symbols = [doc for doc in cursor]
                symbol_count = len(symbols)
                
                if symbol_count > 0:
                    print(f"✓ Found {symbol_count} symbols with '::' in their keys")
                    print("Sample symbols:")
                    for i, symbol in enumerate(symbols[:5]):
                        print(f"  {i+1}. {symbol['key']} (Type: {symbol.get('symbol_type', 'N/A')})")
                else:
                    print("✗ No symbols found with '::' in their keys")
                    
                    # Check if there are any documents and what their structure looks like
                    aql = f"""
                    FOR v IN {node_collection}
                        LIMIT 5
                        RETURN {{
                            "key": v._key,
                            "keys": ATTRIBUTES(v, true),
                            "type": v.type
                        }}
                    """
                    cursor = db.aql.execute(aql)
                    samples = [doc for doc in cursor]
                    
                    if samples:
                        print("Sample documents in node collection:")
                        for i, doc in enumerate(samples):
                            print(f"  {i+1}. Key: {doc['key']}")
                            print(f"     Document attributes: {doc.get('keys', [])}")
                            print(f"     Type: {doc.get('type', 'N/A')}")
                    else:
                        print("No documents found in node collection despite count > 0")
            except Exception as e:
                print(f"Error querying symbols: {str(e)}")
    
    # Step 4: Check actual schema of the documents
    print("\nAnalyzing document schema...")
    if node_collection in all_collections:
        aql = f"""
        FOR v IN {node_collection}
            LIMIT 1
            RETURN v
        """
        try:
            cursor = db.aql.execute(aql)
            samples = [doc for doc in cursor]
            
            if samples:
                print("Document schema example:")
                sample = samples[0]
                # Print first level of attributes to avoid overwhelming output
                attributes = {k: (type(v).__name__ if not isinstance(v, (dict, list)) else 
                               f"{type(v).__name__} of length {len(v)}") 
                             for k, v in sample.items()}
                for k, v in attributes.items():
                    print(f"  {k}: {v}")
                
                # Check if _key has the expected format and if expected attributes exist
                expected_attrs = ["symbol_type", "line_number", "context", "docstring"]
                if "_key" in sample:
                    print(f"\nKey format analysis for '{sample['_key']}':")
                    if "::" in sample["_key"]:
                        print("✓ Key contains '::' separator as expected")
                        parts = sample["_key"].split("::")
                        print(f"  File part: {parts[0]}")
                        print(f"  Symbol part: {parts[1] if len(parts) > 1 else 'N/A'}")
                    else:
                        print("✗ Key does not contain '::' separator")
                        print("  This might explain why no symbols are being found")
                
                print("\nChecking for expected attributes:")
                for attr in expected_attrs:
                    if attr in sample:
                        print(f"✓ '{attr}' attribute exists")
                    else:
                        print(f"✗ '{attr}' attribute does not exist")
            else:
                print("No documents found to analyze schema")
        except Exception as e:
            print(f"Error analyzing schema: {str(e)}")
    
    print("\nDiagnosis complete. Check the output above to identify why the symbol index is empty.")

if __name__ == "__main__":
    diagnose_database_issues()