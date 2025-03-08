import os
import json
import re
import traceback
from typing import Dict, List, Optional, Union
from arango import ArangoClient
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from dotenv import load_dotenv

class CustomCodebaseQuery:
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
        Initialize the CustomCodebaseQuery with database and Mistral API connections.
        
        Args:
            db_name: ArangoDB database name
            username: ArangoDB username
            password: ArangoDB password
            host: ArangoDB host URL
            mistral_api_key: Mistral API key (if None, will try to get from environment)
            model: Mistral model to use
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
        self.graph_name = graph
        self.node_collection = node
        self.edge_collection = edge
        
        # Initialize file and snippet cache
        self.files = {}
        self.snippets = {}
        self.initialize_cache()
    
    def initialize_cache(self):
        """Initialize cache of files and code snippets"""
        try:
            # Query all files
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER v.type == 'file'
                RETURN {{
                    "key": v._key,
                    "file_index": v.file_index,
                    "directory": v.directory
                }}
            """
            cursor = self.db.aql.execute(aql)
            for doc in cursor:
                self.files[doc.get("file_index")] = {
                    "key": doc.get("key"),
                    "directory": doc.get("directory")
                }
            
            # Query all code snippets
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER v.type == 'snippet'
                RETURN {{
                    "key": v._key,
                    "code": v.code_snippet,
                    "start_line": v.start_line,
                    "end_line": v.end_line
                }}
            """
            cursor = self.db.aql.execute(aql)
            for doc in cursor:
                self.snippets[doc.get("key")] = {
                    "code": doc.get("code_snippet"),
                    "start_line": doc.get("start_line"),
                    "end_line": doc.get("end_line")
                }
            
            print(f"Initialized cache with {len(self.files)} files and {len(self.snippets)} code snippets")
        except Exception as e:
            print(f"Error initializing cache: {str(e)}")
            traceback.print_exc()
    
    def find_function_by_name(self, function_name: str) -> List[Dict]:
        """Find function snippets by name with improved matching"""
        results = []
        
        try:
            # Use a more flexible pattern to catch different ways the function might be defined
            for key, snippet in self.snippets.items():
                code = snippet.get("code", "")
                if not code:
                    continue
                
                # Define regex pattern to match function definitions with various indentation styles
                # This will match patterns like:
                # - "def function_name("
                # - "def function_name ("
                # - "    def function_name("
                # - "@decorator\n    def function_name("
                pattern = re.compile(r'(?:^|\n)\s*(?:@\w+\s*(?:\(.*?\))?\s*\n\s*)*def\s+' + 
                                     re.escape(function_name) + r'\s*\(', 
                                     re.MULTILINE)
                
                if pattern.search(code):
                    # Extract the function context
                    lines = code.split("\n")
                    function_lines = []
                    in_function = False
                    indent_level = 0
                    
                    for i, line in enumerate(lines):
                        # Look for the function definition
                        if not in_function and re.search(r'^\s*def\s+' + re.escape(function_name) + r'\s*\(', line):
                            in_function = True
                            # Calculate indentation level
                            indent_level = len(line) - len(line.lstrip())
                            # Check previous lines for decorators
                            j = i - 1
                            while j >= 0 and (lines[j].strip().startswith('@') or not lines[j].strip()):
                                function_lines.insert(0, lines[j])
                                j -= 1
                            function_lines.append(line)
                        elif in_function:
                            # Check if we're still in the function based on indentation
                            if line.strip() and len(line) - len(line.lstrip()) <= indent_level and not (
                                line.strip().startswith('#') or not line.strip()
                            ):
                                in_function = False
                            else:
                                function_lines.append(line)
                    
                    function_code = "\n".join(function_lines)
                    
                    # Get docstring if available
                    docstring = ""
                    docstring_pattern = re.compile(r'"""(.*?)"""', re.DOTALL)
                    match = docstring_pattern.search(function_code)
                    if match:
                        docstring = match.group(1).strip()
                    
                    results.append({
                        "key": key,
                        "code": function_code,
                        "docstring": docstring,
                        "start_line": snippet.get("start_line"),
                        "end_line": snippet.get("end_line")
                    })
        except Exception as e:
            print(f"Error finding function by name: {str(e)}")
            traceback.print_exc()
        
        return results
    
    def find_function_in_db(self, function_name: str) -> List[Dict]:
        """Find function in the database using AQL with improved matching"""
        results = []
        
        try:
            # Use a more flexible AQL search pattern
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER v.type == 'snippet'
                LET code = v.code_snippet
                FILTER CONTAINS(code, "def {function_name}") OR 
                       CONTAINS(code, "def {function_name} ")
                RETURN {{
                    "key": v._key,
                    "code": code,
                    "start_line": v.start_line,
                    "end_line": v.end_line
                }}
            """
            cursor = self.db.aql.execute(aql)
            for doc in cursor:
                code = doc.get("code")
                
                # Check if it's a proper function definition and not just a string containing the text
                if re.search(r'(?:^|\n)\s*(?:@\w+\s*(?:\(.*?\))?\s*\n\s*)*def\s+' + 
                            re.escape(function_name) + r'\s*\(', code, re.MULTILINE):
                    
                    # Get docstring if available
                    docstring = ""
                    docstring_match = re.search(r'"""(.*?)"""', code, re.DOTALL)
                    if docstring_match:
                        docstring = docstring_match.group(1).strip()
                    
                    results.append({
                        "key": doc.get("key"),
                        "code": code,
                        "docstring": docstring,
                        "start_line": doc.get("start_line"),
                        "end_line": doc.get("end_line")
                    })
        except Exception as e:
            print(f"Error searching in database: {str(e)}")
            traceback.print_exc()
        
        return results
    
    def search_function_by_partial_name(self, partial_name: str) -> List[Dict]:
        """Search for functions with names containing the partial name"""
        results = []
        
        try:
            # Search for functions with partial name match
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER v.type == 'snippet'
                LET code = v.code_snippet
                FILTER CONTAINS(LOWER(code), LOWER("def {partial_name}"))
                RETURN {{
                    "key": v._key,
                    "code": code,
                    "start_line": v.start_line,
                    "end_line": v.end_line
                }}
            """
            cursor = self.db.aql.execute(aql)
            for doc in cursor:
                # Extract function name from code
                code = doc.get("code")
                function_names = re.findall(r'def\s+(\w+)', code)
                
                # Check if any of the found function names contain the partial name
                matching_functions = [name for name in function_names if partial_name.lower() in name.lower()]
                
                if matching_functions:
                    docstring = ""
                    docstring_match = re.search(r'"""(.*?)"""', code, re.DOTALL)
                    if docstring_match:
                        docstring = docstring_match.group(1).strip()
                    
                    results.append({
                        "key": doc.get("key"),
                        "code": code,
                        "function_names": matching_functions,
                        "docstring": docstring,
                        "start_line": doc.get("start_line"),
                        "end_line": doc.get("end_line")
                    })
        except Exception as e:
            print(f"Error searching with partial name: {str(e)}")
            traceback.print_exc()
        
        return results
    
    def debug_search(self, term: str):
        """Print snippets containing a term for debugging"""
        found = 0
        for key, snippet in self.snippets.items():
            code = snippet.get("code", "")
            if code and term.lower() in code.lower():
                found += 1
                print(f"Found '{term}' in snippet {key}:")
                print(code[:200] + "..." if len(code) > 200 else code)
                print("-" * 50)
        
        print(f"Found {found} snippets containing '{term}'")
        
        # Also try a direct database search
        try:
            aql = f"""
            FOR v IN {self.node_collection}
                FILTER v.type == 'snippet'
                LET code = v.code_snippet
                FILTER CONTAINS(LOWER(code), LOWER("{term}"))
                RETURN {{
                    "key": v._key,
                    "preview": SUBSTRING(code, 0, 200)
                }}
            """
            cursor = self.db.aql.execute(aql)
            db_found = 0
            for doc in cursor:
                db_found += 1
                print(f"Found '{term}' in database snippet {doc.get('key')}:")
                print(doc.get('preview') + "..." if len(doc.get('preview')) >= 200 else doc.get('preview'))
                print("-" * 50)
            
            print(f"Found {db_found} snippets containing '{term}' in database")
        except Exception as e:
            print(f"Error in database debug search: {str(e)}")
    
    def query_function(self, function_name: str) -> str:
        """
        Query about a specific function and get an analysis in JSON format.
        
        Args:
            function_name: Name of the function to analyze
            
        Returns:
            JSON-formatted analysis of the function
        """
        # First try the improved in-memory search
        function_snippets = self.find_function_by_name(function_name)
        
        # If not found, try direct database search
        if not function_snippets:
            function_snippets = self.find_function_in_db(function_name)
        
        # If still not found, try partial name search
        if not function_snippets:
            partial_matches = self.search_function_by_partial_name(function_name)
            if partial_matches:
                # Format information about partial matches
                partial_info = []
                for match in partial_matches:
                    function_names = match.get("function_names", [])
                    for name in function_names:
                        partial_info.append(f"- {name}")
                
                return json.dumps({
                    "status": "partial_match",
                    "message": f"Function '{function_name}' not found exactly, but found similar functions",
                    "similar_functions": [name for match in partial_matches for name in match.get("function_names", [])]
                }, indent=2)
        
        if not function_snippets:
            # Last resort: debug search to look for any mentions
            print(f"Debug search for '{function_name}':")
            self.debug_search(function_name)
            return json.dumps({
                "status": "not_found",
                "message": f"Function '{function_name}' not found in the codebase."
            }, indent=2)
        
        # Prepare context for the LLM
        snippets_info = []
        for snippet in function_snippets:
            snippets_info.append({
                "code": snippet.get("code"),
                "docstring": snippet.get("docstring"),
                "start_line": snippet.get("start_line"),
                "end_line": snippet.get("end_line")
            })
        
        # Format the context
        context = json.dumps(snippets_info, indent=2)
        
        # Prepare system prompt
        system_prompt = """You are an expert code analyzer assisting with a Python codebase.
    You have access to information about functions, including their code and docstrings.
    Analyze the provided function(s) and explain:
    1. The purpose and functionality of ALL entities that match the query name
    2. Any patterns or similarities you observe across the functions
    3. Key parameters and return values
    4. How it might be used in the codebase
    
    Format your response as a JSON object with the following structure:
    {
    "status": "success",
    "function_name": "(function name)",
    "analysis": {
        "purpose": "(description of purpose)",
        "parameters": [{"name": "param1", "description": "description", "type": "type if known"}],
        "return_value": {"description": "description", "type": "type if known"},
        "usage_examples": ["example 1", "example 2"]
    }
    }

    Focus on technical accuracy in your JSON response.
    Do not hallucinate or provide false information. If you are unsure, indicate that in your response.
    """

        # Query the LLM
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=f"""
    Here is information about the function '{function_name}':
    {context}

    Please analyze this function and provide the analysis in the requested JSON format.
    """)
        ]
        
        response = self.mistral_client.chat(
            model=self.model,
            messages=messages
        )
        
        return response.choices[0].message.content
    
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
                FOR v IN {self.node_collection}
                    FILTER v.type == 'snippet'
                    LET code = v.code_snippet
                    FILTER CONTAINS(LOWER(code), LOWER("{search_term}"))
                    RETURN {{
                        "key": v._key,
                        "code": code,
                        "start_line": v.start_line,
                        "end_line": v.end_line
                    }}
                """
                cursor = self.db.aql.execute(aql)
                for doc in cursor:
                    matching_snippets.append({
                        "key": doc.get("key"),
                        "code": doc.get("code"),
                        "start_line": doc.get("start_line"),
                        "end_line": doc.get("end_line")
                    })
            
            if not matching_snippets:
                # Last resort: debug search to look for any mentions
                print(f"Debug search for '{search_term}':")
                self.debug_search(search_term)
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
    
    def analyze_codebase(self) -> str:
        """
        Generate an overview of the codebase structure.
        
        Returns:
            Analysis of the codebase structure
        """
        try:
            # Get summary of files and directories
            directories = {}
            for file_idx, file_info in self.files.items():
                directory = file_info.get("directory", "")
                if directory:
                    if directory not in directories:
                        directories[directory] = 0
                    directories[directory] += 1
            
            # Format the context
            context = {
                "total_files": len(self.files),
                "total_code_snippets": len(self.snippets),
                "directories": directories
            }
            
            # Prepare system prompt
            system_prompt = """You are an expert code analyzer assisting with a Python codebase.
