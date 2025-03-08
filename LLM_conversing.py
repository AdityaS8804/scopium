import os
import json
from dotenv import load_dotenv
from LLM import EnhancedCodebaseQuery

def main():
    """
    Main function to demonstrate using the EnhancedCodebaseQuery class.
    """
    # Load environment variables from .env file
    load_dotenv()
    
    # Get configuration from environment variables or use defaults
    # db_name = os.environ.get("ARANGODB_NAME", "_system")
    # username = os.environ.get("ARANGODB_USERNAME", "root")
    # password = os.environ.get("ARANGODB_PASSWORD", "your_password")
    # host = os.environ.get("ARANGODB_HOST", "https://your_host.arangodb.cloud:8529")
    # mistral_api_key = os.environ.get("MISTRAL_API_KEY")
    # model = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
    # node_collection = os.environ.get("NODE_COLLECTION", "your_node_collection")
    # edge_collection = os.environ.get("EDGE_COLLECTION", "your_edge_collection")
    # graph_name = os.environ.get("GRAPH_NAME", "your_graph_name")

    db_name="_system"
    username="root"
    password="cUZ0YaNdcwfUTw6VjRny"
    host="https://d2eeb8083350.arangodb.cloud:8529"
    mistral_api_key=os.environ.get("MISTRAL_API_KEY")
    node_collection="FlaskRepv1_node"
    edge_collection="FlaskRepv1_node_to_FlaskRepv1_node"
    graph_name="FlaskRepv1"
    model = "mistral-large-latest"
    
    # Initialize the EnhancedCodebaseQuery class
    try:
        query_engine = EnhancedCodebaseQuery(
            db_name=db_name,
            username=username,
            password=password,
            host=host,
            mistral_api_key=mistral_api_key,
            model=model,
            node=node_collection,
            edge=edge_collection,
            graph=graph_name
        )
        print("✅ Successfully initialized the codebase query engine")
        
        # Interactive command line interface
        print("\n==== Codebase Query Tool ====")
        print("Type 'exit' to quit")
        print("Available commands:")
        print("  1. function <name> - Query a function by name")
        print("  2. symbol <name> - Find all occurrences of a symbol")
        print("  3. search <term> - Search for a term in the codebase")
        print("  4. structure - Analyze database structure")
        print("  5. overview - Get a codebase overview")
        print("  6. query <question> - Ask a natural language question about the codebase")
        
        while True:
            user_input = input("\nEnter command > ").strip()
            
            if user_input.lower() == 'exit':
                break
                
            parts = user_input.split(' ', 1)
            command = parts[0].lower()
            
            if len(parts) > 1:
                param = parts[1].strip()
            else:
                param = ""
                
            if command == "function" and param:
                print(f"\nAnalyzing function '{param}'...")
                result = query_engine.query_function(param)
                print(json.dumps(json.loads(result), indent=2))
                
            elif command == "symbol" and param:
                print(f"\nFinding symbol '{param}'...")
                locations = query_engine.find_symbol_locations(param)
                if locations:
                    print(f"Found {len(locations)} occurrences of '{param}':")
                    for i, loc in enumerate(locations, 1):
                        print(f"\n{i}. {loc['symbol_type'].upper()} in {loc['file_path']} (line {loc['line_number']}):")
                        print(f"   {loc['context']}")
                else:
                    print(f"Symbol '{param}' not found in the codebase.")
                    
            elif command == "search" and param:
                print(f"\nSearching for '{param}'...")
                result = query_engine.search_code(param)
                print(result)
                
            elif command == "structure":
                print("\nAnalyzing database structure...")
                result = query_engine.query_database_structure("Explain the overall database structure")
                print(result)
                
            elif command == "overview":
                print("\nGenerating codebase overview...")
                result = query_engine.analyze_codebase()
                print(result)
                
            elif command == "query" and param:
                print(f"\nProcessing query: '{param}'...")
                result = query_engine.conversational_query(param)
                print(result)
                
            else:
                print("Invalid command. Please try again.")
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()