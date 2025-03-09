import os
import json
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
        password: str = None,
        host: str = None,
        mistral_api_key: Optional[str] = None,
        model: str = "mistral-large-latest",
        graph: str = None
    ):
        """
        Initialize the codebase query system that dynamically discovers the graph structure.
        
        Args:
            db_name: ArangoDB database name
            username: ArangoDB username
            password: ArangoDB password
            host: ArangoDB host URL
            mistral_api_key: Mistral API key (if None, will try to get from environment)
            model: Mistral model to use
            graph: Graph name (if None, will try to discover the first available graph)
        """
        # Connect to ArangoDB
        if not host:
            host = os.environ.get("ARANGO_HOST", "http://localhost:8529")
        self.client = ArangoClient(hosts=host)
        
        if not password:
            password = os.environ.get("ARANGO_PASSWORD")
            if not password:
                raise ValueError("ArangoDB password not provided and not found in environment")
        
        self.db = self.client.db(db_name, username=username, password=password)
        
        # Connect to Mistral API
        if mistral_api_key is None:
            mistral_api_key = os.environ.get("MISTRAL_API_KEY")
        if mistral_api_key is None:
            raise ValueError("Mistral API key not provided and not found in environment")
        
        # Initialize Mistral client
        self.mistral_client = MistralClient(api_key=mistral_api_key)
        self.model = model
        
        # Dynamically discover graph structure
        self.graph_name = graph
        self.node_collection = None
        self.edge_collection = None
        
        # Discover graph structure
        self._discover_graph_structure()
        
        # Initialize caches
        self.files = {}
        self.snippets = {}
        self.symbols = {}
        
        # Get schema information
        self.db_schema = self._db_schema()
        
        # Analyze node types
        self.node_types = self._analyze_node_types()

        self.symbol_name_index = {}
        self.file_to_snippets = {}
        self.file_to_symbols = {}
        self.snippet_to_symbols = {}
        
        # Initialize cache
        self._initialize_cache()
        
        # Conversation history for contextual awareness
        self.conversation_history = []
    
    def _discover_graph_structure(self):
        """Dynamically discover the graph structure in ArangoDB with improved directory detection"""
        try:
            # Get graph object
            graph = self.db.graph(self.graph_name)
            graph_info = graph.properties()
            
            # Get the edge collection name from graph properties
            edge_definitions = graph_info.get('edgeDefinitions', [])
            
            # If no edge definitions exist, set defaults and retry
            if not edge_definitions:
                print(f"No edge definitions found, using default naming pattern")
                self.node_collection = f"{self.graph_name}_node"
                self.edge_collection = f"{self.graph_name}_node_to_{self.graph_name}_node"
                print(f"Using default collections: Nodes={self.node_collection}, Edges={self.edge_collection}")
                # Validate the schema to understand the field names
                self._validate_schema()
                return
            
            # Get the edge collection
            edge_def = edge_definitions[0]
            self.edge_collection = edge_def.get('collection')
            
            # Get node collection
            from_collections = edge_def.get('from', [])
            if not from_collections:
                # No 'from' collections, use defaults
                self.node_collection = f"{self.graph_name}_nodes"
                print(f"No 'from' collections found, using default node collection: {self.node_collection}")
            else:
                self.node_collection = from_collections[0]
            
            print(f"Using collections: Nodes={self.node_collection}, Edges={self.edge_collection}")
            
            # Validate the schema to understand the field names
            self._validate_schema()
        except Exception as e:
            print(f"Error discovering graph structure: {str(e)}")
            traceback.print_exc()
            raise

    def _validate_schema(self):
        """Validate the schema and identify the key field names used in this database"""
        try:
            # Sample nodes to understand the schema
            aql = f"""
            FOR v IN {self.node_collection}
            LIMIT 10
            RETURN v
            """
            cursor = self.db.aql.execute(aql)
            sample_nodes = [doc for doc in cursor]
            
            if not sample_nodes:
                raise ValueError(f"No nodes found in collection {self.node_collection}")
            
            # Identify the type field
            type_field_candidates = ['type', 'ast_type', 'node_type']
            self.type_field = None
            
            for field in type_field_candidates:
                for node in sample_nodes:
                    if field in node:
                        self.type_field = field
                        print(f"Found type field: {field}")
                        break
                if self.type_field:
                    break
                    
            if not self.type_field:
                print("Warning: Could not identify a type field in nodes")
            
            # Identify path field
            path_field_candidates = ['path', 'file_path', 'rel_path']
            self.path_field = None
            
            for field in path_field_candidates:
                for node in sample_nodes:
                    if field in node:
                        self.path_field = field
                        print(f"Found path field: {field}")
                        break
                if self.path_field:
                    break
            
            # Sample edges to understand relationship types
            aql = f"""
            FOR e IN {self.edge_collection}
            LIMIT 10
            RETURN e
            """
            cursor = self.db.aql.execute(aql)
            sample_edges = [doc for doc in cursor]
            
            # Identify edge type field
            edge_type_field_candidates = ['edge_type', 'relation', 'relationship', 'type']
            self.edge_type_field = None
            
            for field in edge_type_field_candidates:
                for edge in sample_edges:
                    if field in edge:
                        self.edge_type_field = field
                        print(f"Found edge type field: {field}")
                        break
                if self.edge_type_field:
                    break
            
            print(f"Schema validation complete: type_field={self.type_field}, path_field={self.path_field}, edge_type_field={self.edge_type_field}")
        
        except Exception as e:
            print(f"Error validating schema: {str(e)}")
            traceback.print_exc()

    def _validate_node_types(self):
        """Validate that all necessary node types are accessible in the graph"""
        try:
            # Check for directory nodes specifically
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER v.type == 'directory'
                LIMIT 1
                RETURN v
            """
            cursor = self.db.aql.execute(aql)
            directories = [doc for doc in cursor]
            
            if not directories:
                print("Warning: No directory nodes found in the collection.")
                # Try alternative fields
                alternative_fields = ['ast_type', 'node_type']
                for field in alternative_fields:
                    aql = f"""
                    FOR v IN {self.node_collection}
                        FILTER v.{field} == 'directory' OR v.{field} == 'Directory'
                        LIMIT 1
                        RETURN v
                    """
                    cursor = self.db.aql.execute(aql)
                    alternative_dirs = [doc for doc in cursor]
                    if alternative_dirs:
                        print(f"Found directory nodes using alternate field: {field}")
                        break
            else:
                print(f"Found directory nodes successfully")
                
            # Also check for edges that connect directories
            aql = f"""
            FOR e IN {self.edge_collection}
                FILTER e.edge_type == 'contains_directory'
                LIMIT 1
                RETURN e
            """
            cursor = self.db.aql.execute(aql)
            dir_edges = [doc for doc in cursor]
            
            if not dir_edges:
                print("Warning: No 'contains_directory' edges found in the edge collection.")
                # Try alternative edge types
                alt_edge_types = ['contains', 'has_directory', 'parent']
                for edge_type in alt_edge_types:
                    aql = f"""
                    FOR e IN {self.edge_collection}
                        FILTER e.edge_type == '{edge_type}' OR e.relation == '{edge_type}' OR e.relationship == '{edge_type}'
                        FOR v1 IN {self.node_collection}
                            FILTER v1._id == e._from
                            FOR v2 IN {self.node_collection}
                                FILTER v2._id == e._to
                                FILTER (v1.type == 'directory' OR v2.type == 'directory')
                                LIMIT 1
                                RETURN e
                    """
                    cursor = self.db.aql.execute(aql)
                    alt_dir_edges = [doc for doc in cursor]
                    if alt_dir_edges:
                        print(f"Found directory edges using alternate edge type: {edge_type}")
                        break
            else:
                print(f"Found directory edge relationships successfully")
                
        except Exception as e:
            print(f"Error validating node types: {str(e)}")
            # Not raising the exception here to allow the process to continue
    
    def _db_schema(self) -> Dict:
        """Get detailed schema information with better type understanding"""
        try:
            # Basic schema information
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
            
            return {
                "Graph Schema": graph_details,
                "Collection Schema": [c for c in collection_names],
                "Node Types": {},  # Will be filled by _analyze_node_types
                "Type Relationships": []  # Will be filled later
            }
        except Exception as e:
            print(f"Error getting enhanced schema: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}
    
    def _analyze_node_types(self):
        """Analyze and cache the node types in the database using the detected schema fields"""
        node_types = {}
        try:
            # Use the detected type field
            if not self.type_field:
                print("No type field detected, trying to infer node types from other properties")
                # Fallback logic to infer types
                return self._infer_node_types()
            
            # Query distinct node types
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER HAS(v, "{self.type_field}")
                COLLECT type = v.{self.type_field} WITH COUNT INTO count
                RETURN {{
                    "type": type,
                    "count": count
                }}
            """
            cursor = self.db.aql.execute(aql)
            type_counts = [doc for doc in cursor]
            
            # For each node type, get a sample and analyze structure
            for type_info in type_counts:
                node_type = type_info.get('type')
                count = type_info.get('count', 0)
                
                if not node_type:
                    continue
                
                # Get a sample for this node type
                aql = f"""
                FOR v IN {self.node_collection}
                    FILTER v.{self.type_field} == '{node_type}'
                    LIMIT 1
                    RETURN v
                """
                cursor = self.db.aql.execute(aql)
                samples = [doc for doc in cursor]
                
                if not samples:
                    continue
                
                sample = samples[0]
                
                # Normalize the node type name
                normalized_type = node_type

                
                # Add to node types dictionary
                node_types[normalized_type] = {
                    'count': count,
                    'field': self.type_field,
                    'sample_structure': list(sample.keys()),
                    'sample': sample
                }
                
                print(f"Type: {node_type}, Count: {count}")
            
            # Update the db_schema with node types
            self.db_schema["Node Types"] = node_types
            
            # Special handling for directories and files if not found
            for important_type in ['directory', 'file']:
                if important_type not in node_types:
                    self._detect_special_type(important_type, node_types)
                    
            return node_types
        except Exception as e:
            print(f"Error analyzing node types: {str(e)}")
            traceback.print_exc()
            return {}
    
    def _analyze_type_relationships(self, node_types):
        """Analyze relationships between different node types"""
        type_relationships = []
        try:
            node_type_keys = list(node_types.keys())
            
            # For each node type pair, check if there are edges between them
            for from_type in node_type_keys:
                for to_type in node_type_keys:
                    aql = f"""
                    FOR v1 IN {self.node_collection}
                        FILTER v1.type == '{from_type}'
                        LIMIT 1
                        FOR v2 IN {self.node_collection}
                            FILTER v2.type == '{to_type}'
                            LIMIT 1
                            FOR e IN {self.edge_collection}
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
            
            # Update db_schema with type relationships
            self.db_schema["Type Relationships"] = type_relationships
            
        except Exception as e:
            print(f"Error analyzing type relationships: {str(e)}")
            traceback.print_exc()

    def _detect_special_type(self, type_name, node_types):
        """Try to detect special types like directories and files if they weren't found by regular means"""
        try:
            # Different detection strategies based on type
            if type_name == 'directory':
                # Look for nodes with directory-like properties
                indicators = ['path', 'directory', 'dir_name', 'folder']
                filter_conditions = []
                
                for indicator in indicators:
                    filter_conditions.append(f'HAS(v, "{indicator}")')
                    
                if self.path_field:
                    # Add condition that path doesn't end with file extension
                    filter_conditions.append(f'NOT REGEX_TEST(v.{self.path_field}, "\\.[a-zA-Z0-9]+$")')
                
                filter_str = " OR ".join(filter_conditions)
                
                aql = f"""
                FOR v IN {self.node_collection}
                    FILTER {filter_str}
                    LIMIT 100
                    RETURN v
                """
                
            elif type_name == 'file':
                # Look for nodes with file-like properties
                indicators = ['file', 'file_name', 'filename']
                filter_conditions = []
                
                for indicator in indicators:
                    filter_conditions.append(f'HAS(v, "{indicator}")')
                    
                if self.path_field:
                    # Add condition that path ends with file extension
                    filter_conditions.append(f'REGEX_TEST(v.{self.path_field}, "\\.[a-zA-Z0-9]+$")')
                
                filter_str = " OR ".join(filter_conditions)
                
                aql = f"""
                FOR v IN {self.node_collection}
                    FILTER {filter_str}
                    LIMIT 100
                    RETURN v
                """
            
            cursor = self.db.aql.execute(aql)
            detected_nodes = [doc for doc in cursor]
            
            if detected_nodes:
                print(f"Detected {len(detected_nodes)} potential {type_name} nodes")
                
                # Use the first node as a sample
                sample = detected_nodes[0]
                
                node_types[type_name] = {
                    'count': len(detected_nodes),
                    'field': 'inferred',
                    'sample_structure': list(sample.keys()),
                    'sample': sample
                }
                
                print(f"Added inferred {type_name} type to node types")
            else:
                print(f"Could not detect any {type_name} nodes")
        
        except Exception as e:
            print(f"Error detecting {type_name} nodes: {str(e)}")

    def _build_directory_structure(self) -> Dict:
        """
        Build a hierarchical representation of the directory structure
        Returns:
            Dictionary representing the directory tree
        """
        directory_tree = {}
        
        try:
            # First, identify all directory nodes
            directory_field = 'type'
            if 'directory' in self.node_types:
                directory_field = self.node_types['directory'].get('field', 'type')
                
            # Get all directory nodes
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER v.{directory_field} == 'directory'
                RETURN {{
                    "key": v._key,
                    "path": v.path,
                    "name": v.name
                }}
            """
            cursor = self.db.aql.execute(aql)
            directories = [doc for doc in cursor]
            
            # If no explicit directory nodes found, try to extract directories from file paths
            if not directories:
                # Extract directories from file paths
                all_directories = set()
                for file_info in self.files.values():
                    file_path = file_info.get("file_path", "")
                    if file_path:
                        # Extract all parent directories
                        parts = file_path.split('/')
                        for i in range(1, len(parts)):
                            dir_path = '/'.join(parts[:i])
                            if dir_path:
                                all_directories.add(dir_path)
                
                # Create synthetic directory nodes
                directories = [{"path": dir_path, "name": dir_path.split('/')[-1]} for dir_path in all_directories]
                
            # Build directory tree
            for directory in directories:
                path = directory.get("path", "")
                if not path:
                    continue
                    
                # Add to tree
                current = directory_tree
                parts = path.split('/')
                for i, part in enumerate(parts):
                    if not part:
                        continue
                        
                    if part not in current:
                        current[part] = {"files": [], "dirs": {}}
                        
                    if i == len(parts) - 1:
                        # This is the target directory, add its key
                        current[part]["key"] = directory.get("key")
                    else:
                        current = current[part]["dirs"]
                        
            # Add files to their respective directories
            for file_key, file_info in self.files.items():
                file_path = file_info.get("file_path", "")
                if not file_path:
                    continue
                    
                # Determine directory path and file name
                parts = file_path.split('/')
                file_name = parts[-1]
                dir_path = '/'.join(parts[:-1])
                
                # Find directory in tree
                current = directory_tree
                if dir_path:
                    found = True
                    for part in dir_path.split('/'):
                        if not part:
                            continue
                        if part in current:
                            current = current[part]["dirs"]
                        else:
                            # Directory not found in tree, create it
                            found = False
                            break
                            
                    if not found:
                        # Create missing directory path
                        current = directory_tree
                        for part in dir_path.split('/'):
                            if not part:
                                continue
                            if part not in current:
                                current[part] = {"files": [], "dirs": {}}
                            current = current[part]["dirs"]
                
                # Find parent directory and add file
                parent = current
                for part in parts[:-1]:
                    if not part:
                        continue
                    if part not in parent:
                        parent[part] = {"files": [], "dirs": {}}
                    parent = parent[part]["dirs"]
                
                # Add file to parent directory
                if parts[-2] in parent:
                    parent[parts[-2]]["files"].append({
                        "key": file_key,
                        "name": file_name,
                        "path": file_path,
                        "language": file_info.get("language", "")
                    })
        
        except Exception as e:
            print(f"Error building directory structure: {str(e)}")
            traceback.print_exc()
            
        return directory_tree
    
    def _initialize_cache(self):
        """Initialize cache of files, code snippets, and symbols using detected schema fields"""
        try:
            # Initialize file cache
            if 'file' in self.node_types:
                # Determine best field for file info
                field_info = self.node_types['file']
                
                path_field = None
                name_field = None
                
                # Try to find the best fields for path and name
                sample = field_info.get('sample', {})
                for field in sample:
                    lower_field = field.lower()
                    if 'path' in lower_field and not path_field:
                        path_field = field
                    elif ('name' in lower_field or 'file' in lower_field) and 'path' not in lower_field and not name_field:
                        name_field = field
                
                # Use detected fields or defaults
                path_field = path_field or self.path_field or 'path'
                name_field = name_field or 'file_name'
                type_field = field_info.get('field') or self.type_field or 'type'
                
                aql = f"""
                FOR v IN {self.node_collection}
                    FILTER v.{type_field} == 'file'
                    RETURN v
                """
                cursor = self.db.aql.execute(aql)
                
                # Process each file
                for doc in cursor:
                    file_key = doc.get('_key')
                    file_path = doc.get(path_field, "")
                    file_name = doc.get(name_field, "")
                    
                    if not file_path and not file_name:
                        continue
                    
                    if not file_path and file_name:
                        # Try to construct a path
                        for key in doc:
                            if 'dir' in key.lower() or 'folder' in key.lower():
                                directory = doc.get(key, "")
                                file_path = f"{directory}/{file_name}" if directory else file_name
                                break
                    
                    language = ""
                    # Try to detect language from extension
                    if file_path:
                        ext = file_path.split('.')[-1].lower() if '.' in file_path else ""
                        if ext == 'py':
                            language = 'python'
                        elif ext in ['js', 'ts']:
                            language = 'javascript'
                        elif ext in ['java']:
                            language = 'java'
                        elif ext in ['c', 'cpp', 'h', 'hpp']:
                            language = 'c/c++'
                    
                    self.files[file_key] = {
                        "key": file_key,
                        "file_name": file_name,
                        "file_path": file_path,
                        "language": language
                    }
                
                print(f"Cached {len(self.files)} files")
                
            # Initialize snippet cache
            if 'snippet' in self.node_types:
                # Determine best fields for snippet info
                field_info = self.node_types['snippet']
                
                content_field = None
                name_field = None
                
                # Try to find the best fields for content and name
                sample = field_info.get('sample', {})
                for field in sample:
                    lower_field = field.lower()
                    if ('content' in lower_field or 'code' in lower_field) and not content_field:
                        content_field = field
                    elif ('name' in lower_field or 'title' in lower_field) and not name_field:
                        name_field = field
                
                # Use detected fields or defaults
                content_field = content_field or 'content'
                name_field = name_field or 'snippet_name'
                type_field = field_info.get('field') or self.type_field or 'type'
                
                aql = f"""
                FOR v IN {self.node_collection}
                    FILTER v.{type_field} == 'snippet'
                    RETURN v
                """
                cursor = self.db.aql.execute(aql)
                
                # Process each snippet
                for doc in cursor:
                    snippet_key = doc.get('_key')
                    content = doc.get(content_field, "")
                    snippet_name = doc.get(name_field, "")
                    
                    if not content:
                        continue
                    
                    # Try to determine file relationship
                    file_key = None
                    for key in doc:
                        if 'file' in key.lower() and key != name_field:
                            file_key = doc.get(key)
                            break
                    
                    # Try to determine language
                    language = ""
                    for key in doc:
                        if 'lang' in key.lower():
                            language = doc.get(key, "")
                            break
                    
                    if not language and file_key in self.files:
                        language = self.files[file_key].get('language', "")
                    
                    self.snippets[snippet_key] = {
                        "key": snippet_key,
                        "snippet_name": snippet_name,
                        "content": content,
                        "file_key": file_key,
                        "language": language
                    }
                
                print(f"Cached {len(self.snippets)} code snippets")
            
                # Initialize symbol cache
                if 'symbol' in self.node_types:  # This is checking for an exact match with 'symbol'
                    # Determine best fields for symbol info
                    field_info = self.node_types['symbol']
                    
                    name_field = None
                    type_name_field = None
                    
                    # Try to find the best fields for symbol name and symbol type
                    sample = field_info.get('sample', {})
                    for field in sample:
                        lower_field = field.lower()
                        if 'name' in lower_field and not name_field:
                            name_field = field
                        elif ('type' in lower_field and 'name' in lower_field) and not type_name_field:
                            type_name_field = field
                    
                    # Add fallback detection for symbol name field
                    if not name_field and 'context' in sample:
                        name_field = 'context'
                        print(f"Using 'context' as fallback for symbol name field")
                    
                    # Use detected fields or defaults
                    name_field = name_field or 'symbol_name'
                    type_name_field = type_name_field or 'symbol_type'
                    type_field = field_info.get('field') or self.type_field or 'type'
                    
                    print(f"Using name_field: {name_field}, type_field: {type_field}")
                    
                    aql = f"""
                    FOR v IN {self.node_collection}
                        FILTER v.{type_field} == 'symbol'
                        RETURN v
                    """
                    print(f"Symbol query: {aql}")
                    cursor = self.db.aql.execute(aql)
                    sample_symbols = [doc for doc in cursor]
                    print(f"Sample symbol count: {len(sample_symbols)}")
                    
                    if sample_symbols:
                        print(f"Sample symbol fields: {list(sample_symbols[0].keys())}")
                        print(f"Sample symbol name value: {sample_symbols[0].get(name_field, 'NOT FOUND')}")
                        print(f"Sample symbol type value: {sample_symbols[0].get(type_name_field, 'NOT FOUND')}")

                    # Re-execute the query
                    cursor = self.db.aql.execute(aql)
                    
                    # Process counter
                    processed_count = 0
                    
                    # Process each symbol
                    for doc in cursor:
                        symbol_key = doc.get('_key')
                        symbol_name = doc.get(name_field, "")
                        symbol_type = doc.get(type_name_field, "")
                        
                        if not symbol_name:
                            # Try context as a fallback
                            symbol_name = doc.get('context', "")
                            if not symbol_name:
                                continue
                        
                        # Try to determine file relationship
                        file_key = None
                        for key in doc:
                            if 'file' in key.lower() and key != name_field:
                                file_key = doc.get(key)
                                break
                        
                        # Try to determine snippet relationship
                        snippet_key = None
                        for key in doc:
                            if 'snippet' in key.lower():
                                snippet_key = doc.get(key)
                                break
                        
                        # Try to get definition and documentation
                        definition = ""
                        documentation = doc.get('docstring', "")  # Try the known docstring field first
                        
                        for key in doc:
                            lower_key = key.lower()
                            if 'def' in lower_key or 'decl' in lower_key:
                                definition = doc.get(key, "")
                            elif ('doc' in lower_key or 'comment' in lower_key) and not documentation:
                                documentation = doc.get(key, "")
                        
                        self.symbols[symbol_key] = {
                            "key": symbol_key,
                            "symbol_name": symbol_name,
                            "symbol_type": symbol_type,
                            "file_key": file_key,
                            "snippet_key": snippet_key,
                            "definition": definition,
                            "documentation": documentation
                        }
                        
                        # Index by name for quick lookups
                        if symbol_name:
                            if symbol_name not in self.symbol_name_index:
                                self.symbol_name_index[symbol_name] = []
                            self.symbol_name_index[symbol_name].append(symbol_key)
                        
                        processed_count += 1
                        if processed_count % 200 == 0:
                            print(f"Processed {processed_count} symbols so far")
                    
                    print(f"Cached {len(self.symbols)} symbols")
                
            # Build relationship indexes for faster traversal
            self._build_relationship_indexes()
        
        except Exception as e:
            print(f"Error initializing cache: {str(e)}")
            traceback.print_exc()

    def _build_relationship_indexes(self):
        """Build indexes for quick relationship lookup between files, snippets and symbols"""
        try:
            # Build file -> snippets index
            for snippet_key, snippet in self.snippets.items():
                file_key = snippet.get('file_key')
                if file_key:
                    if file_key not in self.file_to_snippets:
                        self.file_to_snippets[file_key] = []
                    self.file_to_snippets[file_key].append(snippet_key)
            
            # Build file -> symbols index
            for symbol_key, symbol in self.symbols.items():
                file_key = symbol.get('file_key')
                if file_key:
                    if file_key not in self.file_to_symbols:
                        self.file_to_symbols[file_key] = []
                    self.file_to_symbols[file_key].append(symbol_key)
            
            # Build snippet -> symbols index
            for symbol_key, symbol in self.symbols.items():
                snippet_key = symbol.get('snippet_key')
                if snippet_key:
                    if snippet_key not in self.snippet_to_symbols:
                        self.snippet_to_symbols[snippet_key] = []
                    self.snippet_to_symbols[snippet_key].append(symbol_key)
            
            print("Built relationship indexes for files, snippets, and symbols")
        
        except Exception as e:
            print(f"Error building relationship indexes: {str(e)}")
            traceback.print_exc()

    def get_file_by_key(self, file_key: str) -> Dict:
        """
        Helper method to retrieve file node by key
        
        Args:
            file_key: The key of the file node
            
        Returns:
            Dict containing file information
        """
        if file_key in self.files:
            return self.files[file_key]
        
        try:
            aql = f"""
            FOR file IN {self.node_collection}
                FILTER file._key == '{file_key}' AND file.type == 'file'
                RETURN {{
                    "key": file._key,
                    "directory": file.directory,
                    "file_name": file.file_name,
                    "file_path": file.path || (file.directory + '/' + file.file_name),
                    "language": file.language
                }}
            """
            cursor = self.db.aql.execute(aql)
            files = [doc for doc in cursor]
            
            if files:
                self.files[file_key] = files[0]
                return files[0]
            
            return {}
        except Exception as e:
            print(f"Error retrieving file by key: {str(e)}")
            traceback.print_exc()
            return {}

    def find_symbol_occurrences(self, symbol_name: str) -> List[Dict]:
        """
        Find all occurrences of a symbol using both the symbol nodes and code snippets
        
        Args:
            symbol_name: The name of the symbol to find
            
        Returns:
            List of dictionaries containing symbol occurrences
        """
        results = []
        
        try:
            # Look for symbol nodes
            if 'symbol' in self.node_types:
                aql = f"""
                FOR symbol IN {self.node_collection}
                    FILTER symbol.type == 'symbol' AND symbol.name == '{symbol_name}'
                    LET file = (
                        FOR edge IN {self.edge_collection}
                            FILTER edge._to == symbol._id
                            FOR file IN {self.node_collection}
                                FILTER file._id == edge._from AND file.type == 'file'
                                RETURN {{
                                    "key": file._key,
                                    "directory": file.directory,
                                    "file_name": file.file_name,
                                    "file_path": file.path || (file.directory + '/' + file.file_name),
                                    "language": file.language
                                }}
                    )
                    RETURN {{
                        "type": "symbol",
                        "name": symbol.name,
                        "symbol_type": symbol.symbol_type,
                        "line_number": symbol.line_number,
                        "context": symbol.context,
                        "docstring": symbol.docstring,
                        "file": LENGTH(file) > 0 ? file[0] : null
                    }}
                """
                cursor = self.db.aql.execute(aql)
                symbol_results = [doc for doc in cursor]
                results.extend(symbol_results)
            
            # Look for symbol occurrences in code snippets
            if 'snippet' in self.node_types:
                # Determine the best attribute for code based on the sample
                code_field = 'code_snippet'
                snippet_sample = self.node_types.get('snippet', {}).get('sample', {})
                
                if 'code_snippet' in snippet_sample:
                    code_field = 'code_snippet'
                elif 'code' in snippet_sample:
                    code_field = 'code'
                elif 'snippet' in snippet_sample:
                    code_field = 'snippet'
                
                aql = f"""
                FOR snippet IN {self.node_collection}
                    FILTER snippet.type == 'snippet' AND snippet.{code_field} LIKE '%{symbol_name}%'
                    LET file = (
                        FOR edge IN {self.edge_collection}
                            FILTER edge._to == snippet._id
                            FOR file IN {self.node_collection}
                                FILTER file._id == edge._from AND file.type == 'file'
                                RETURN {{
                                    "key": file._key,
                                    "directory": file.directory,
                                    "file_name": file.file_name,
                                    "file_path": file.path || (file.directory + '/' + file.file_name),
                                    "language": file.language
                                }}
                    )
                    RETURN {{
                        "type": "snippet",
                        "code": snippet.{code_field},
                        "start_line": snippet.start_line,
                        "end_line": snippet.end_line,
                        "file": LENGTH(file) > 0 ? file[0] : null
                    }}
                """
                cursor = self.db.aql.execute(aql)
                snippet_results = [doc for doc in cursor]
                results.extend(snippet_results)
        
        except Exception as e:
            print(f"Error finding symbol occurrences: {str(e)}")
            traceback.print_exc()
        
        return results

    def find_by_name(self, name: str, symbol_type: Optional[str] = None) -> List[Dict]:
        """
        Find function/class snippets by name with improved matching across all files
        
        Args:
            name: The name of the function/class to find
            symbol_type: Optional filter for symbol type (e.g., 'function', 'class')
            
        Returns:
            List of dictionaries containing matching symbols and snippets
        """
        results = []
        
        try:
            # Look for symbol nodes first
            if 'symbol' in self.node_types:
                type_filter = f" AND symbol.symbol_type == '{symbol_type}'" if symbol_type else ""
                
                aql = f"""
                FOR symbol IN {self.node_collection}
                    FILTER symbol.type == 'symbol' AND symbol.name == '{name}'{type_filter}
                    LET file = (
                        FOR edge IN {self.edge_collection}
                            FILTER edge._to == symbol._id
                            FOR file IN {self.node_collection}
                                FILTER file._id == edge._from AND file.type == 'file'
                                RETURN {{
                                    "key": file._key,
                                    "directory": file.directory,
                                    "file_name": file.file_name,
                                    "file_path": file.path || (file.directory + '/' + file.file_name),
                                    "language": file.language
                                }}
                    )
                    LET snippet = (
                        FOR edge IN {self.edge_collection}
                            FILTER edge._from == symbol._id
                            FOR snippet IN {self.node_collection}
                                FILTER snippet._id == edge._to AND snippet.type == 'snippet'
                                RETURN snippet
                    )
                    RETURN {{
                        "type": "symbol",
                        "name": symbol.name,
                        "symbol_type": symbol.symbol_type,
                        "line_number": symbol.line_number,
                        "context": symbol.context,
                        "docstring": symbol.docstring,
                        "file": LENGTH(file) > 0 ? file[0] : null,
                        "snippet": LENGTH(snippet) > 0 ? snippet[0] : null
                    }}
                """
                cursor = self.db.aql.execute(aql)
                symbol_results = [doc for doc in cursor]
                results.extend(symbol_results)
            
            # If no symbols found or symbol cache is empty, try fuzzy matching in snippets
            if not results and 'snippet' in self.node_types:
                # Determine the best attribute for code based on the sample
                code_field = 'code_snippet'
                snippet_sample = self.node_types.get('snippet', {}).get('sample', {})
                
                if 'code_snippet' in snippet_sample:
                    code_field = 'code_snippet'
                elif 'code' in snippet_sample:
                    code_field = 'code'
                elif 'snippet' in snippet_sample:
                    code_field = 'snippet'
                
                # Common patterns for function/class definitions in different languages
                patterns = []
                
                if not symbol_type or symbol_type == 'function':
                    patterns.extend([
                        f"function {name}",  # JavaScript
                        f"def {name}",       # Python
                        f"{name} = function", # JavaScript
                        f"const {name} = ", # JavaScript arrow function
                        f"let {name} = ",   # JavaScript arrow function
                        f"var {name} = ",   # JavaScript arrow function
                        f"{name}\\(",       # C/C++/Java method
                        f"func {name}",     # Go
                    ])
                
                if not symbol_type or symbol_type == 'class':
                    patterns.extend([
                        f"class {name}",     # Python/JavaScript/Java
                        f"interface {name}", # TypeScript/Java
                        f"struct {name}",    # C/C++/Go
                        f"type {name} struct", # Go
                    ])
                
                # Create LIKE conditions for each pattern
                like_conditions = [f"snippet.{code_field} LIKE '%{pattern}%'" for pattern in patterns]
                like_filter = " OR ".join(like_conditions)
                
                aql = f"""
                FOR snippet IN {self.node_collection}
                    FILTER snippet.type == 'snippet' AND ({like_filter})
                    LET file = (
                        FOR edge IN {self.edge_collection}
                            FILTER edge._to == snippet._id
                            FOR file IN {self.node_collection}
                                FILTER file._id == edge._from AND file.type == 'file'
                                RETURN {{
                                    "key": file._key,
                                    "directory": file.directory,
                                    "file_name": file.file_name,
                                    "file_path": file.path || (file.directory + '/' + file.file_name),
                                    "language": file.language
                                }}
                    )
                    RETURN {{
                        "type": "snippet",
                        "code": snippet.{code_field},
                        "start_line": snippet.start_line,
                        "end_line": snippet.end_line,
                        "file": LENGTH(file) > 0 ? file[0] : null
                    }}
                """
                cursor = self.db.aql.execute(aql)
                snippet_results = [doc for doc in cursor]
                results.extend(snippet_results)
        
        except Exception as e:
            print(f"Error finding by name: {str(e)}")
            traceback.print_exc()
        
        return results

    def analyze_symbol(self, name: str, symbol_type: Optional[str] = None) -> Dict:
        """
        Query about a specific function/class and get an analysis in JSON format.
        Will return all implementations across different files.
        
        Args:
            name: The name of the function/class to analyze
            symbol_type: Optional filter for symbol type (e.g., 'function', 'class')
            
        Returns:
            Dictionary containing analysis of the symbol
        """
        # First, find all occurrences
        occurrences = self.find_by_name(name, symbol_type)
        
        if not occurrences:
            return {"error": f"No {symbol_type or 'symbol'} named '{name}' found in the codebase"}
        
        # Extract code snippets and organize by file
        implementations_by_file = {}
        for occurrence in occurrences:
            file_info = occurrence.get("file", {})
            file_path = file_info.get("file_path", "unknown_path")
            
            if file_path not in implementations_by_file:
                implementations_by_file[file_path] = {
                    "file_info": file_info,
                    "implementations": []
                }
            
            if occurrence.get("type") == "symbol":
                # For symbol occurrence, get its snippet
                snippet = occurrence.get("snippet", {})
                implementations_by_file[file_path]["implementations"].append({
                    "type": occurrence.get("symbol_type", "unknown"),
                    "name": occurrence.get("name", name),
                    "line_number": occurrence.get("line_number"),
                    "docstring": occurrence.get("docstring", ""),
                    "context": occurrence.get("context", ""),
                    "code": snippet.get("code_snippet", snippet.get("code", snippet.get("snippet", "")))
                })
            elif occurrence.get("type") == "snippet":
                # For snippet occurrence
                implementations_by_file[file_path]["implementations"].append({
                    "type": symbol_type or "unknown",
                    "name": name,
                    "line_number": occurrence.get("start_line"),
                    "code": occurrence.get("code", "")
                })
        
        # Use Mistral LLM to analyze the symbol
        symbol_analysis = self._analyze_with_llm(name, symbol_type, implementations_by_file)
        
        return {
            "name": name,
            "type": symbol_type or "unknown",
            "implementations_count": len(occurrences),
            "files_count": len(implementations_by_file),
            "implementations_by_file": implementations_by_file,
            "analysis": symbol_analysis
        }

    def _analyze_with_llm(self, name: str, symbol_type: Optional[str], implementations: Dict) -> Dict:
        """
        Use Mistral API to analyze a symbol based on its implementations
        
        Args:
            name: The name of the symbol to analyze
            symbol_type: The type of the symbol (function, class, etc.)
            implementations: Dictionary with implementations by file
            
        Returns:
            Dictionary with LLM analysis
        """
        try:
            # Extract all code snippets from implementations
            all_code = []
            for file_path, file_data in implementations.items():
                for implementation in file_data["implementations"]:
                    code = implementation.get("code", "")
                    docstring = implementation.get("docstring", "")
                    if code:
                        all_code.append(f"File: {file_path}\n{code}")
                    if docstring:
                        all_code.append(f"Docstring: {docstring}")
            
            # Join all code with separators
            code_text = "\n\n" + "-" * 40 + "\n\n".join(all_code)
            
            # Create a prompt for the LLM
            prompt = f"""
            Please analyze this {symbol_type or 'symbol'} named '{name}' from a codebase:
            
            {code_text}
            
            Provide a JSON response with the following fields:
            1. purpose: A clear description of what this {symbol_type or 'symbol'} does
            2. parameters: List of parameters with their types and purpose (if applicable)
            3. return_value: What this {symbol_type or 'symbol'} returns (if applicable)
            4. dependencies: Other functions/classes/modules it depends on
            5. usage_pattern: How this {symbol_type or 'symbol'} is typically used
            6. edge_cases: Potential edge cases or error handling
            7. complexity: Analysis of time/space complexity (if applicable)
            8. suggestions: Any improvements or best practices that could be applied
            
            Format your response as a valid JSON object without any extra text or markdown.
            """
            
            # Create message for the LLM
            messages = [
                ChatMessage(role="user", content=prompt)
            ]
            
            # Get completion from Mistral
            chat_response = self.mistral_client.chat(
                model=self.model,
                messages=messages
            )
            
            # Extract the content from the response
            content = chat_response.choices[0].message.content
            
            # Try to parse the response as JSON
            try:
                analysis = json.loads(content)
                return analysis
            except json.JSONDecodeError:
                # If JSON parsing fails, return the raw text
                return {"raw_analysis": content}
            
        except Exception as e:
            print(f"Error analyzing with LLM: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}
    
    def analyze_error(self, error_message: str) -> Dict:
        """
        Analyze a specific error message in the codebase and suggest solutions
        
        Args:
            error_message: The error message to analyze
            
        Returns:
            Dictionary containing error analysis and potential solutions
        """
        try:
            # First, search for similar error patterns in the code
            # Split error message into keywords
            keywords = error_message.lower().split()
            keywords = [kw for kw in keywords if len(kw) > 3]  # Filter out short words
            
            # Create LIKE conditions for each keyword
            code_field = 'code_snippet'
            snippet_sample = self.node_types.get('snippet', {}).get('sample', {})
            
            if 'code_snippet' in snippet_sample:
                code_field = 'code_snippet'
            elif 'code' in snippet_sample:
                code_field = 'code'
            elif 'snippet' in snippet_sample:
                code_field = 'snippet'
                
            # Find code snippets that might contain error handling for similar errors
            related_snippets = []
            
            for keyword in keywords:
                aql = f"""
                FOR snippet IN {self.node_collection}
                    FILTER snippet.type == 'snippet' 
                    AND (
                        snippet.{code_field} LIKE '%error%' 
                        AND snippet.{code_field} LIKE '%{keyword}%'
                    )
                    LET file = (
                        FOR edge IN {self.edge_collection}
                            FILTER edge._to == snippet._id
                            FOR file IN {self.node_collection}
                                FILTER file._id == edge._from AND file.type == 'file'
                                RETURN {{
                                    "key": file._key,
                                    "file_path": file.path || (file.directory + '/' + file.file_name)
                                }}
                    )
                    RETURN {{
                        "code": snippet.{code_field},
                        "start_line": snippet.start_line,
                        "end_line": snippet.end_line,
                        "file": LENGTH(file) > 0 ? file[0] : null
                    }}
                """
                cursor = self.db.aql.execute(aql)
                for doc in cursor:
                    if doc not in related_snippets:
                        related_snippets.append(doc)
            
            # Format snippets for LLM
            snippets_text = ""
            for i, snippet in enumerate(related_snippets):
                file_info = snippet.get("file", {})
                file_path = file_info.get("file_path", "unknown")
                code = snippet.get("code", "")
                
                snippets_text += f"\nSnippet {i+1} from {file_path}:\n{code}\n"
            
            # Create a prompt for the LLM
            prompt = f"""
            Please analyze this error message from a codebase:
            
            ```
            {error_message}
            ```
            
            I found these potentially related code snippets from the codebase:
            {snippets_text if snippets_text else "No directly related snippets found."}
            
            Provide a JSON response with the following fields:
            1. error_type: Classification of this error
            2. likely_causes: List of potential causes for this error
            3. affected_components: Which parts of the code might be affected
            4. solution_suggestions: Specific recommendations to fix this error
            5. preventive_measures: How to prevent this type of error in the future
            
            Format your response as a valid JSON object without any extra text or markdown.
            """
            
            # Create message for the LLM
            messages = [
                ChatMessage(role="user", content=prompt)
            ]
            
            # Get completion from Mistral
            chat_response = self.mistral_client.chat(
                model=self.model,
                messages=messages
            )
            
            # Extract the content from the response
            content = chat_response.choices[0].message.content
            
            # Try to parse the response as JSON
            try:
                analysis = json.loads(content)
                return {
                    "error_message": error_message,
                    "related_snippets_count": len(related_snippets),
                    "analysis": analysis
                }
            except json.JSONDecodeError:
                # If JSON parsing fails, return the raw text
                return {
                    "error_message": error_message,
                    "related_snippets_count": len(related_snippets),
                    "raw_analysis": content
                }
            
        except Exception as e:
            print(f"Error analyzing error: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    def get_database_structure(self) -> Dict:
        """
        Answer questions about the database structure
        Returns:
            Dictionary containing information about the database structure
        """
        try:
            # Most of this information was already gathered during initialization
            # Just format it in a more user-friendly way
            # Extract node types with counts
            node_types_info = {}
            for node_type, info in self.node_types.items():
                node_types_info[node_type] = {
                    "count": info.get("count", 0),
                    "properties": info.get("sample_structure", [])
                }
                
            # Extract relationship types
            relationship_types = {}
            for rel in self.db_schema.get("Type Relationships", []):
                from_type = rel.get("from_type", "")
                to_type = rel.get("to_type", "")
                edge_type = rel.get("edge_type", "")
                key = f"{from_type}_to_{to_type}"
                if key not in relationship_types:
                    relationship_types[key] = {
                        "from_type": from_type,
                        "to_type": to_type,
                        "edge_types": []
                    }
                if edge_type and edge_type not in relationship_types[key]["edge_types"]:
                    relationship_types[key]["edge_types"].append(edge_type)
                    
            # Count files by language
            languages = {}
            for file_info in self.files.values():
                language = file_info.get("language", "unknown")
                if language not in languages:
                    languages[language] = 0
                languages[language] += 1
                
            # Build directory structure map for improved path navigation
            directory_structure = self._build_directory_structure()
                
            return {
                "graph_name": self.graph_name,
                "node_collection": self.node_collection,
                "edge_collection": self.edge_collection,
                "node_types": node_types_info,
                "relationship_types": list(relationship_types.values()),
                "file_count": len(self.files),
                "snippet_count": len(self.snippets),
                "symbol_count": len(self.symbols),
                "languages": languages,
                "directory_structure": directory_structure
            }
        except Exception as e:
            print(f"Error getting database structure: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}
        
    def analyze_directory(self, path: str) -> Dict:
        """
        Analyze a specific directory in the codebase
        
        Args:
            path: Path to directory to analyze
        
        Returns:
            Dictionary with directory analysis results
        """
        try:
            print(f"Analyzing code structure at path: {path}")
            
            # Normalize path for consistent matching
            normalized_path = path.rstrip('/')
            
            # First try direct path matching for directory nodes
            print(f"Looking for files with path pattern: {normalized_path}")
            
            # Query files with matching path prefix
            matching_files = []
            for file_key, file_info in self.files.items():
                file_path = file_info.get("file_path", "")
                if file_path and (file_path.startswith(f"{normalized_path}/") or file_path == normalized_path):
                    matching_files.append(file_info)
            
            # Sort files for consistent output
            matching_files.sort(key=lambda x: x.get("file_path", ""))
            
            # Print sample paths for debugging
            print("Sample file paths in database:")
            for i, file_info in enumerate(list(self.files.values())[:6]):
                print(f"File {i+1}: {file_info.get('file_path', '')}")
            
            # If no files found with direct path matching, try more flexible matching
            if not matching_files:
                # Try to find files that might contain the path (handle relative paths)
                for file_key, file_info in self.files.items():
                    file_path = file_info.get("file_path", "")
                    path_parts = normalized_path.split('/')
                    
                    # Check if all path parts appear in order in the file path
                    if file_path:
                        file_parts = file_path.split('/')
                        for i in range(len(file_parts) - len(path_parts) + 1):
                            if file_parts[i:i+len(path_parts)] == path_parts:
                                matching_files.append(file_info)
                                break
                
                # Sort again after flexible matching
                matching_files.sort(key=lambda x: x.get("file_path", ""))
            
            # Get directory structure
            directory_structure = self._get_directory_contents(normalized_path)
            
            # Get snippets for matching files
            file_keys = [file_info.get("key") for file_info in matching_files]
            matching_snippets = []
            for snippet_key, snippet_info in self.snippets.items():
                if snippet_info.get("file_key") in file_keys:
                    matching_snippets.append(snippet_info)
            
            # Get symbols for matching files
            matching_symbols = []
            for symbol_key, symbol_info in self.symbols.items():
                if symbol_info.get("file_key") in file_keys:
                    matching_symbols.append(symbol_info)
            
            return {
                "path": normalized_path,
                "files": matching_files,
                "file_count": len(matching_files),
                "directory_structure": directory_structure,
                "snippets_count": len(matching_snippets),
                "symbols_count": len(matching_symbols)
            }
            
        except Exception as e:
            print(f"Error analyzing directory: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    def _get_directory_contents(self, path: str) -> Dict:
        """
        Get contents of a specific directory
        
        Args:
            path: Path to directory
        
        Returns:
            Dictionary with directory contents
        """
        contents = {"files": [], "subdirectories": []}
        
        # Normalize path
        normalized_path = path.rstrip('/')
        
        # Get files directly in this directory
        for file_key, file_info in self.files.items():
            file_path = file_info.get("file_path", "")
            if not file_path:
                continue
                
            file_dir = '/'.join(file_path.split('/')[:-1])
            
            if file_dir == normalized_path:
                contents["files"].append({
                    "key": file_key,
                    "name": file_info.get("file_name", ""),
                    "path": file_path,
                    "language": file_info.get("language", "")
                })
        
        # Get subdirectories
        seen_subdirs = set()
        for file_key, file_info in self.files.items():
            file_path = file_info.get("file_path", "")
            if not file_path or not file_path.startswith(f"{normalized_path}/"):
                continue
                
            # Get next directory level
            remaining_path = file_path[len(normalized_path)+1:]
            if '/' in remaining_path:
                subdir = remaining_path.split('/')[0]
                subdir_path = f"{normalized_path}/{subdir}"
                
                if subdir_path not in seen_subdirs:
                    seen_subdirs.add(subdir_path)
                    contents["subdirectories"].append({
                        "name": subdir,
                        "path": subdir_path
                    })
        
        return contents

    def search_code(self, term: str) -> List[Dict]:
        """
        Search for code containing a specific term
        
        Args:
            term: The term to search for
            
        Returns:
            List of dictionaries containing matching code snippets
        """
        results = []

        
        
        try:
            # Determine the best attribute for code based on the sample
            code_field = 'code_snippet'
            snippet_sample = self.node_types.get('snippet', {}).get('sample', {})
            
            if 'code_snippet' in snippet_sample:
                code_field = 'code_snippet'
            elif 'code' in snippet_sample:
                code_field = 'code'
            elif 'snippet' in snippet_sample:
                code_field = 'snippet'
            
            aql = f"""
            FOR snippet IN {self.node_collection}
                FILTER snippet.type == 'snippet' AND snippet.{code_field} LIKE '%{term}%'
                LET file = (
                    FOR edge IN {self.edge_collection}
                        FILTER edge._to == snippet._id
                        FOR file IN {self.node_collection}
                            FILTER file._id == edge._from AND file.type == 'file'
                            RETURN {{
                                "key": file._key,
                                "directory": file.directory,
                                "file_name": file.file_name,
                                "file_path": file.path || (file.directory + '/' + file.file_name),
                                "language": file.language
                            }}
                )
                RETURN {{
                    "key": snippet._key,
                    "code": snippet.{code_field},
                    "start_line": snippet.start_line,
                    "end_line": snippet.end_line,
                    "file": LENGTH(file) > 0 ? file[0] : null
                }}
            """
            cursor = self.db.aql.execute(aql)
            for doc in cursor:
                results.append(doc)
                
        except Exception as e:
            print(f"Error searching code: {str(e)}")
            traceback.print_exc()
        
        return results

    def analyze_code_structure(self, path: Optional[str] = None) -> Dict:
        """
        Analyze and visualize the structure of the code, either for a specific file or directory
        
        Args:
            path: Optional path to focus the analysis on
            
        Returns:
            Dictionary containing code structure analysis
        """

        print(f"Analyzing code structure at path: {path}")
        # Print the query you're using to find files
        print(f"Looking for files with path pattern: {path}")
        # Print a few sample files from your cache for comparison
        print("Sample file paths in database:")
        for i, (key, file_info) in enumerate(self.files.items()):
            print(f"File {i+1}: {file_info.get('file_path', 'unknown')}")
            if i >= 5:
                break
        # Rest of your function...
        try:
            # If path is provided, filter by that path
            path_filter = ""
            if path:
                path_filter = f" AND (file.path LIKE '{path}/%' OR file.path == '{path}')"
            
            # First, gather file structure
            aql = f"""
            FOR file IN {self.node_collection}
                FILTER file.type == 'file'{path_filter}
                RETURN {{
                    "key": file._key,
                    "file_path": file.path || (file.directory + '/' + file.file_name),
                    "language": file.language
                }}
            """
            cursor = self.db.aql.execute(aql)
            files = [doc for doc in cursor]
            
            # Group files by directory
            directory_structure = {}
            for file in files:
                file_path = file.get("file_path", "")
                if not file_path:
                    continue
                
                # Split path and use all but the last part as directory
                path_parts = file_path.split('/')
                if len(path_parts) > 1:
                    directory = '/'.join(path_parts[:-1])
                    filename = path_parts[-1]
                else:
                    directory = "."
                    filename = file_path
                
                if directory not in directory_structure:
                    directory_structure[directory] = []
                
                directory_structure[directory].append({
                    "file_name": filename,
                    "file_path": file_path,
                    "key": file.get("key"),
                    "language": file.get("language", "unknown")
                })
            
            # Count symbols by type and file
            symbol_counts = {}
            if 'symbol' in self.node_types:
                path_join = ""
                if path:
                    path_join = f" AND (file.path LIKE '{path}/%' OR file.path == '{path}')"
                
                aql = f"""
                FOR symbol IN {self.node_collection}
                    FILTER symbol.type == 'symbol'
                    LET file = (
                        FOR edge IN {self.edge_collection}
                            FILTER edge._to == symbol._id
                            FOR file IN {self.node_collection}
                                FILTER file._id == edge._from AND file.type == 'file'{path_join}
                                RETURN file
                    )
                    FILTER LENGTH(file) > 0
                    COLLECT file_path = file[0].path || (file[0].directory + '/' + file[0].file_name),
                            symbol_type = symbol.symbol_type WITH COUNT INTO count
                    RETURN {{
                        "file_path": file_path,
                        "symbol_type": symbol_type,
                        "count": count
                    }}
                """
                cursor = self.db.aql.execute(aql)
                for doc in cursor:
                    file_path = doc.get("file_path", "")
                    symbol_type = doc.get("symbol_type", "unknown")
                    count = doc.get("count", 0)
                    
                    if file_path not in symbol_counts:
                        symbol_counts[file_path] = {}
                    
                    symbol_counts[file_path][symbol_type] = count
            
            # Prepare analysis data for LLM
            file_count = len(files)
            directory_count = len(directory_structure)
            
            # Prepare information for visualization
            directory_tree = []
            for directory, file_list in directory_structure.items():
                directory_tree.append({
                    "directory": directory,
                    "files": file_list,
                    "file_count": len(file_list)
                })
            
            # Sort directories by file count (descending)
            directory_tree.sort(key=lambda x: x["file_count"], reverse=True)
            
            # Analyze distribution of languages
            language_counts = {}
            for file in files:
                language = file.get("language", "unknown")
                if language not in language_counts:
                    language_counts[language] = 0
                language_counts[language] += 1
            
            # Create an analysis with Mistral
            if files:
                structure_info = {
                    "file_count": file_count,
                    "directory_count": directory_count,
                    "top_directories": [d["directory"] for d in directory_tree[:5]],
                    "language_distribution": language_counts,
                    "symbol_type_distribution": symbol_counts
                }
                
                # Create a prompt for the LLM to analyze the structure
                prompt = f"""
                Please analyze this codebase structure:
                
                {json.dumps(structure_info, indent=2)}
                
                Provide a JSON response with the following fields:
                1. overview: High-level description of the codebase structure
                2. architecture_patterns: Any architectural patterns you can identify
                3. key_components: The most important directories/modules
                4. language_insights: Analysis of the programming language usage
                5. recommendations: Suggestions for organization or structure improvements
                
                Format your response as a valid JSON object without any extra text or markdown.
                """
                
                # Create message for the LLM
                messages = [
                    ChatMessage(role="user", content=prompt)
                ]
                
                # Get completion from Mistral
                chat_response = self.mistral_client.chat(
                    model=self.model,
                    messages=messages
                )
                
                # Extract the content from the response
                content = chat_response.choices[0].message.content
                
                # Try to parse the response as JSON
                try:
                    analysis = json.loads(content)
                except json.JSONDecodeError:
                    # If JSON parsing fails, return the raw text
                    analysis = {"raw_analysis": content}
            else:
                analysis = {"message": "No files found matching the specified path"}
            
            return {
                "path": path or "entire codebase",
                "file_count": file_count,
                "directory_count": directory_count,
                "directory_structure": directory_tree,
                "language_distribution": language_counts,
                "symbol_distribution": symbol_counts,
                "analysis": analysis
            }
            
        except Exception as e:
            print(f"Error analyzing code structure: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}
        
        # Add this debugging code to your query function
    def debug_query_execution(self, path):
        """Debug what's happening when trying to find files at a path."""
        print(f"Debugging query for path: {path}")
        
        # Check if the path exists in the database at all
        aql = f"""
        FOR v IN {self.node_collection}
            FILTER CONTAINS(v.path, '{path}') OR CONTAINS(v.directory, '{path}')
            RETURN {{path: v.path, directory: v.directory, type: v.type}}
        """
        cursor = self.db.aql.execute(aql)
        results = [doc for doc in cursor]
        print(f"Found {len(results)} items containing the path:")
        for item in results[:10]:  # Print first 10 for debugging
            print(f"  - {item}")
        
        # Check node types in the database
        aql = f"""
        FOR v IN {self.node_collection}
            COLLECT type = v.type WITH COUNT INTO count
            RETURN {{type, count}}
        """
        cursor = self.db.aql.execute(aql)
        type_counts = [doc for doc in cursor]
        print("Node types in database:")
        for type_info in type_counts:
            print(f"  - {type_info['type']}: {type_info['count']}")

    def process_query(self, query: str) -> Dict:
        """
        Process natural language queries about the codebase
        
        Args:
            query: Natural language query about the codebase
            
        Returns:
            Dictionary containing the response to the query
        """
        try:
            # Save the query to conversation history
            self.conversation_history.append({"role": "user", "content": query})
            
            # Get database structure for context
            db_structure = self.get_database_structure()
            
            # Create context for the LLM
            context = {
                "db_structure": db_structure,
                "conversation_history": self.conversation_history[-5:] if len(self.conversation_history) > 1 else []
            }
            
            # Create a prompt for the LLM to analyze the query and decide what action to take
            prompt = f"""
            You are a codebase assistant that helps users find information in their codebase.
            
            Database Structure:
            {json.dumps(db_structure, indent=2)}
            
            Available functions:
            1. find_symbol_occurrences(symbol_name): Find all occurrences of a symbol
            2. find_by_name(name, symbol_type): Find function/class snippets by name
            3. analyze_symbol(name, symbol_type): Get detailed analysis of a function/class
            4. analyze_error(error_message): Analyze an error message and suggest solutions
            5. search_code(term): Search for code containing specific terms
            6. analyze_code_structure(path): Analyze the structure of the code
            7. analyze_directory(path): Analyze a specific directory in the codebase
            
            Conversation History:
            {json.dumps(context["conversation_history"], indent=2)}
            
            User Query: {query}
            
            First, determine what the user is asking and which function would be most appropriate to answer their query.
            
            Return a JSON response with:
            1. understanding: Brief explanation of what you think the user is asking
            2. function_to_call: The most appropriate function to call based on the query
            3. parameters: Parameters to pass to the function
            
            Format your response as a valid JSON object without any extra text or markdown.
            """
            
            # Create message for the LLM
            messages = [
                ChatMessage(role="user", content=prompt)
            ]
            
            # Get completion from Mistral
            chat_response = self.mistral_client.chat(
                model=self.model,
                messages=messages
            )
            
            # Extract the content from the response
            content = chat_response.choices[0].message.content
            
            # Try to parse the response as JSON
            try:
                # Clean up the content to remove markdown code blocks if present
                cleaned_content = content
                if content.strip().startswith("```") and content.strip().endswith("```"):
                    # Extract the content between the backticks
                    cleaned_content = "\n".join(content.strip().split("\n")[1:-1])
                query_analysis = json.loads(cleaned_content)
            except json.JSONDecodeError:
                return {"error": "Failed to parse LLM response as JSON", "raw_response": content}
            
            # Get the function to call and parameters
            function_name = query_analysis.get("function_to_call", "")
            parameters = query_analysis.get("parameters", {})
            
            # Call the appropriate function based on the analysis
            result = None
            if function_name == "find_symbol_occurrences":
                symbol_name = parameters.get("symbol_name", "")
                if symbol_name:
                    result = self.find_symbol_occurrences(symbol_name)
            elif function_name == "find_by_name":
                name = parameters.get("name", "")
                symbol_type = parameters.get("symbol_type")
                if name:
                    result = self.find_by_name(name, symbol_type)
            elif function_name == "analyze_symbol":
                name = parameters.get("name", "")
                symbol_type = parameters.get("symbol_type")
                if name:
                    result = self.analyze_symbol(name, symbol_type)
            elif function_name == "analyze_error":
                error_message = parameters.get("error_message", "")
                if error_message:
                    result = self.analyze_error(error_message)
            elif function_name == "search_code":
                term = parameters.get("term", "")
                if term:
                    result = self.search_code(term)
            elif function_name == "analyze_code_structure":
                path = parameters.get("path")
                result = self.analyze_code_structure(path)
            elif function_name == "analyze_directory":
                path = parameters.get("path", "")
                if path:
                    result = self.analyze_directory(path)
            else:
                result = {"error": f"Unknown function: {function_name}"}
            
            # If result is None or empty, try to handle the query directly
            if result is None or (isinstance(result, list) and len(result) == 0):
                # Create a fallback prompt for the LLM
                fallback_prompt = f"""
                You are a codebase assistant that helps users find information in their codebase.
                
                Database Structure:
                {json.dumps(db_structure, indent=2)}
                
                Unfortunately, I couldn't find specific information to answer the user's query:
                
                User Query: {query}
                
                Please provide a helpful response based on the general codebase structure.
                Your response should:
                1. Acknowledge what information is missing
                2. Suggest alternative approaches based on the available database structure
                3. Ask for any clarification if needed
                
                Format your response as a conversation, not as JSON.
                """
                
                # Create message for the LLM
                fallback_messages = [
                    ChatMessage(role="user", content=fallback_prompt)
                ]
                
                # Get completion from Mistral
                fallback_response = self.mistral_client.chat(
                    model=self.model,
                    messages=fallback_messages
                )
                
                # Extract the content from the response
                fallback_content = fallback_response.choices[0].message.content
                
                # Add the fallback response to conversation history
                self.conversation_history.append({"role": "assistant", "content": fallback_content})
                
                return {
                    "query": query,
                    "understanding": query_analysis.get("understanding", ""),
                    "response_type": "fallback",
                    "response": fallback_content
                }
            
            # Generate a user-friendly explanation of the result
            explanation_prompt = f"""
            You are a codebase assistant that helps users find information in their codebase.
            
            User Query: {query}
            
            Understanding: {query_analysis.get("understanding", "")}
            
            Result: {json.dumps(result, indent=2)}
            
            Please explain these results to the user in a clear, conversational way.
            If results include code snippets, explain what the code does.
            If there are multiple results, summarize the key findings.
            Include specific details from the results to make your explanation concrete.
            
            Format your response as a conversation, not as JSON.
            """
            
            # Create message for the LLM
            explanation_messages = [
                ChatMessage(role="user", content=explanation_prompt)
            ]
            
            # Get completion from Mistral
            explanation_response = self.mistral_client.chat(
                model=self.model,
                messages=explanation_messages
            )
            
            # Extract the content from the response
            explanation = explanation_response.choices[0].message.content
            
            # Add the explanation to conversation history
            self.conversation_history.append({"role": "assistant", "content": explanation})
            
            return {
                "query": query,
                "understanding": query_analysis.get("understanding", ""),
                "function_called": function_name,
                "parameters": parameters,
                "raw_result": result,
                "explanation": explanation
            }
            
        except Exception as e:
            print(f"Error processing query: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    def chat_with_codebase(self, query: str) -> str:
        """
        Main conversational function that processes user queries about the codebase
        
        Args:
            query: User's natural language query
            
        Returns:
            String containing the response to the user
        """
        try:
            # Process the query
            result = self.process_query(query)
            
            # If an error occurred, return an error message
            if "error" in result:
                error_message = result.get("error", "An unknown error occurred")
                if "raw_response" in result:
                    return f"I encountered an error: {error_message}\n\nRaw response from LLM: {result['raw_response']}"
                return f"I encountered an error: {error_message}"
            
            # If the result contains an explanation, return it
            if "explanation" in result:
                return result["explanation"]
            
            # If the result contains a response, return it
            if "response" in result:
                return result["response"]
            
            # This is a fallback if neither explanation nor response are available
            return "I processed your query but couldn't generate a proper explanation. Please try rephrasing your question."
            
        except Exception as e:
            print(f"Error in chat_with_codebase: {str(e)}")
            traceback.print_exc()
            return f"I'm sorry, I encountered an error while processing your query: {str(e)}"

    def reset_conversation(self):
        """Reset the conversation history"""
        self.conversation_history = []

if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    
    # Get Mistral API key from environment
    mistral_api_key = os.environ.get("MISTRAL_API_KEY")
    
    # Initialize client
    query_system = EnhancedCodebaseQuery(
        db_name="_system",
        username="root",
        password="cUZ0YaNdcwfUTw6VjRny",
        host="https://d2eeb8083350.arangodb.cloud:8529",
        mistral_api_key=mistral_api_key,
        model="mistral-large-latest",
        graph="FlaskRepv1"
    )

    # Chat with your codebase
    response = query_system.chat_with_codebase("what does this test_templates_list function do in my codebase?")
    print(response)