You have access to high-level information about the codebase structure.
Provide an overview of the codebase based on the provided information, including:
1. The overall organization and structure
2. Potential architecture patterns based on directory organization
3. Any insights you can provide about the purpose and scope of the codebase

Focus on clarity and technical accuracy in your explanation.
"""

            # Query the LLM
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=f"""
Here is information about the codebase structure:
{json.dumps(context, indent=2)}

Please provide an overview of this codebase based on the available information.
""")
            ]
            
            response = self.mistral_client.chat(
                model=self.model,
                messages=messages
            )
            
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error analyzing codebase: {str(e)}")
            traceback.print_exc()
            return f"An error occurred while analyzing the codebase: {str(e)}"


# Example usage
if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    
    # Get Mistral API key from environment
    mistral_api_key = os.environ.get("MISTRAL_API_KEY")
    
    # Initialize client
    client = CustomCodebaseQuery(
        db_name="_system",
        username="root", 
        password="cUZ0YaNdcwfUTw6VjRny",
        host="https://d2eeb8083350.arangodb.cloud:8529",
        mistral_api_key=mistral_api_key,
        node="FlaskRepv1_node",
        edge="FlaskRepv1_node_to_FlaskRepv1_node",
        graph="FlaskRepv1"
    )
    
    # Example: Query about a specific function
    function_name = "block"  # Replace with a function name in your codebase
    print(f"Searching for function '{function_name}'...")
    response = client.query_function(function_name)
    print(f"Analysis of function '{function_name}':")
    print(response)
    print("\n" + "-"*50 + "\n")
    
    # # Example: Search for code containing a term
    # search_term = "level"  # Replace with a relevant term
    # print(f"Searching for term '{search_term}'...")
    # response = client.search_code(search_term)
    # print(f"Search results for '{search_term}':")
    # print(response)
    # print("\n" + "-"*50 + "\n")