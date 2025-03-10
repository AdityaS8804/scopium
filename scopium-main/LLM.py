import os
import json
import re
import traceback
from typing import Dict, List, Optional, Union, Any
from arango import ArangoClient
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from dotenv import load_dotenv

class EnhancedCodebaseQuery:
    def __init__(
        self,
        db_name: str = "_system",
        username: str = "root",
        password: str = "your_password",
        host: str = "https://your_host.arangodb.cloud:8529",
        mistral_api_key: Optional[str] = None,
        model: str = "mistral-large-latest",
        node: str = "your_node_collection",
        edge: str = "your_edge_collection",
        graph: str = "your_graph_name"
    ):
        """
        Enhanced initialization that better understands the graph structure.
        Args:
            db_name: ArangoDB database name
            username: ArangoDB username
            password: ArangoDB password
            host: ArangoDB host URL
            mistral_api_key: Mistral API key (if None, will try to get from environment)
            model: Mistral model to use
            node: Node collection name
            edge: Edge collection name
            graph: Graph name
        """
        # Connect to ArangoDB
        self.client = ArangoClient(hosts=host)
        self.db = self.client.db(db_name, username=username, password=password)
        
        # Connect to Mistral API
        if mistral_api_key is None:
            mistral_api_key = os.environ.get("MISTRAL_API_KEY")
        if mistral_api_key is None:
            raise ValueError("Mistral API key not provided and not found in environment")
        
        # Initialize Mistral client
        self.mistral_client = MistralClient(api_key=mistral_api_key)
        self.model = model
        
        # Graph name and collections
        self.graph = graph
        self.node = node
        self.edge = edge
        
        # Initialize file and snippet cache
        self.files = {}
        self.snippets = {}
        self.symbols = {}  # New cache for symbols
        
        # Database schema info - store the result of _db_schema() in self.db_schema
        self.db_schema = self._db_schema()
        
        # Get enhanced schema with node type understanding
        self.node_types = self.analyze_node_types()
        
        # Initialize cache
        self.initialize_cache()
        
        # Conversation history for contextual awareness
        self.conversation_history = []

    def analyze_node_types(self):
        """Analyze and cache the node types in the database"""
        node_types = {}
        try:
            # Query to find all distinct node types
            aql = f"""
            FOR v IN {self.node}
                COLLECT type = v.type
                RETURN {{
                    "type": type,
                    "count": COUNT(1)
                }}
            """
            cursor = self.db.aql.execute(aql)
            type_counts = [doc for doc in cursor]
            
            # For each node type, get a sample and analyze structure
            for type_info in type_counts:
                node_type = type_info.get('type')
                count = type_info.get('count', 0)
                
                # Skip if no type
                if not node_type:
                    continue
                
                # Get a sample for this node type
                aql = f"""
                FOR v IN {self.node}
                    FILTER v.type == '{node_type}'
                    LIMIT 1
                    RETURN v
                """
                cursor = self.db.aql.execute(aql)
                samples = [doc for doc in cursor]
                
                # Skip if no samples
                if not samples:
                    continue
                
                sample = samples[0]
                
                # Add to node types dictionary
                node_types[node_type] = {
                    'count': count,
                    'sample_structure': list(sample.keys()),
                    'sample': sample
                }
                
                print(f"Type: {node_type}, Count: {count}")
                print(f"Sample: {json.dumps(sample, indent=2)}")
                print("---")
                
        except Exception as e:
            print(f"Error analyzing node types: {str(e)}")
            traceback.print_exc()
            # Return an empty dict instead of None if there's an error
            return {}
        
        return node_types

    def initialize_cache(self):
        """Initialize cache of files, code snippets, and symbols"""
        try:
            # Query all files 
            aql = f"""
            FOR v IN {self.node}
                FILTER v.type == 'file'
                RETURN {{
                    "key": v._key,
                    "file_index": v.file_index, 
                    "directory": v.directory,
                    "file_name": v.file_name
                }}
            """
            cursor = self.db.aql.execute(aql)
            for doc in cursor:
                file_key = doc.get("file_index", doc.get("key"))
                directory = doc.get("directory", "")
                file_name = doc.get("file_name", "")
                file_path = f"{directory}/{file_name}" if directory and file_name else ""
                
                self.files[file_key] = {
                    "key": doc.get("key"),
                    "directory": directory,
                    "file_name": file_name,
                    "file_path": file_path
                }
            
            # Query all code snippets and their relationships to files
            aql = f"""
            FOR snippet IN {self.node}
                FILTER snippet.type == 'snippet'
                LET file_info = (
                    FOR edge IN {self.edge}
                        FILTER edge._to == snippet._id AND edge.edge_type == 'contains_snippet'
                        FOR file IN {self.node}
                            FILTER file._id == edge._from AND file.type == 'file'
                            RETURN {{
                                "file_key": file._key,
                                "directory": file.directory,
                                "file_name": file.file_name
                            }}
                )
                RETURN {{
                    "key": snippet._key,
                    "code": snippet.code_snippet,
                    "start_line": snippet.start_line,
                    "end_line": snippet.end_line,
                    "file_info": LENGTH(file_info) > 0 ? file_info[0] : null
                }}
            """
            cursor = self.db.aql.execute(aql)
            for doc in cursor:
                file_info = doc.get("file_info", {})
                file_key = file_info.get("file_key") if file_info else None
                directory = file_info.get("directory", "") if file_info else ""
                file_name = file_info.get("file_name", "") if file_info else ""
                file_path = f"{directory}/{file_name}" if directory and file_name else ""
                
                self.snippets[doc.get("key")] = {
                    "code": doc.get("code"),
                    "start_line": doc.get("start_line"),
                    "end_line": doc.get("end_line"),
                    "file_key": file_key,
                    "file_path": file_path
                }
                    
            # Cache symbols if they exist in the schema
            # Make sure we check if the key exists in a safe way
            if self.node_types and 'symbol' in self.node_types:
                aql = f"""
                FOR symbol IN {self.node}
                    FILTER symbol.type == 'symbol'
                    LET file_info = (
                        FOR edge IN {self.edge}
                            FILTER edge._to == symbol._id AND edge.edge_type == 'defines'
                            FOR file IN {self.node}
                                FILTER file._id == edge._from AND file.type == 'file'
                                RETURN {{
                                    "file_key": file._key,
                                    "directory": file.directory,
                                    "file_name": file.file_name
                                }}
                    )
                    RETURN {{
                        "key": symbol._key,
                        "symbol_type": symbol.symbol_type,
                        "line_number": symbol.line_number,
                        "context": symbol.context,
                        "docstring": symbol.docstring,
                        "file_info": LENGTH(file_info) > 0 ? file_info[0] : null
                    }}
                """
                cursor = self.db.aql.execute(aql)
                for doc in cursor:
                    file_info = doc.get("file_info", {})
                    file_key = file_info.get("file_key") if file_info else None
                    directory = file_info.get("directory", "") if file_info else ""
                    file_name = file_info.get("file_name", "") if file_info else ""
                    file_path = f"{directory}/{file_name}" if directory and file_name else ""
                    
                    self.symbols[doc.get("key")] = {
                        "symbol_type": doc.get("symbol_type"),
                        "line_number": doc.get("line_number"),
                        "context": doc.get("context"),
                        "docstring": doc.get("docstring", ""),
                        "file_key": file_key,
                        "file_path": file_path
                    }

            print(f"Initialized cache with {len(self.files)} files, {len(self.snippets)} code snippets, and {len(self.symbols)} symbols")
        except Exception as e:
            print(f"Error initializing cache: {str(e)}")
            traceback.print_exc()

    def _db_schema(self) -> Dict:
        """Get detailed schema information with better type understanding"""
        try:
            # Basic schema information as before
            collections = self.db.collections()
            collection_names = [c['name'] for c in collections if not c['name'].startswith('_')]
            
            # Get graphs
            graphs = self.db.graphs()
            graph_names = [g['name'] for g in graphs]
            graph_details = []
            
            for graph_name in graph_names:
                graph = self.db.graph(graph_name)
                graph_info = graph.properties()
                
                # Get edge definitions for better understanding of relationships
                edge_definitions = graph_info.get('edgeDefinitions', [])
                enhanced_edge_defs = []
                
                for edge_def in edge_definitions:
                    collection = edge_def.get('collection', '')
                    from_collections = edge_def.get('from', [])
                    to_collections = edge_def.get('to', [])
                    
                    # Sample some edges to understand relationship types
                    edge_samples = []
                    if collection:
                        try:
                            cursor = self.db.aql.execute(
                                f"FOR e IN {collection} LIMIT 5 RETURN e"
                            )
                            edge_samples = [edge for edge in cursor]
                        except Exception as e:
                            print(f"Error sampling edges from {collection}: {str(e)}")
                    
                    # Extract edge types if they exist
                    edge_types = set()
                    for edge in edge_samples:
                        if 'edge_type' in edge:
                            edge_types.add(edge['edge_type'])
                    
                    enhanced_edge_defs.append({
                        'collection': collection,
                        'from_collections': from_collections,
                        'to_collections': to_collections,
                        'edge_types': list(edge_types),
                        'sample_count': len(edge_samples),
                    })
                
                graph_details.append({
                    'name': graph_info.get('name'),
                    'edge_definitions': enhanced_edge_defs,
                    'orphan_collections': graph_info.get('orphanCollections', [])
                })
            
            # Enhanced node type analysis
            node_types = {}
            try:
                # Query to find all distinct node types
                aql = f"""
                FOR v IN {self.node}
                    COLLECT type = v.type
                    RETURN {{
                        "type": type,
                        "count": COUNT(1)
                    }}
                """
                cursor = self.db.aql.execute(aql)
                type_counts = [doc for doc in cursor]
                
                # For each node type, get a sample and analyze structure
                for type_info in type_counts:
                    node_type = type_info.get('type')
                    count = type_info.get('count', 0)
                    
                    # Skip if no type (shouldn't happen but just in case)
                    if not node_type:
                        continue
                    
                    # Get a sample for this node type
                    aql = f"""
                    FOR v IN {self.node}
                        FILTER v.type == '{node_type}'
                        LIMIT 1
                        RETURN v
                    """
                    cursor = self.db.aql.execute(aql)
                    samples = [doc for doc in cursor]
                    
                    # Skip if no samples
                    if not samples:
                        continue
                    
                    sample = samples[0]
                    
                    # Add to node types dictionary
                    node_types[node_type] = {
                        'count': count,
                        'sample_structure': list(sample.keys()),
                        'sample': sample
                    }
                
            except Exception as e:
                print(f"Error analyzing node types: {str(e)}")
                traceback.print_exc()
                
            # Enhancement: Analyze relationships between different node types
            type_relationships = []
            try:
                # For each node type pair, check if there are edges between them
                for from_type in node_types:
                    for to_type in node_types:
                        aql = f"""
                        FOR v1 IN {self.node}
                            FILTER v1.type == '{from_type}'
                            LIMIT 1
                            FOR v2 IN {self.node}
                                FILTER v2.type == '{to_type}'
                                LIMIT 1
                                FOR e IN {self.edge}
                                    FILTER e._from == v1._id AND e._to == v2._id
                                    RETURN DISTINCT {{
                                        "from_type": '{from_type}',
                                        "to_type": '{to_type}',
                                        "edge_type": e.edge_type
                                    }}
                        """
                        cursor = self.db.aql.execute(aql)
                        relationships = [doc for doc in cursor]
                        
                        for rel in relationships:
                            type_relationships.append(rel)
                
            except Exception as e:
                print(f"Error analyzing type relationships: {str(e)}")
                traceback.print_exc()
            
            return {
                "Graph Schema": graph_details,
                "Collection Schema": [c for c in collection_names],
                "Node Types": node_types,
                "Type Relationships": type_relationships
            }
        except Exception as e:
            print(f"Error getting enhanced schema: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}
        
    def find_symbol_locations(self, symbol_name: str) -> List[Dict]:
        """
        Find all occurrences of a symbol using both the symbol nodes and code snippets
        
        Args:
            symbol_name: The name of the symbol to search for
            
        Returns:
            List of dictionaries containing symbol location information
        """
        results = []
        
        try:
            print(f"Searching for symbol: {symbol_name}")
            
            # First, check for dedicated symbol nodes (more accurate)
            aql = f"""
            FOR v IN {self.node}
                FILTER v.type == 'symbol'
                FILTER CONTAINS(v.context, '{symbol_name}')
                
                // Get file information through relationships
                LET file_info = (
                    FOR file IN {self.node}
                    FILTER file.type == 'file'
                    FOR edge IN {self.edge}
                    FILTER edge._from == file._id AND edge._to == v._id
                    RETURN {{
                        "file_key": file._key,
                        "directory": file.directory,
                        "file_index": file.file_index
                    }}
                )
                
                RETURN {{
                    "symbol_name": '{symbol_name}',
                    "symbol_type": v.symbol_type,
                    "line_number": v.line_number,
                    "context": v.context,
                    "docstring": v.docstring,
                    "file_info": file_info[0]
                }}
            """
            
            cursor = self.db.aql.execute(aql)
            symbol_nodes = [doc for doc in cursor]
            
            for node in symbol_nodes:
                file_info = node.get("file_info", {})
                
                result = {
                    "symbol_name": symbol_name,
                    "symbol_type": node.get("symbol_type", "unknown"),
                    "file_key": file_info.get("file_key"),
                    "directory": file_info.get("directory", "Unknown"),
                    "file_index": file_info.get("file_index", "Unknown"),
                    "line_number": node.get("line_number"),
                    "context": node.get("context"),
                    "docstring": node.get("docstring", "")
                }
                
                print(f"Found symbol '{symbol_name}' in file {result['directory']} at line {result['line_number']}")
                results.append(result)
            
            # If no dedicated symbol nodes found or as a fallback, search in snippets
            if not results:
                print(f"No dedicated symbol nodes found for {symbol_name}, searching in snippets...")
                
                # Search for the symbol in cached snippets (your original approach)
                for snippet_key, snippet_data in self.snippets.items():
                    code = snippet_data.get("code", "")
                    if not code:
                        continue
                        
                    if symbol_name in code:
                        file_key = snippet_data.get("file_key")
                        file_data = None
                        
                        # Find the corresponding file
                        for file_index, file_info in self.files.items():
                            if file_info.get("key") == file_key:
                                file_data = file_info
                                break
                        
                        # If we still don't have file data, check edges
                        if not file_data:
                            # Try to find file through edges
                            aql = f"""
                            FOR edge IN {self.edge}
                            FILTER edge._to == '{self.node}/{snippet_key}'
                            FILTER edge.edge_type == 'contains_snippet'
                            LET file = DOCUMENT(edge._from)
                            RETURN file
                            """
                            cursor = self.db.aql.execute(aql)
                            files = [doc for doc in cursor]
                            if files:
                                file_data = {
                                    "key": files[0].get("_key"),
                                    "directory": files[0].get("directory"),
                                    "file_index": files[0].get("file_index")
                                }
                        
                        # Skip if we still don't have file info
                        if not file_data:
                            continue
                        
                        # Calculate line numbers for each occurrence
                        code_lines = code.split('\n')
                        line_offsets = []
                        
                        for i, line in enumerate(code_lines):
                            if symbol_name in line:
                                line_offsets.append(i)
                        
                        base_line = snippet_data.get("start_line", 1)
                        
                        for offset in line_offsets:
                            line_number = base_line + offset
                            
                            # Get context (3 lines above and below)
                            start_ctx = max(0, offset - 3)
                            end_ctx = min(len(code_lines), offset + 4)
                            context_lines = code_lines[start_ctx:end_ctx]
                            
                            result = {
                                "symbol_name": symbol_name,
                                "symbol_type": "unknown",  # Can't determine from snippet
                                "file_key": file_data.get("key"),
                                "directory": file_data.get("directory", "Unknown"),
                                "file_index": file_data.get("file_index", "Unknown"),
                                "line_number": line_number,
                                "context": "\n".join(context_lines)
                            }
                            
                            print(f"Found '{symbol_name}' in snippet in file {file_data.get('directory', 'Unknown')} at line {line_number}")
                            results.append(result)
                
            print(f"Found {len(results)} occurrences of '{symbol_name}'")
                    
        except Exception as e:
            print(f"Error finding symbol locations: {str(e)}")
            traceback.print_exc()
        
        return results

    def _get_file_by_key(self, file_key):
        """Helper method to retrieve file node by key"""
        try:
            aql = f"""
            FOR file IN {self.node}
            FILTER file._key == '{file_key}'
            RETURN file
            """
            cursor = self.db.aql.execute(aql)
            files = [doc for doc in cursor]
            return files[0] if files else None
        except Exception as e:
            print(f"Error getting file by key: {str(e)}")
            return None
    
    def find_function_by_name(self, function_name: str) -> List[Dict]:
        """Find function snippets by name with improved matching across all files"""
        results = []
        
        try:
            print(f"Searching for function '{function_name}'...")
            
            # Use a more comprehensive AQL query to get detailed file information
            aql = f"""
            FOR v IN {self.node}
                FILTER v.type == 'snippet'
                LET code = v.code_snippet
                FILTER CONTAINS(code, "def {function_name}") OR 
                    CONTAINS(code, "def {function_name} ")
                
                // Get the file information through relationships
                LET file_info = (
                    FOR file IN {self.node}
                    FILTER file.type == 'file'
                    FOR edge IN {self.edge}
                    FILTER edge._from == file._id AND edge._to == v._id
                    
                    // Try to get the file name by finding related nodes
                    LET file_name_info = (
                        FOR other_node IN {self.node}
                        FILTER other_node.type == 'symbol' OR other_node.type == 'snippet'
                        FOR other_edge IN {self.edge}
                        FILTER other_edge._from == file._id AND other_edge._to == other_node._id
                        FILTER other_node.type == 'symbol' AND HAS(other_node, 'context') AND CONTAINS(other_node.context, 'import')
                        SORT other_node.line_number ASC
                        LIMIT 1
                        RETURN other_node.context
                    )
                    
                    RETURN {{
                        "file_key": file._key,
                        "directory": file.directory,
                        "file_index": file.file_index,
                        "file_name_hint": file_name_info[0]
                    }}
                )
                
                RETURN {{
                    "key": v._key,
                    "code": code,
                    "start_line": v.start_line,
                    "end_line": v.end_line,
                    "file_info": file_info[0]
                }}
            """
            cursor = self.db.aql.execute(aql)
            
            # Also check the cached files to get more information
            file_details = {}
            for doc in cursor:
                code = doc.get("code")
                file_info = doc.get("file_info", {})
                
                # Check if it's a proper function definition
                if re.search(r'(?:^|\n)\s*(?:@\w+\s*(?:\(.*?\))?\s*\n\s*)*def\s+' + 
                            re.escape(function_name) + r'\s*\(', code, re.MULTILINE):
                    
                    # Extract docstring
                    docstring = ""
                    docstring_match = re.search(r'"""(.*?)"""', code, re.DOTALL)
                    if docstring_match:
                        docstring = docstring_match.group(1).strip()
                    
                    # Extract the function code
                    lines = code.split("\n")
                    function_lines = []
                    in_function = False
                    indent_level = 0
                    
                    for i, line in enumerate(lines):
                        # Look for the function definition
                        if not in_function and re.search(r'^\s*def\s+' + re.escape(function_name) + r'\s*\(', line):
                            in_function = True
                            indent_level = len(line) - len(line.lstrip())
                            j = i - 1
                            while j >= 0 and (lines[j].strip().startswith('@') or not lines[j].strip()):
                                function_lines.insert(0, lines[j])
                                j -= 1
                            function_lines.append(line)
                        elif in_function:
                            if line.strip() and len(line) - len(line.lstrip()) <= indent_level and not (
                                line.strip().startswith('#') or not line.strip()
                            ):
                                in_function = False
                            else:
                                function_lines.append(line)
                    
                    function_code = "\n".join(function_lines)
                    
                    # Get metadata
                    directory = file_info.get("directory", "Unknown")
                    file_index = file_info.get("file_index", "Unknown")
                    file_key = file_info.get("file_key", "Unknown")
                    start_line = doc.get("start_line")
                    end_line = doc.get("end_line")
                    
                    # Attempt to determine the filename using code analysis
                    file_name = "Unknown"
                    
                    # 1. Check if we can infer the filename from the first import statement
                    if "import flask" in code.lower() or "from flask" in code.lower():
                        module_match = re.search(r'from\s+flask\.(\w+)', code)
                        if module_match:
                            file_name = f"{module_match.group(1)}.py"
                    
                    # 2. Try to infer the filename from the directory structure or code content
                    if file_name == "Unknown" and directory != "Unknown":
                        # Check if the directory path has useful clues
                        parts = directory.split('/')
                        if parts and parts[-1] and not parts[-1].startswith('__'):
                            # If the last directory component is descriptive, use it
                            file_name = f"{parts[-1]}.py"
                    
                    # 3. Look for module-level docstrings that might indicate the file's purpose
                    module_docstring = re.search(r'^"""(.+?)"""', code, re.DOTALL)
                    if file_name == "Unknown" and module_docstring:
                        doc_text = module_docstring.group(1).lower()
                        # Extract potential module name from docstring
                        module_match = re.search(r'flask\.(\w+)', doc_text)
                        if module_match:
                            file_name = f"{module_match.group(1)}.py"
                    
                    # 4. Look for class or function names that match Flask naming patterns
                    if file_name == "Unknown":
                        class_match = re.search(r'class\s+(\w+)', code)
                        if class_match and 'flask' in code.lower():
                            class_name = class_match.group(1)
                            # Convert CamelCase to snake_case for potential filename
                            snake_case = ''.join(['_'+c.lower() if c.isupper() else c.lower() for c in class_name]).lstrip('_')
                            file_name = f"{snake_case}.py"
                    
                    # Store the file key and its details for later use
                    file_details[file_key] = {
                        "directory": directory,
                        "file_index": file_index,
                        "file_name": file_name,
                        "start_line": start_line,
                        "end_line": end_line
                    }
                    
                    # Log what we found
                    location = f"{directory}/{file_name}" if file_name != "Unknown" else directory
                    print(f"Found function '{function_name}' in file {location} at lines {start_line} - {end_line}")
                    
                    results.append({
                        "key": doc.get("key"),
                        "code": function_code,
                        "docstring": docstring,
                        "start_line": start_line,
                        "end_line": end_line,
                        "directory": directory,
                        "file_index": file_index,
                        "file_name": file_name,
                        "location": location
                    })
            
            # Additional step: Try to infer file names by examining contents/patterns of the entire repository
            # This is a heuristic approach based on common Flask codebase organization
            if all(result.get("file_name", "Unknown") == "Unknown" for result in results):
                # For get_root_path specifically, we know it's typically in helpers.py or utils.py
                if function_name == "get_root_path":
                    for i, result in enumerate(results):
                        if "helpers" in result.get("code", "").lower() or "util" in result.get("code", "").lower():
                            # It's most likely in helpers.py or utils.py based on Flask's structure
                            likely_file = "helpers.py" if "helpers" in result.get("code", "").lower() else "utils.py"
                            results[i]["file_name"] = likely_file
                            results[i]["location"] = f"{result['directory']}/{likely_file}"
                            print(f"Updated: Function '{function_name}' is likely in {results[i]['location']}")
            
            print(f"Found {len(results)} implementations of function '{function_name}'")
        except Exception as e:
            print(f"Error finding function by name: {str(e)}")
            traceback.print_exc()
        
        return results
    
    def query_function(self, function_name: str) -> str:
        """
        Query about a specific function and get an analysis in JSON format.
        Will return all implementations across different files.
        
        Args:
            function_name: Name of the function to analyze
            
        Returns:
            JSON-formatted analysis of the function across all files
        """
        # Find all function implementations across the codebase
        function_snippets = self.find_function_by_name(function_name)
        
        if not function_snippets:
            return json.dumps({
                "status": "not_found",
                "message": f"Function '{function_name}' not found in the codebase."
            }, indent=2)
        
        # Group implementations by file
        grouped_implementations = {}
        for snippet in function_snippets:
            file_path = snippet.get("file_path", "Unknown")
            if file_path not in grouped_implementations:
                grouped_implementations[file_path] = []
            grouped_implementations[file_path].append(snippet)
        
        # Prepare context for the LLM
        implementations_context = []
        for file_path, snippets in grouped_implementations.items():
            for snippet in snippets:
                implementations_context.append({
                    "file_path": file_path,
                    "code": snippet.get("code"),
                    "docstring": snippet.get("docstring"),
                    "start_line": snippet.get("start_line"),
                    "end_line": snippet.get("end_line")
                })
        
        # Print debug info
        print(f"Searching for function '{function_name}'...")
        print("Details of found implementations:")
        for impl in implementations_context:
            print(f"File: {impl['file_path']}")
            print(f"Lines: {impl['start_line']} - {impl['end_line']}")
            print(f"Docstring: {impl['docstring'][:100]}..." if len(impl.get('docstring', '')) > 100 else f"Docstring: {impl.get('docstring', '')}")
            print("---")
        
        # Format the context
        context = json.dumps(implementations_context, indent=2)
        
        # Prepare system prompt
        system_prompt = """You are an expert code analyzer assisting with a Python codebase.
You have access to information about functions, including their code and docstrings.
Analyze ALL provided implementations of the function across different files.
For each implementation, explain:
1. The purpose and functionality
2. Key parameters and return values
3. The file location and line numbers
4. Any differences between implementations

Format your response as a JSON object with the following structure:
{
  "status": "success",
  "function_name": "(function name)",
  "implementations": [
    {
      "file_path": "(file path)",
      "line_range": "(start line - end line)",
      "analysis": {
        "purpose": "(description of purpose)",
        "parameters": [{"name": "param1", "description": "description", "type": "type if known"}],
        "return_value": {"description": "description", "type": "type if known"}
      }
    },
    {
      // Another implementation...
    }
  ],
  "comparison": "(description of differences between implementations, if multiple exist)"
}

Focus on technical accuracy in your JSON response.
"""

        # Query the LLM
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=f"""
Here is information about all implementations of the function '{function_name}' across the codebase:
{context}

Please analyze each implementation and provide the analysis in the requested JSON format.
""")
        ]
        
        response = self.mistral_client.chat(
            model=self.model,
            messages=messages
        )
        
        return response.choices[0].message.content
    
    def analyze_error(self, error_message: str) -> str:
        """Analyze a specific error message in the codebase and suggest solutions."""
        try:
            print("Starting error analysis...")
            print(f"Error message: {error_message}")
            
            # Extract key information from the error message
            file_path_match = re.search(r'([a-zA-Z0-9_\-/.]+\.py)', error_message)
            line_number_match = re.search(r'\.py:(\d+):(\d+)', error_message)
            error_type_match = re.search(r'error: (.+?)(?:\n|$)', error_message)
            
            file_path = file_path_match.group(1) if file_path_match else "Unknown"
            line_info = f"line {line_number_match.group(1)}, column {line_number_match.group(2)}" if line_number_match else "Unknown location"
            error_type = error_type_match.group(1) if error_type_match else "Unknown error"
            
            print(f"Extracted file path: {file_path}")
            print(f"Extracted line info: {line_info}")
            print(f"Extracted error type: {error_type}")
            
            # Search for relevant code snippets
            snippets = []
            
            # Check which fields exist in the collection by examining schema
            collection_schema = next((col for col in self.db_schema["Collection Schema"] 
                                    if col["collection_name"] == self.node), None)
            
            if not collection_schema:
                print(f"Warning: Could not find schema for collection {self.node}")
                return f"Error: Could not find schema for node collection {self.node}"
            
            # Determine the field names based on schema
            properties = collection_schema.get("document_properties", [])
            has_type_field = any(prop["name"] == "type" for prop in properties)
            has_file_path_field = any(prop["name"] == "file_path" for prop in properties)
            has_path_field = any(prop["name"] == "path" for prop in properties)
            
            # Build the query dynamically based on available fields
            filter_conditions = []
            if has_type_field:
                filter_conditions.append('v.type == "file"')
            
            path_field = "file_path" if has_file_path_field else "path" if has_path_field else None
            if path_field and file_path != "Unknown":
                file_name = file_path.split('/')[-1]
                filter_conditions.append(f'CONTAINS(v.{path_field}, "{file_name}")')
            
            # Construct the AQL query
            filter_clause = " AND ".join(filter_conditions)
            aql = f"""
            FOR v IN {self.node}
                FILTER {filter_clause}
                RETURN v
            """
            
            print(f"Executing AQL query to find file: {aql}")
            cursor = self.db.aql.execute(aql)
            file_nodes = [doc for doc in cursor]
            print(f"Found {len(file_nodes)} file nodes")
            
            # Debug output to see what's in the nodes
            for i, node in enumerate(file_nodes):
                print(f"File node {i} keys: {list(node.keys())}")
                print(f"File node {i} values: {node}")
            
            # If we found the file, get snippets containing the relevant code
            if file_nodes:
                # Get the _key field from the first file node
                file_key = file_nodes[0].get("_key")
                if not file_key:
                    print("Warning: No _key field found in file node")
                    file_key = str(file_nodes[0].get("_id", "")).split('/')[-1]
                    print(f"Using extracted key from _id: {file_key}")
                
                print(f"Found file with key: {file_key}")
                
                # Examine the structure of snippet nodes
                snippet_field_check_aql = f"""
                FOR v IN {self.node}
                    FILTER v.type == 'snippet' OR v.ast_type == 'snippet'
                    LIMIT 1
                    RETURN v
                """
                cursor = self.db.aql.execute(snippet_field_check_aql)
                snippet_examples = [doc for doc in cursor]
                
                if snippet_examples:
                    print(f"Snippet example keys: {list(snippet_examples[0].keys())}")
                    
                    # Determine file reference field in snippets
                    file_ref_field = None
                    if "file_key" in snippet_examples[0]:
                        file_ref_field = "file_key"
                    elif "file_id" in snippet_examples[0]:
                        file_ref_field = "file_id"
                    
                    # Get snippets related to this file
                    snippet_filter = f"v.{file_ref_field} == '{file_key}'" if file_ref_field else "TRUE"
                    type_filter = "v.type == 'snippet'" if has_type_field else "TRUE"
                    
                    aql = f"""
                    FOR v IN {self.node}
                        FILTER {type_filter}
                        FILTER {snippet_filter}
                        RETURN {{
                            "key": v._key,
                            "code": v.code_snippet,
                            "start_line": v.start_line,
                            "end_line": v.end_line
                        }}
                    """
                    print(f"Executing AQL query to find snippets: {aql}")
                    cursor = self.db.aql.execute(aql)
                    file_snippets = [doc for doc in cursor]
                    print(f"Found {len(file_snippets)} file snippets")
                    
                    if file_snippets:
                        print(f"First snippet: {file_snippets[0]}")
                    
                    # Find the specific snippet containing the error line
                    if line_number_match:
                        error_line = int(line_number_match.group(1))
                        for snippet in file_snippets:
                            start_line = snippet.get("start_line", 0)
                            end_line = snippet.get("end_line", 0)
                            
                            if start_line <= error_line <= end_line:
                                snippets.append({
                                    "file_path": file_path,
                                    "code": snippet.get("code"),
                                    "start_line": start_line,
                                    "end_line": end_line,
                                    "error_line": error_line,
                                    "relative_line": error_line - start_line
                                })
                    print("SNIPPETS: ")
                    print(snippets)
            
            # If no specific line found or file not found, search for related code
            # Extract key terms from the error message
            if "Cannot access attribute" in error_message:
                attribute_match = re.search(r'Cannot access attribute "([^"]+)"', error_message)
                attribute = attribute_match.group(1) if attribute_match else ""
                
                class_match = re.search(r'for class "([^"]+)"', error_message)
                class_name = class_match.group(1) if class_match else ""
                
                if attribute and class_name:
                    # Search for the class definition
                    class_snippets = self.find_symbol_locations(class_name)
                    for loc in class_snippets:
                        if loc.get("symbol_type") == "class":
                            snippets.append({
                                "file_path": loc.get("file_path"),
                                "code": loc.get("context"),
                                "start_line": loc.get("line_number"),
                                "class_definition": True
                            })
                    
                    # Search for the attribute being used
                    attr_snippets = self.find_symbol_locations(attribute)
                    for loc in attr_snippets:
                        snippets.append({
                            "file_path": loc.get("file_path"),
                            "code": loc.get("context"),
                            "start_line": loc.get("line_number"),
                            "attribute_usage": True
                        })
            
            # Prepare context for the LLM
            context = {
                "error_details": {
                    "file_path": file_path,
                    "location": line_info,
                    "error_type": error_type,
                    "full_error": error_message
                },
                "relevant_snippets": snippets
            }
            
            # Prepare system prompt
            system_prompt = """You are an expert Python developer specializing in debugging and error resolution.
    You have been given information about a Python error and relevant code snippets from the codebase.
    Analyze the error and provide:
    1. A clear explanation of what's causing the error
    2. The specific code that's problematic
    3. A solution to fix the error, with code examples
    4. Any additional context or files that need to be checked

    Focus on being specific and technical in your solution.
    """

            # Query the LLM
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=f"""
    Here is information about a Python error:
    {json.dumps(context, indent=2)}

    Please analyze this error and provide a detailed solution.
    """)
            ]
            
            response = self.mistral_client.chat(
                model=self.model,
                messages=messages
            )
            
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error analyzing error message: {str(e)}")
            traceback.print_exc()
            return f"An error occurred while analyzing the error: {str(e)}"
    
    def query_database_structure(self, query: str) -> str:
        """
        Answer questions about the database structure.
        
        Args:
            query: Natural language query about the database
            
        Returns:
            Response about the database structure
        """
        # Update conversation history
        self.conversation_history.append({
            "role": "user",
            "content": query
        })
        
        # Prepare system prompt
        system_prompt = """You are a database expert assisting with understanding an ArangoDB database structure.
You have access to the schema information about collections, graphs, and their properties.
Answer the user's questions about the database structure based on this information.

Keep answers concise and informative, focusing on the specific aspects of the database the user is asking about.
"""

        # Prepare conversation context
        context = json.dumps(self.db_schema, indent=2)
        
        # Build messages including conversation history
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=f"""
Here is information about the database schema:
{context}

User query: {query}

Please provide a helpful answer about the database structure based on the schema information.
""")
        ]
        
        # Add conversation history for context
        if len(self.conversation_history) > 1:
            history_context = "Previous conversation:\n"
            for i in range(max(0, len(self.conversation_history) - 3), len(self.conversation_history) - 1):
                history_context += f"User: {self.conversation_history[i]['content']}\n"
            messages[1].content += f"\n\n{history_context}"
        
        response = self.mistral_client.chat(
            model=self.model,
            messages=messages
        )
        
        answer = response.choices[0].message.content
        
        # Update conversation history with response
        self.conversation_history.append({
            "role": "assistant",
            "content": answer
        })
        
        return answer
    
    def conversational_query(self, query: str) -> str:
        """
        Process natural language queries about the codebase.
        
        Args:
            query: Natural language query about the codebase
            
        Returns:
            Response to the query
        """
        # Update conversation history
        self.conversation_history.append({
            "role": "user",
            "content": query
        })
        
        # Prepare system prompt
        system_prompt = """You are an expert code analyst assisting with understanding a Python codebase.
    You have access to code snippets, function implementations, and database schema information.
    Based on the user's query, provide relevant information about the codebase.

    You can search for specific functions, analyze code patterns, or explain database structures.
    """

        # Create a brief summary of the codebase capabilities
        codebase_summary = {
            "total_files": len(self.files),
            "total_snippets": len(self.snippets),
            "db_collections": [coll["collection_name"] for coll in self.db_schema.get("Collection Schema", [])]
        }
        
        # Build messages including conversation history
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=f"""
    Codebase summary:
    {json.dumps(codebase_summary, indent=2)}

    Database schema summary:
    {json.dumps(self.db_schema, indent=2)[:1000]}... (truncated)

    User query: {query}

    If the user is asking about:
    1. A specific function - search for it using the find_function_by_name method
    2. Database structure - use the query_database_structure method
    3. Symbol locations - use find_symbol_locations
    4. General codebase structure - use search_code or analyze_codebase
    5. An error found in the code - use analyze_error
    6. General query - respond directly

    Determine what action to take and respond accordingly.
    """)
        ]
        
        # Add conversation history for context
        if len(self.conversation_history) > 1:
            history_context = "Previous conversation:\n"
            for i in range(max(0, len(self.conversation_history) - 3), len(self.conversation_history) - 1):
                history_context += f"User: {self.conversation_history[i]['content']}\n"
                if i < len(self.conversation_history) - 2:
                    history_context += f"Assistant: {self.conversation_history[i+1]['content'][:200]}...\n"
            messages[1].content += f"\n\n{history_context}"
        
        # First, determine the intent of the query
        intent_messages = messages.copy()
        intent_messages[1].content += "\n\nFirst, determine the category of this query (function_search, symbol_location, database_structure, error_analysis, or general)."
        
        intent_response = self.mistral_client.chat(
            model=self.model,
            messages=intent_messages
        )
        
        intent_text = intent_response.choices[0].message.content.lower()
        
        # Choose the appropriate method based on intent
        if "function_search" in intent_text or "function search" in intent_text:
            # Extract potential function name
            function_name_response = self.mistral_client.chat(
                model=self.model,
                messages=[
                    ChatMessage(role="system", content="Extract the function name from the query"),
                    ChatMessage(role="user", content=f"Query: {query}\nExtract just the function name, no other text.")
                ]
            )
            function_name = function_name_response.choices[0].message.content.strip()
            result = self.query_function(function_name)
            
        elif "symbol_location" in intent_text or "symbol location" in intent_text:
            # Extract potential symbol name
            symbol_name_response = self.mistral_client.chat(
                model=self.model,
                messages=[
                    ChatMessage(role="system", content="Extract the symbol name (function, class, variable) from the query"),
                    ChatMessage(role="user", content=f"Query: {query}\nExtract just the symbol name, no other text.")
                ]
            )
            symbol_name = symbol_name_response.choices[0].message.content.strip()
            locations = self.find_symbol_locations(symbol_name)
            result = json.dumps({"symbol": symbol_name, "locations": locations}, indent=2)
            
        elif "database_structure" in intent_text or "database structure" in intent_text:
            result = self.query_database_structure(query)
        
        elif "error_analysis" in intent_text or "error analysis" in intent_text or "code error" in intent_text:
            # The query contains an error message - extract it and use the analyze_error method
            result = self.analyze_error(query)
            
        else:
            # General query - let the LLM decide how to respond
            result = self.mistral_client.chat(
                model=self.model,
                messages=messages
            ).choices[0].message.content
        
        # Ensure result is not too large
        if isinstance(result, str) and len(result) > 8000:
            result = result[:8000] + "... (truncated)"
        
        # Update conversation history with response
        self.conversation_history.append({
            "role": "assistant",
            "content": result
        })
        
        return result

    def search_code(self, search_term: str) -> str:
        """
        Search for code containing a specific term.
        
        Args:
            search_term: Term to search for in code snippets
            
        Returns:
            Analysis of relevant code snippets
        """
        matching_snippets = []
        
        try:
            # First try the improved in-memory search
            for key, snippet in self.snippets.items():
                code = snippet.get("code", "")
                if code and search_term.lower() in code.lower():
                    matching_snippets.append({
                        "key": key,
                        "code": code,
                        "start_line": snippet.get("start_line"),
                        "end_line": snippet.get("end_line")
                    })
            
            # If no results, try direct database search with case-insensitive matching
            if not matching_snippets:
                aql = f"""
                FOR v IN {self.node}
                    FILTER v.type == 'snippet'
                    LET code = v.code_snippet
                    FILTER CONTAINS(LOWER(code), LOWER("{search_term}"))
                    
                    // Get the file information through relationships
                    LET file_info = (
                        FOR file IN {self.node}
                        FILTER file.type == 'file'
                        FOR edge IN {self.edge}
                        FILTER edge._from == file._id AND edge._to == v._id
                        RETURN {{
                            "file_key": file._key,
                            "directory": file.directory,
                            "file_path": file.file_path,
                            "file_name": file.file_name
                        }}
                    )
                    
                    RETURN {{
                        "key": v._key,
                        "code": code,
                        "start_line": v.start_line,
                        "end_line": v.end_line,
                        "file_info": file_info[0]
                    }}
                """
                cursor = self.db.aql.execute(aql)
                for doc in cursor:
                    matching_snippets.append({
                        "key": doc.get("key"),
                        "code": doc.get("code"),
                        "start_line": doc.get("start_line"),
                        "end_line": doc.get("end_line"),
                        "file_path": doc.get("file_info", {}).get("file_path", "Unknown"),
                        "file_name": doc.get("file_info", {}).get("file_name", "Unknown")
                    })
            
            if not matching_snippets:
                return f"No code snippets containing '{search_term}' were found."
            
            # Limit the number of snippets to avoid token limits
            if len(matching_snippets) > 5:
                matching_snippets = matching_snippets[:5]
                
            # Format the context
            context = json.dumps(matching_snippets, indent=2)
            
            # Prepare system prompt
            system_prompt = """You are an expert code analyzer assisting with a Python codebase.
You have found code snippets containing a specific search term.
Analyze these snippets and explain:
1. What the code does
2. How the search term is used in the context
3. Any patterns or insights you can identify from these snippets
4. The file locations where the term is found

Focus on clarity and technical accuracy in your explanation.
"""

            # Query the LLM
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=f"""
Here are code snippets containing the search term '{search_term}':
{context}

Please analyze these snippets and explain how '{search_term}' is used in the code.
""")
            ]
            
            response = self.mistral_client.chat(
                model=self.model,
                messages=messages
            )
            
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error searching code: {str(e)}")
            traceback.print_exc()
            return f"An error occurred while searching for '{search_term}': {str(e)}"
    
    def analyze_code(self, file_path: str = None, directory: str = None) -> Dict:
        """
        Analyze and visualize the structure of the code, either for a specific file or directory.
        
        Args:
            file_path: Optional specific file path to analyze
            directory: Optional directory to analyze
            
        Returns:
            Dictionary with code structure analysis
        """
        try:
            # Query filter based on input
            filter_condition = "TRUE"
            if file_path:
                filter_condition = f"v.file_path == '{file_path}' OR v.directory == '{file_path}'"
            elif directory:
                filter_condition = f"v.directory == '{directory}' OR STARTS_WITH(v.directory, '{directory}/')"
            
            # Get file nodes
            aql = f"""
            FOR v IN {self.node}
                FILTER v.type == 'file'
                FILTER {filter_condition}
                RETURN v
            """
            cursor = self.db.aql.execute(aql)
            file_nodes = [doc for doc in cursor]
            
            file_structures = []
            for file_node in file_nodes:
                file_key = file_node.get("_key")
                file_path = file_node.get("directory", "") + "/" + file_node.get("file_name", "unknown")
                
                # Get symbols in this file
                aql = f"""
                FOR v IN {self.node}
                    FILTER v.type == 'symbol'
                    FOR edge IN {self.edge}
                        FILTER edge._from == '{self.node}/{file_key}' AND edge._to == v._id
                        RETURN {{
                            "symbol_name": v.context,
                            "symbol_type": v.symbol_type,
                            "line_number": v.line_number,
                            "docstring": v.docstring
                        }}
                """
                cursor = self.db.aql.execute(aql)
                symbols = [doc for doc in cursor]
                
                # Categorize symbols by type
                categorized_symbols = {}
                for symbol in symbols:
                    symbol_type = symbol.get("symbol_type", "unknown")
                    if symbol_type not in categorized_symbols:
                        categorized_symbols[symbol_type] = []
                    categorized_symbols[symbol_type].append(symbol)
                
                # Get snippets in this file
                aql = f"""
                FOR v IN {self.node}
                    FILTER v.type == 'snippet'
                    FOR edge IN {self.edge}
                        FILTER edge._from == '{self.node}/{file_key}' AND edge._to == v._id
                        FILTER edge.edge_type == 'contains_snippet'
                        RETURN {{
                            "snippet_key": v._key,
                            "start_line": v.start_line,
                            "end_line": v.end_line
                        }}
                """
                cursor = self.db.aql.execute(aql)
                snippets = [doc for doc in cursor]
                
                # Get symbol relationships
                symbol_relations = []
                if len(symbols) > 0:
                    symbol_keys = [f"'{self.node}/{s['_key']}'" for s in symbols if '_key' in s]
                    if symbol_keys:
                        symbol_keys_str = ", ".join(symbol_keys)
                        aql = f"""
                        FOR edge IN {self.edge}
                            FILTER edge._from IN [{symbol_keys_str}] AND edge._to IN [{symbol_keys_str}]
                            LET from_symbol = DOCUMENT(edge._from)
                            LET to_symbol = DOCUMENT(edge._to)
                            RETURN {{
                                "relation_type": edge.edge_type,
                                "from_symbol": from_symbol.context,
                                "to_symbol": to_symbol.context
                            }}
                        """
                        cursor = self.db.aql.execute(aql)
                        symbol_relations = [doc for doc in cursor]
                
                file_structures.append({
                    "file_path": file_path,
                    "symbols_count": len(symbols),
                    "snippets_count": len(snippets),
                    "categorized_symbols": categorized_symbols,
                    "symbol_relationships": symbol_relations
                })
            
            # Get directory structure if analyzing a directory
            directory_structure = {}
            if directory:
                # Get all directories
                aql = f"""
                FOR v IN {self.node}
                    FILTER v.type == 'directory'
                    FILTER STARTS_WITH(v.directory, '{directory}')
                    RETURN DISTINCT v.directory
                """
                cursor = self.db.aql.execute(aql)
                directories = [doc for doc in cursor]
                
                # Count files in each directory
                for dir_path in directories:
                    aql = f"""
                    FOR v IN {self.node}
                        FILTER v.type == 'file'
                        FILTER v.directory == '{dir_path}'
                        COLLECT WITH COUNT INTO count
                        RETURN count
                    """
                    cursor = self.db.aql.execute(aql)
                    counts = [doc for doc in cursor]
                    file_count = counts[0] if counts else 0
                    
                    directory_structure[dir_path] = {
                        "file_count": file_count
                    }
            
            # Prepare Mermaid diagram code for visualizing the structure
            mermaid_code = "classDiagram\n"
            
            # Add files as classes
            for file_structure in file_structures:
                file_name = file_structure["file_path"].split("/")[-1]
                mermaid_code += f"    class {file_name} {{\n"
                
                # Add symbol categories as fields
                for symbol_type, symbols in file_structure.get("categorized_symbols", {}).items():
                    for symbol in symbols:
                        symbol_name = symbol.get("symbol_name", "").replace("\n", " ")
                        if len(symbol_name) > 30:
                            symbol_name = symbol_name[:27] + "..."
                        mermaid_code += f"        {symbol_type} {symbol_name}\n"
                
                mermaid_code += "    }\n"
            
            # Add relationships
            for file_structure in file_structures:
                for relation in file_structure.get("symbol_relationships", []):
                    from_symbol = relation.get("from_symbol", "").split("\n")[0].strip()
                    to_symbol = relation.get("to_symbol", "").split("\n")[0].strip()
                    relation_type = relation.get("relation_type", "")
                    
                    if from_symbol and to_symbol:
                        mermaid_code += f"    {from_symbol} --> {to_symbol} : {relation_type}\n"
            
            return {
                "file_count": len(file_structures),
                "file_structures": file_structures,
                "directory_structure": directory_structure,
                "mermaid_diagram": mermaid_code
            }
            
        except Exception as e:
            print(f"Error analyzing code structure: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}


# Example usage
if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    
    # Get Mistral API key from environment
    mistral_api_key = os.environ.get("MISTRAL_API_KEY")
    
    # Initialize client
    client = EnhancedCodebaseQuery(
        db_name="_system",
        username="root",
        password="cUZ0YaNdcwfUTw6VjRny",
        host="https://d2eeb8083350.arangodb.cloud:8529",
        mistral_api_key=mistral_api_key,
        model="mistral-large-latest",
        node="FlaskRepv1_node",
        edge="FlaskRepv1_node_to_FlaskRepv1_node",
        graph="FlaskRepv1"
    )
    
    # # 1. Example: Query about a specific function
    function_name = "from_prefixed_env"  # Replace with a function name in your codebase
    print(f"Searching for function '{function_name}'...")
    response = client.query_function(function_name)
    print(f"Analysis of function '{function_name}':")
    print(response)
    print("\n" + "-"*50 + "\n")
    
#    # 2. Example: Find symbol locations
    # symbol_name = "from_prefixed_env"  # Replace with a symbol in your codebase
    # print(f"Finding occurrences of symbol '{symbol_name}'...")
    # locations = client.find_symbol_locations(symbol_name)
    # print(f"Found {len(locations)} occurrences of '{symbol_name}':")
    # for location in locations[:3]:  # Show first 3 results
    #     print(f"- {location.get('file_path', 'Unknown')} (line {location.get('line_number', 'Unknown')})")
    # print("\n" + "-"*50 + "\n")
    
    # # 3. Example: Search for code containing a term
    # search_term = "werkzeug"  # Replace with a relevant term
    # print(f"Searching for term '{search_term}'...")
    # response = client.search_code(search_term)
    # print(f"Search results for '{search_term}':")
    # print(response)
    # print("\n" + "-"*50 + "\n")
    
    # 4. Example: Analyze codebase overview
    # print("Generating codebase overview...")
    # response = client.analyze_codebase()
    # print("Codebase Overview:")
    # print(response)
    # print("\n" + "-"*50 + "\n")
    
    # # 5. Example: Query about database structure
    # db_query = "What collections are in the database?"
    # print(f"Database structure query: '{db_query}'")
    # response = client.query_database_structure(db_query)
    # print("Database Structure Information:")
    # print(response)
    # print("\n" + "-"*50 + "\n")
    
    # 6. Example: Conversational query about the codebase
#     nl_query = """Pyright reports type errors for src/flask/helpers.py:

# flask/src/flask/helpers.py
#   flask/src/flask/helpers.py:590:27 - error: Cannot access attribute "get_filename" for class "Loader"
#     Attribute "get_filename" is unknown (reportAttributeAccessIssue)
# Command which was run:

# .venv/bin/pyright --pythonpath .venv/bin/python3 --project pyproject.toml
# Environment:

# Python version: 3.12
# Flask version: 3.1.0
# Tell me all the related code I need to solve this error."""
#     print(f"Processing query: '{nl_query}'")
#     response = client.conversational_query(nl_query)
#     print("Query Response:")
#     print(response)
#     print("\n" + "-"*50 + "\n")

    # # 7. Error message
    # error_message = """Pyright reports type errors for src/flask/helpers.py:
    # flask/src/flask/helpers.py:590:27 - error: Cannot access attribute "get_filename" for class "Loader"
    #   Attribute "get_filename" is unknown (reportAttributeAccessIssue)"""
    
    # print("Analyzing error...")
    # response = client.analyze_error(error_message)
    # print("Error Analysis:")
    # print(response)

    # client.explore_node_types()