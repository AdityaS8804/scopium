import os
import ast
import networkx as nx
from typing import Dict, Set, List, Tuple, Optional, Union
import json
from arango import ArangoClient
import re
import glob


class CodebaseVisualizer:
    def __init__(self, root_dir: str, supported_languages=None):
        self.root_dir = root_dir
        self.graph = nx.DiGraph()
        self.file_contents: Dict[str, str] = {}
        # file -> [(module, line_no)]
        self.import_relations: Dict[str, List[Tuple[str, int]]] = {}
        # file -> {symbol -> {type, line_no, context}}
        self.module_symbols: Dict[str, Dict[str, Dict[str, any]]] = {}
        # symbol -> [(file, line_no, context)]
        self.symbol_references: Dict[str, List[Tuple[str, int, str]]] = {}
        self.file_index: Dict[str, int] = {}  # Maps files to indices
        self.current_index = 0
        self.directories: Set[str] = set()
        # Add a new index for all symbols to quickly locate them
        # symbol -> [{file, type, line_no, context}]
        self.symbol_index: Dict[str, List[Dict]] = {}

        # Define supported languages
        self.supported_languages = supported_languages or [
            "python", "cpp", "java", "go"]

        # Language file extensions mapping
        self.language_extensions = {
            "python": [".py"],
            "cpp": [".c", ".cpp", ".h", ".hpp", ".cc", ".cxx", ".hxx"],
            "java": [".java"],
            "go": [".go"]
        }

    def _get_next_index(self) -> int:
        """Get next available index for file indexing."""
        self.current_index += 1
        return self.current_index

    def _chunk_code(self, code: str, lines_per_chunk: int = 20) -> List[Dict]:
        """
        Chunk the given code into snippets.
        Returns a list of dictionaries with 'code_snippet', 'start_line', and 'end_line'.
        """
        lines = code.splitlines()
        chunks = []
        for i in range(0, len(lines), lines_per_chunk):
            chunk_lines = lines[i:i + lines_per_chunk]
            chunk = {
                'code_snippet': '\n'.join(chunk_lines),
                'start_line': i + 1,
                'end_line': i + len(chunk_lines)
            }
            chunks.append(chunk)
        return chunks

    def _get_context_around_line(self, file_path: str, line_no: int, context_lines: int = 3) -> str:
        """Extract context around a specific line in a file."""
        if file_path not in self.file_contents:
            return ""

        lines = self.file_contents[file_path].splitlines()
        start = max(0, line_no - context_lines - 1)
        end = min(len(lines), line_no + context_lines)

        context = "\n".join(lines[start:end])
        return context

    def _detect_language(self, file_path: str) -> str:
        """Detect the programming language of a file based on its extension."""
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        for language, extensions in self.language_extensions.items():
            if ext in extensions:
                return language

        return "unknown"

    def parse_files(self) -> None:
        """Parse all files in the directory and build relationships."""
        # First pass: Index all files and create directory nodes
        for root, dirs, files in os.walk(self.root_dir):
            # Add directory node
            rel_dir = os.path.relpath(root, self.root_dir)
            if rel_dir != '.':
                self.directories.add(rel_dir)
                self.graph.add_node(rel_dir, type='directory')

                # Add edge from parent directory to this directory (if not root)
                parent_dir = os.path.dirname(rel_dir)
                if parent_dir and parent_dir != '.':
                    self.graph.add_edge(parent_dir, rel_dir,
                                        edge_type='contains_directory')

            # Index files of supported languages
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.root_dir)
                file_language = self._detect_language(file_path)

                if file_language in self.supported_languages:
                    self.file_index[rel_path] = self._get_next_index()

                    # Add node for this file
                    self.graph.add_node(
                        rel_path, type='file', file_index=self.file_index[rel_path], language=file_language)

                    # Connect file to its directory
                    if rel_dir != '.':
                        self.graph.add_edge(
                            rel_dir, rel_path, edge_type='contains_file')

                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            self.file_contents[rel_path] = content
                            self._analyze_file(
                                rel_path, content, file_language)
                    except Exception as e:
                        print(f"Error parsing {file_path}: {e}")

        # Second pass: Find symbol references across files
        for file_path, content in self.file_contents.items():
            file_language = self._detect_language(file_path)
            self._find_references_in_file(file_path, content, file_language)

        # Build the symbol index after all analyses
        self._build_symbol_index()

    def _analyze_file(self, file_path: str, content: str, language: str) -> None:
        """Analyze a file for imports and symbols with line numbers and context."""
        if language == "python":
            self._analyze_python_file(file_path, content)
        elif language == "cpp":
            self._analyze_cpp_file(file_path, content)
        elif language == "java":
            self._analyze_java_file(file_path, content)
        elif language == "go":
            self._analyze_go_file(file_path, content)

    def _analyze_python_file(self, file_path: str, content: str) -> None:
        """Analyze a Python file for imports and symbols."""
        try:
            tree = ast.parse(content)
            imports = []
            symbols = {}

            for node in ast.walk(tree):
                # Track imports
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            imports.append((name.name, node.lineno))
                    else:  # ImportFrom
                        module = node.module if node.module else ''
                        for name in node.names:
                            imports.append(
                                (f"{module}.{name.name}" if module else name.name, node.lineno))

                # Track defined symbols with line numbers and context
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign)):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        symbol_name = node.name
                        symbol_type = 'class' if isinstance(
                            node, ast.ClassDef) else 'function'
                        line_no = node.lineno
                        context = self._extract_python_node_source(
                            content, node)

                        symbols[symbol_name] = {
                            'type': symbol_type,
                            'line_no': line_no,
                            'context': context,
                            'docstring': ast.get_docstring(node)
                        }
                    elif isinstance(node, ast.Assign):
                        # Handle variable assignments
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                symbol_name = target.id
                                line_no = node.lineno
                                context = self._extract_python_node_source(
                                    content, node)

                                symbols[symbol_name] = {
                                    'type': 'variable',
                                    'line_no': line_no,
                                    'context': context
                                }

            self.import_relations[file_path] = imports
            self.module_symbols[file_path] = symbols

        except Exception as e:
            print(f"Error analyzing Python file {file_path}: {e}")

    def _extract_python_node_source(self, source: str, node) -> str:
        """Extract the source code for a Python AST node."""
        try:
            lines = source.splitlines()
            if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                start = node.lineno - 1
                end = getattr(node, 'end_lineno', start + 1)
                return '\n'.join(lines[start:end])
            return ""
        except Exception:
            return ""

    def _analyze_cpp_file(self, file_path: str, content: str) -> None:
        """Analyze a C/C++ file for includes and symbols."""
        imports = []
        symbols = {}

        # Process content line by line
        lines = content.splitlines()

        # Regular expressions for C/C++ code analysis
        include_pattern = re.compile(r'#include\s+[<"]([^>"]+)[>"]')
        class_pattern = re.compile(r'(?:class|struct)\s+(\w+)')
        function_pattern = re.compile(
            r'(\w+)\s*\([^)]*\)\s*(?:const|override|final|noexcept)?\s*(?:{|;)')
        namespace_pattern = re.compile(r'namespace\s+(\w+)')

        for line_no, line in enumerate(lines, 1):
            # Find include statements
            include_match = include_pattern.search(line)
            if include_match:
                imports.append((include_match.group(1), line_no))

            # Find class/struct definitions
            class_match = class_pattern.search(line)
            if class_match:
                class_name = class_match.group(1)
                context = self._get_context_around_line(file_path, line_no)
                symbols[class_name] = {
                    'type': 'class',
                    'line_no': line_no,
                    'context': context
                }

            # Find function definitions (simplified)
            function_match = function_pattern.search(line)
            if function_match and not line.strip().startswith('#') and not line.strip().startswith('//'):
                function_name = function_match.group(1)
                # Skip some common keywords that might be mistaken for functions
                if function_name not in ['if', 'while', 'for', 'switch', 'return']:
                    context = self._get_context_around_line(file_path, line_no)
                    symbols[function_name] = {
                        'type': 'function',
                        'line_no': line_no,
                        'context': context
                    }

            # Find namespace definitions
            namespace_match = namespace_pattern.search(line)
            if namespace_match:
                namespace_name = namespace_match.group(1)
                context = self._get_context_around_line(file_path, line_no)
                symbols[namespace_name] = {
                    'type': 'namespace',
                    'line_no': line_no,
                    'context': context
                }

        self.import_relations[file_path] = imports
        self.module_symbols[file_path] = symbols

    def _analyze_java_file(self, file_path: str, content: str) -> None:
        """Analyze a Java file for imports and symbols."""
        imports = []
        symbols = {}

        # Process content line by line
        lines = content.splitlines()

        # Regular expressions for Java code analysis
        package_pattern = re.compile(r'package\s+([\w.]+)')
        import_pattern = re.compile(r'import\s+([\w.]+(?:\.\*)?)')
        class_pattern = re.compile(
            r'(?:public|private|protected)?\s*(?:abstract|final)?\s*class\s+(\w+)')
        interface_pattern = re.compile(
            r'(?:public|private|protected)?\s*interface\s+(\w+)')
        method_pattern = re.compile(
            r'(?:public|private|protected)?\s*(?:static|final|abstract)?\s*(?:[\w<>[\],\s]+)\s+(\w+)\s*\([^)]*\)')

        for line_no, line in enumerate(lines, 1):
            # Find package declaration
            package_match = package_pattern.search(line)
            if package_match:
                package_name = package_match.group(1)
                imports.append((package_name, line_no))

            # Find import statements
            import_match = import_pattern.search(line)
            if import_match:
                import_name = import_match.group(1)
                imports.append((import_name, line_no))

            # Find class definitions
            class_match = class_pattern.search(line)
            if class_match:
                class_name = class_match.group(1)
                context = self._get_context_around_line(file_path, line_no)
                symbols[class_name] = {
                    'type': 'class',
                    'line_no': line_no,
                    'context': context
                }

            # Find interface definitions
            interface_match = interface_pattern.search(line)
            if interface_match:
                interface_name = interface_match.group(1)
                context = self._get_context_around_line(file_path, line_no)
                symbols[interface_name] = {
                    'type': 'interface',
                    'line_no': line_no,
                    'context': context
                }

            # Find method definitions
            method_match = method_pattern.search(line)
            if method_match:
                method_name = method_match.group(1)
                # Skip some common keywords that might be mistaken for methods
                if method_name not in ['if', 'while', 'for', 'switch', 'return']:
                    context = self._get_context_around_line(file_path, line_no)
                    symbols[method_name] = {
                        'type': 'method',
                        'line_no': line_no,
                        'context': context
                    }

        self.import_relations[file_path] = imports
        self.module_symbols[file_path] = symbols

    def _analyze_go_file(self, file_path: str, content: str) -> None:
        """Analyze a Go file for imports and symbols."""
        imports = []
        symbols = {}

        # Process content line by line
        lines = content.splitlines()

        # Regular expressions for Go code analysis
        package_pattern = re.compile(r'package\s+(\w+)')
        import_single_pattern = re.compile(r'import\s+"([^"]+)"')
        import_multi_start_pattern = re.compile(r'import\s+\(')
        import_multi_line_pattern = re.compile(r'\s*"([^"]+)"')
        func_pattern = re.compile(r'func\s+(?:\([^)]+\)\s+)?(\w+)')
        struct_pattern = re.compile(r'type\s+(\w+)\s+struct')
        interface_pattern = re.compile(r'type\s+(\w+)\s+interface')

        in_import_block = False

        for line_no, line in enumerate(lines, 1):
            # Find package declaration
            package_match = package_pattern.search(line)
            if package_match:
                package_name = package_match.group(1)
                imports.append((f"package {package_name}", line_no))

            # Handle single-line imports
            import_match = import_single_pattern.search(line)
            if import_match:
                import_name = import_match.group(1)
                imports.append((import_name, line_no))

            # Handle multi-line imports
            if import_multi_start_pattern.search(line):
                in_import_block = True
                continue

            if in_import_block:
                if line.strip() == ')':
                    in_import_block = False
                    continue

                import_line_match = import_multi_line_pattern.search(line)
                if import_line_match:
                    import_name = import_line_match.group(1)
                    imports.append((import_name, line_no))

            # Find function definitions
            func_match = func_pattern.search(line)
            if func_match:
                func_name = func_match.group(1)
                context = self._get_context_around_line(file_path, line_no)
                symbols[func_name] = {
                    'type': 'function',
                    'line_no': line_no,
                    'context': context
                }

            # Find struct definitions
            struct_match = struct_pattern.search(line)
            if struct_match:
                struct_name = struct_match.group(1)
                context = self._get_context_around_line(file_path, line_no)
                symbols[struct_name] = {
                    'type': 'struct',
                    'line_no': line_no,
                    'context': context
                }

            # Find interface definitions
            interface_match = interface_pattern.search(line)
            if interface_match:
                interface_name = interface_match.group(1)
                context = self._get_context_around_line(file_path, line_no)
                symbols[interface_name] = {
                    'type': 'interface',
                    'line_no': line_no,
                    'context': context
                }

        self.import_relations[file_path] = imports
        self.module_symbols[file_path] = symbols

    def _find_references_in_file(self, file_path: str, content: str, language: str) -> None:
        """Find references to symbols in a file based on its language."""
        if language == "python":
            self._find_references_in_python_file(file_path, content)
        elif language == "cpp":
            self._find_references_in_cpp_file(file_path, content)
        elif language == "java":
            self._find_references_in_java_file(file_path, content)
        elif language == "go":
            self._find_references_in_go_file(file_path, content)

    def _find_references_in_python_file(self, file_path: str, content: str) -> None:
        """Find references to symbols in a Python file."""
        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                # Find variable references
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    symbol_name = node.id
                    line_no = node.lineno

                    # Track reference with context
                    if symbol_name not in self.symbol_references:
                        self.symbol_references[symbol_name] = []

                    context = self._get_context_around_line(file_path, line_no)
                    self.symbol_references[symbol_name].append(
                        (file_path, line_no, context))

                # Find attribute references (e.g., obj.method())
                elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                    attr_name = node.attr
                    line_no = node.lineno

                    if attr_name not in self.symbol_references:
                        self.symbol_references[attr_name] = []

                    context = self._get_context_around_line(file_path, line_no)
                    self.symbol_references[attr_name].append(
                        (file_path, line_no, context))

        except Exception as e:
            print(f"Error finding references in Python file {file_path}: {e}")

    def _find_references_in_cpp_file(self, file_path: str, content: str) -> None:
        """Find references to symbols in a C/C++ file."""
        # Get all symbol names from all files to check for references
        all_symbols = set()
        for symbols_dict in self.module_symbols.values():
            all_symbols.update(symbols_dict.keys())

        # Process content line by line
        lines = content.splitlines()

        for line_no, line in enumerate(lines, 1):
            # Look for references to any known symbol
            for symbol_name in all_symbols:
                # Simple pattern matching (would be more robust with proper C++ parsing)
                pattern = r'\b' + re.escape(symbol_name) + r'\b'
                if re.search(pattern, line):
                    # Check if this is not the definition line
                    if (file_path in self.module_symbols and
                        symbol_name in self.module_symbols[file_path] and
                            self.module_symbols[file_path][symbol_name]['line_no'] == line_no):
                        continue

                    if symbol_name not in self.symbol_references:
                        self.symbol_references[symbol_name] = []

                    context = self._get_context_around_line(file_path, line_no)
                    self.symbol_references[symbol_name].append(
                        (file_path, line_no, context))

    def _find_references_in_java_file(self, file_path: str, content: str) -> None:
        """Find references to symbols in a Java file."""
        # Get all symbol names from all files to check for references
        all_symbols = set()
        for symbols_dict in self.module_symbols.values():
            all_symbols.update(symbols_dict.keys())

        # Process content line by line
        lines = content.splitlines()

        for line_no, line in enumerate(lines, 1):
            # Skip comment lines and import/package declarations
            if (line.strip().startswith("//") or
                line.strip().startswith("/*") or
                line.strip().startswith("import ") or
                    line.strip().startswith("package ")):
                continue

            # Look for references to any known symbol
            for symbol_name in all_symbols:
                # Simple pattern matching with word boundaries
                pattern = r'\b' + re.escape(symbol_name) + r'\b'
                if re.search(pattern, line):
                    # Check if this is not the definition line
                    if (file_path in self.module_symbols and
                        symbol_name in self.module_symbols[file_path] and
                            self.module_symbols[file_path][symbol_name]['line_no'] == line_no):
                        continue

                    if symbol_name not in self.symbol_references:
                        self.symbol_references[symbol_name] = []

                    context = self._get_context_around_line(file_path, line_no)
                    self.symbol_references[symbol_name].append(
                        (file_path, line_no, context))

    def _find_references_in_go_file(self, file_path: str, content: str) -> None:
        """Find references to symbols in a Go file."""
        # Get all symbol names from all files to check for references
        all_symbols = set()
        for symbols_dict in self.module_symbols.values():
            all_symbols.update(symbols_dict.keys())

        # Process content line by line
        lines = content.splitlines()

        for line_no, line in enumerate(lines, 1):
            # Skip comment lines and import/package declarations
            if (line.strip().startswith("//") or
                line.strip().startswith("/*") or
                line.strip().startswith("import ") or
                    line.strip().startswith("package ")):
                continue

            # Look for references to any known symbol
            for symbol_name in all_symbols:
                # Simple pattern matching with word boundaries
                pattern = r'\b' + re.escape(symbol_name) + r'\b'
                if re.search(pattern, line):
                    # Check if this is not the definition line
                    if (file_path in self.module_symbols and
                        symbol_name in self.module_symbols[file_path] and
                            self.module_symbols[file_path][symbol_name]['line_no'] == line_no):
                        continue

                    if symbol_name not in self.symbol_references:
                        self.symbol_references[symbol_name] = []

                    context = self._get_context_around_line(file_path, line_no)
                    self.symbol_references[symbol_name].append(
                        (file_path, line_no, context))

    def _build_symbol_index(self) -> None:
        """Build a comprehensive index of all symbols and where they're defined/used."""
        # Initialize the symbol index
        self.symbol_index = {}

        # First, add all symbol definitions
        for file_path, symbols in self.module_symbols.items():
            for symbol_name, details in symbols.items():
                if symbol_name not in self.symbol_index:
                    self.symbol_index[symbol_name] = []

                self.symbol_index[symbol_name].append({
                    'file': file_path,
                    'type': 'definition',
                    'symbol_type': details['type'],
                    'line_no': details['line_no'],
                    'context': details.get('context', ''),
                    'docstring': details.get('docstring', '')
                })

        # Then, add all references
        for symbol_name, references in self.symbol_references.items():
            if symbol_name not in self.symbol_index:
                self.symbol_index[symbol_name] = []

            for file_path, line_no, context in references:
                # Avoid duplicating references if they're already in definitions
                if not any(ref['file'] == file_path and ref['line_no'] == line_no and ref['type'] == 'definition'
                           for ref in self.symbol_index.get(symbol_name, [])):
                    self.symbol_index[symbol_name].append({
                        'file': file_path,
                        'type': 'reference',
                        'line_no': line_no,
                        'context': context
                    })

    def build_graph(self) -> nx.DiGraph:
        """Build the NetworkX graph with enhanced node and edge information."""
        # We've already added basic file and directory nodes during parsing
        # Now add more detailed connections and data

        # Add nodes for all directories (if not already added)
        for directory in self.directories:
            if not self.graph.has_node(directory):
                self.graph.add_node(directory, type='directory')

            # Ensure parent directories exist and are connected
            parts = directory.split(os.sep)
            for i in range(1, len(parts)):
                parent_path = os.sep.join(parts[:i])
                if parent_path and not self.graph.has_node(parent_path):
                    self.graph.add_node(parent_path, type='directory')
                    self.directories.add(parent_path)

                # Connect parent to child directory
                if parent_path:
                    child_path = os.sep.join(parts[:i+1])
                    self.graph.add_edge(
                        parent_path, child_path, edge_type='contains_directory')

        # Add nodes for all files with indices and code snippet nodes
        for file_path, file_idx in self.file_index.items():
            language = self._detect_language(file_path)

            # Update file node if it exists, create it otherwise
            if self.graph.has_node(file_path):
                self.graph.nodes[file_path].update({
                    'file_index': file_idx,
                    'directory': os.path.dirname(file_path),
                    'language': language
                })
            else:
                self.graph.add_node(file_path,
                                    type='file',
                                    file_index=file_idx,
                                    directory=os.path.dirname(file_path),
                                    language=language)

            # Connect file to its directory
            directory = os.path.dirname(file_path)
            if directory:
                # Make sure the directory node exists
                if not self.graph.has_node(directory):
                    self.graph.add_node(directory, type='directory')
                    self.directories.add(directory)

                # Add edge from directory to file if it doesn't exist
                if not self.graph.has_edge(directory, file_path):
                    self.graph.add_edge(
                        directory, file_path, edge_type='contains_file')

            # Create snippet nodes for the entire file
            if file_path in self.file_contents:
                chunks = self._chunk_code(self.file_contents[file_path])
                for idx, chunk_info in enumerate(chunks):
                    snippet_node = f"{file_path}::snippet::{idx}"
                    self.graph.add_node(snippet_node,
                                        type='snippet',
                                        code_snippet=chunk_info['code_snippet'],
                                        start_line=chunk_info['start_line'],
                                        end_line=chunk_info['end_line'],
                                        language=language)
                    # Connect file node to snippet node
                    self.graph.add_edge(file_path, snippet_node,
                                        edge_type='contains_snippet',
                                        start_line=chunk_info['start_line'],
                                        end_line=chunk_info['end_line'])

            # Add nodes for symbols in this file
            for symbol, details in self.module_symbols.get(file_path, {}).items():
                symbol_node = f"{file_path}::{symbol}"
                self.graph.add_node(symbol_node,
                                    type='symbol',
                                    symbol_type=details['type'],
                                    line_number=details['line_no'],
                                    context=details.get('context', ''),
                                    docstring=details.get('docstring', ''))
                self.graph.add_edge(file_path, symbol_node,
                                    edge_type='defines',
                                    line_number=details['line_no'])

        # Add edges for imports with line numbers
        for file_path, imports in self.import_relations.items():
            for imp, line_no in imports:
                # Look for matching files or symbols
                for target_file, symbols in self.module_symbols.items():
                    if imp in symbols:
                        self.graph.add_edge(file_path,
                                            f"{target_file}::{imp}",
                                            edge_type='import',
                                            line_number=line_no)
                    # For Python, handle module imports
                    elif self._detect_language(file_path) == "python" and target_file.replace('.py', '').endswith(imp):
                        self.graph.add_edge(file_path,
                                            target_file,
                                            edge_type='import',
                                            line_number=line_no)
                    # For Java, handle package imports
                    elif self._detect_language(file_path) == "java" and imp.startswith(os.path.splitext(os.path.basename(target_file))[0]):
                        self.graph.add_edge(file_path,
                                            target_file,
                                            edge_type='import',
                                            line_number=line_no)

        # Add edges for symbol references
        for symbol, references in self.symbol_references.items():
            for file_path, line_no, context in references:
                # Find symbol nodes that match this reference
                for target_file, symbols in self.module_symbols.items():
                    if symbol in symbols:
                        # Create reference edge
                        self.graph.add_edge(file_path,
                                            f"{target_file}::{symbol}",
                                            edge_type='references',
                                            line_number=line_no,
                                            context=context)

        return self.graph

    def export_to_arango(self, url: str, username: str, password: str, db_name: str = "codebase",
                         graph_name: str = "Custom_Flask", node_collection: str = "nodes",
                         edge_collection: str = "edges", overwrite: bool = False) -> None:
        """
        Export the NetworkX graph to ArangoDB.

        Args:
            url: ArangoDB server URL
            username: ArangoDB username
            password: ArangoDB password
            db_name: Database name
            graph_name: Graph name
            node_collection: Node collection name
            edge_collection: Edge collection name
            overwrite: Whether to overwrite existing database
        """
        # Initialize ArangoDB client
        client = ArangoClient(hosts=url)
        sys_db = client.db('_system', username=username, password=password)

        # Create or use existing database
        if sys_db.has_database(db_name):
            if overwrite:
                sys_db.delete_database(db_name)
                sys_db.create_database(db_name)
                print(f"Database '{db_name}' recreated.")
            else:
                print(f"Using existing database '{db_name}'.")
        else:
            sys_db.create_database(db_name)
            print(f"Database '{db_name}' created.")

        # Connect to the database
        db = client.db(db_name, username=username, password=password)

        # Create or use existing collections
        if db.has_collection(node_collection):
            nodes = db.collection(node_collection)
            nodes.truncate()
        else:
            nodes = db.create_collection(node_collection)

        if db.has_collection(edge_collection):
            edges = db.collection(edge_collection)
            edges.truncate()
        else:
            edges = db.create_edge_collection(edge_collection)

        # Create or use existing graph
        if db.has_graph(graph_name):
            graph = db.graph(graph_name)
        else:
            graph = db.create_graph(graph_name)
            # Define edge definition
            graph.create_edge_definition(
                edge_collection=edge_collection,
                from_vertex_collections=[node_collection],
                to_vertex_collections=[node_collection]
            )

        # Prepare nodes for ArangoDB (ensuring unique IDs)
        node_mapping = {}  # Maps node names to ArangoDB keys

        # Add nodes to ArangoDB
        print("Adding nodes to ArangoDB...")
        for node_name, node_attrs in self.graph.nodes(data=True):
            # Create a sanitized key for ArangoDB
            key = re.sub(r'[^a-zA-Z0-9_\-]', '_', node_name)
            node_mapping[node_name] = key

            # Include all attributes and the original node name
            node_data = {
                '_key': key,
                'original_name': node_name
            }
            node_data.update(node_attrs)

            # Handle special data types for ArangoDB
            for attr, value in node_data.items():
                if isinstance(value, (set, tuple)):
                    node_data[attr] = list(value)

            # Insert the node
            nodes.insert(node_data)

        # Add edges to ArangoDB
        print("Adding edges to ArangoDB...")
        for src, dst, edge_attrs in self.graph.edges(data=True):
            # Create edge with proper from/to
            edge_data = {
                '_from': f"{node_collection}/{node_mapping[src]}",
                '_to': f"{node_collection}/{node_mapping[dst]}"
            }
            edge_data.update(edge_attrs)

            # Handle special data types for ArangoDB
            for attr, value in edge_data.items():
                if isinstance(value, (set, tuple)):
                    edge_data[attr] = list(value)

            # Insert the edge
            edges.insert(edge_data)

        print(
            f"Exported graph to ArangoDB: {len(self.graph.nodes())} nodes and {len(self.graph.edges())} edges.")

    def query_database(self, url: str, username: str, password: str, db_name: str = "codebase",
                       query: str = None) -> List[Dict]:
        """
        Execute a query against the ArangoDB database.

        Args:
            url: ArangoDB server URL
            username: ArangoDB username
            password: ArangoDB password
            db_name: Database name
            query: AQL query string

        Returns:
            Query results as a list of dictionaries
        """
        client = ArangoClient(hosts=url)
        db = client.db(db_name, username=username, password=password)

        if query is None:
            # Default query to get basic statistics
            query = """
            RETURN {
                "node_count": LENGTH(FOR v IN nodes RETURN v),
                "edge_count": LENGTH(FOR e IN edges RETURN e),
                "file_count": LENGTH(FOR v IN nodes FILTER v.type == 'file' RETURN v),
                "directory_count": LENGTH(FOR v IN nodes FILTER v.type == 'directory' RETURN v),
                "symbol_count": LENGTH(FOR v IN nodes FILTER v.type == 'symbol' RETURN v)
            }
            """

        cursor = db.aql.execute(query)
        return [doc for doc in cursor]

    def export_to_json(self, output_path: str) -> None:
        """
        Export the graph data to a JSON file for backup or analysis outside ArangoDB.

        Args:
            output_path: Path to write the JSON file
        """
        data = {
            "nodes": [],
            "edges": []
        }

        # Export nodes
        for node_name, attrs in self.graph.nodes(data=True):
            node_data = {"id": node_name}
            node_data.update(attrs)
            data["nodes"].append(node_data)

        # Export edges
        for src, dst, attrs in self.graph.edges(data=True):
            edge_data = {
                "source": src,
                "target": dst
            }
            edge_data.update(attrs)
            data["edges"].append(edge_data)

        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Exported graph to JSON file: {output_path}")

    def analyze_codebase(self) -> Dict[str, any]:
        """
        Perform basic analysis on the codebase and return statistics.

        Returns:
            Dictionary with analysis results
        """
        stats = {
            "total_files": len(self.file_index),
            "total_directories": len(self.directories),
            "total_symbols": sum(len(symbols) for symbols in self.module_symbols.values()),
            "languages": {},
            "file_sizes": {
                "min": float('inf'),
                "max": 0,
                "avg": 0
            },
            "symbol_types": {}
        }

        # Count files by language
        for file_path in self.file_index:
            lang = self._detect_language(file_path)
            stats["languages"][lang] = stats["languages"].get(lang, 0) + 1

            # Track file sizes
            file_size = len(self.file_contents.get(file_path, ""))
            stats["file_sizes"]["min"] = min(
                stats["file_sizes"]["min"], file_size)
            stats["file_sizes"]["max"] = max(
                stats["file_sizes"]["max"], file_size)

        # Calculate average file size
        if stats["total_files"] > 0:
            total_size = sum(len(content)
                             for content in self.file_contents.values())
            stats["file_sizes"]["avg"] = total_size / stats["total_files"]
        else:
            stats["file_sizes"]["min"] = 0

        # Count symbols by type
        for symbols in self.module_symbols.values():
            for symbol, details in symbols.items():
                symbol_type = details.get("type", "unknown")
                stats["symbol_types"][symbol_type] = stats["symbol_types"].get(
                    symbol_type, 0) + 1

        return stats

    def run_workflow(self, code_path: str, arango_url: str, username: str, password: str,
                     db_name: str = "codebase") -> Dict:
        """
        Run the complete workflow: parse files, build graph, export to ArangoDB, and analyze.

        Args:
            code_path: Path to the codebase
            arango_url: ArangoDB server URL
            username: ArangoDB username
            password: ArangoDB password
            db_name: Database name

        Returns:
            Analysis results
        """
        print(f"Processing codebase at: {code_path}")

        # Parse files
        self.parse_files()
        print(
            f"Parsed {len(self.file_index)} files and {len(self.directories)} directories")

        # Build graph
        self.build_graph()
        print(
            f"Built graph with {len(self.graph.nodes())} nodes and {len(self.graph.edges())} edges")

        # Export to ArangoDB
        self.export_to_arango(
            url=arango_url,
            username=username,
            password=password,
            db_name=db_name,
            overwrite=True
        )

        # Analyze codebase
        analysis = self.analyze_codebase()
        print(f"Analysis complete: {analysis}")

        return analysis

    def validate_graph_and_data(self) -> dict:
        """
        Validate the parsed data and graph construction.
        Returns a detailed report on what was found and potential issues.
        """
        report = {
            "files": {
                "count": len(self.file_index),
                "samples": list(self.file_index.keys())[:5],  # First 5 files
                "extensions": {}
            },
            "directories": {
                "count": len(self.directories),
                "samples": list(self.directories)[:5]  # First 5 directories
            },
            "symbols": {
                "count": sum(len(symbols) for symbols in self.module_symbols.values()),
                "by_type": {},
                "samples": []
            },
            "graph": {
                "nodes": self.graph.number_of_nodes(),
                "edges": self.graph.number_of_edges(),
                "node_types": {},
                "edge_types": {}
            },
            "possible_issues": []
        }

        # Check file extensions
        for file_path in self.file_index:
            _, ext = os.path.splitext(file_path)
            ext = ext.lower()
            report["files"]["extensions"][ext] = report["files"]["extensions"].get(
                ext, 0) + 1

        # Check for supported extensions
        supported_exts = []
        for lang, exts in self.language_extensions.items():
            supported_exts.extend(exts)

        if set(report["files"]["extensions"].keys()).isdisjoint(supported_exts):
            report["possible_issues"].append(
                "No files with supported extensions found.")

        # Check symbol types
        for file_path, symbols in self.module_symbols.items():
            for symbol_name, details in symbols.items():
                symbol_type = details['type']
                report["symbols"]["by_type"][symbol_type] = report["symbols"]["by_type"].get(
                    symbol_type, 0) + 1

                if len(report["symbols"]["samples"]) < 5:
                    report["symbols"]["samples"].append({
                        "name": symbol_name,
                        "file": file_path,
                        "type": symbol_type,
                        "line": details['line_no']
                    })

        # Check graph node and edge types
        for _, data in self.graph.nodes(data=True):
            node_type = data.get('type', 'unknown')
            report["graph"]["node_types"][node_type] = report["graph"]["node_types"].get(
                node_type, 0) + 1

        for _, _, data in self.graph.edges(data=True):
            edge_type = data.get('edge_type', 'unknown')
            report["graph"]["edge_types"][edge_type] = report["graph"]["edge_types"].get(
                edge_type, 0) + 1

        # Check if nodes match files and directories
        if report["graph"]["node_types"].get("file", 0) != report["files"]["count"]:
            report["possible_issues"].append(
                f"Mismatch between file count ({report['files']['count']}) and file nodes in graph ({report['graph']['node_types'].get('file', 0)})"
            )

        if report["graph"]["node_types"].get("directory", 0) != report["directories"]["count"]:
            report["possible_issues"].append(
                f"Mismatch between directory count ({report['directories']['count']}) and directory nodes in graph ({report['graph']['node_types'].get('directory', 0)})"
            )

        # Check if symbols have corresponding nodes
        symbol_count = report["symbols"]["count"]
        symbol_nodes = report["graph"]["node_types"].get("symbol", 0)
        if symbol_count != symbol_nodes:
            report["possible_issues"].append(
                f"Mismatch between symbol count ({symbol_count}) and symbol nodes in graph ({symbol_nodes})"
            )

        # Validate directory structure
        if report["directories"]["count"] > 0 and report["files"]["count"] > 0:
            # Check if files are connected to their directories
            contains_file_edges = report["graph"]["edge_types"].get(
                "contains_file", 0)
            if contains_file_edges < report["files"]["count"]:
                report["possible_issues"].append(
                    f"Some files may not be properly connected to their directories ({contains_file_edges} edges for {report['files']['count']} files)"
                )

        return report
