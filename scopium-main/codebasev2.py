import os
import ast
import networkx as nx
import matplotlib.pyplot as plt
from typing import Dict, Set, List, Tuple, Optional
import json

class CodebaseVisualizer:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.graph = nx.DiGraph()
        self.file_contents: Dict[str, str] = {}
        self.import_relations: Dict[str, Set[str]] = {}
        self.module_symbols: Dict[str, Dict[str, Dict[str, int]]] = {}  # file -> {symbol -> {type, line_no}}
        self.file_index: Dict[str, int] = {}  # Maps files to indices
        self.current_index = 0
        self.directories: Set[str] = set()

    def _get_next_index(self) -> int:
        """Get next available index for file indexing."""
        self.current_index += 1
        return self.current_index

    def parse_files(self) -> None:
        """Parse all Python files in the directory and build relationships."""
        # First pass: Index all files and create directory nodes
        for root, dirs, files in os.walk(self.root_dir):
            # Add directory node
            rel_dir = os.path.relpath(root, self.root_dir)
            if rel_dir != '.':
                self.directories.add(rel_dir)
                self.graph.add_node(rel_dir, type='directory')

            # Index Python files
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.root_dir)
                    self.file_index[rel_path] = self._get_next_index()
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            self.file_contents[rel_path] = content
                            self._analyze_file(rel_path, content)
                    except Exception as e:
                        print(f"Error parsing {file_path}: {e}")

        # Second pass: Create directory relationships
        self._build_directory_relationships()

    def _analyze_file(self, file_path: str, content: str) -> None:
        """Analyze a single file for imports and symbols with line numbers."""
        try:
            tree = ast.parse(content)
            imports = set()
            symbols = {}

            for node in ast.walk(tree):
                # Track imports
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            imports.add((name.name, node.lineno))
                    else:  # ImportFrom
                        module = node.module if node.module else ''
                        imports.add((module, node.lineno))

                # Track defined symbols with line numbers
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    symbols[node.name] = {
                        'type': 'class' if isinstance(node, ast.ClassDef) else 'function',
                        'line_no': node.lineno
                    }

            self.import_relations[file_path] = imports
            self.module_symbols[file_path] = symbols

        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")

    def _build_directory_relationships(self) -> None:
        """Build relationships between files in the same directory."""
        # Group files by directory
        dir_files: Dict[str, List[str]] = {}
        for file_path in self.file_contents.keys():
            directory = os.path.dirname(file_path)
            if directory not in dir_files:
                dir_files[directory] = []
            dir_files[directory].append(file_path)

        # Create edges between files in the same directory
        for directory, files in dir_files.items():
            for i, file1 in enumerate(files):
                for file2 in files[i+1:]:
                    self.graph.add_edge(file1, file2, 
                                      edge_type='sub-dir',
                                      directory=directory)

    def build_graph(self) -> None:
        """Build the NetworkX graph with enhanced node and edge information."""
        # Add nodes for all files with indices
        for file_path, file_idx in self.file_index.items():
            self.graph.add_node(file_path, 
                              type='file',
                              file_index=file_idx,
                              directory=os.path.dirname(file_path))
            
            # Add nodes for symbols in this file
            for symbol, details in self.module_symbols.get(file_path, {}).items():
                symbol_node = f"{file_path}::{symbol}"
                self.graph.add_node(symbol_node, 
                                  type='symbol',
                                  symbol_type=details['type'],
                                  line_number=details['line_no'])
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
                    elif target_file.replace('.py', '').endswith(imp):
                        self.graph.add_edge(file_path, 
                                          target_file,
                                          edge_type='import',
                                          line_number=line_no)

        # Connect files to their directory nodes
        for file_path in self.file_contents.keys():
            directory = os.path.dirname(file_path)
            if directory and directory in self.directories:
                self.graph.add_edge(directory, file_path, edge_type='contains')

    def visualize(self, output_path: str = 'codebase_graph.png') -> None:
        """Generate an enhanced visualization of the codebase graph."""
        plt.figure(figsize=(20, 20))
        
        # Create layout
        pos = nx.spring_layout(self.graph, k=2, iterations=50)
        
        # Draw different types of nodes
        directory_nodes = [n for n, d in self.graph.nodes(data=True) if d.get('type') == 'directory']
        file_nodes = [n for n, d in self.graph.nodes(data=True) if d.get('type') == 'file']
        symbol_nodes = [n for n, d in self.graph.nodes(data=True) if d.get('type') == 'symbol']
        
        # Draw nodes with different colors
        nx.draw_networkx_nodes(self.graph, pos, nodelist=directory_nodes,
                             node_color='lightgray', node_size=4000, alpha=0.7)
        nx.draw_networkx_nodes(self.graph, pos, nodelist=file_nodes,
                             node_color='lightblue', node_size=3000, alpha=0.7)
        nx.draw_networkx_nodes(self.graph, pos, nodelist=symbol_nodes,
                             node_color='lightgreen', node_size=2000, alpha=0.7)
        
        # Draw edges with different colors based on type
        edge_colors = {'import': 'red', 'defines': 'green', 'sub-dir': 'blue', 'contains': 'gray'}
        for edge_type, color in edge_colors.items():
            edges = [(u, v) for (u, v, d) in self.graph.edges(data=True) 
                    if d.get('edge_type') == edge_type]
            if edges:
                nx.draw_networkx_edges(self.graph, pos, edgelist=edges,
                                     edge_color=color, arrows=True)
        
        # Add labels with file indices
        labels = {}
        for node in self.graph.nodes():
            if self.graph.nodes[node]['type'] == 'file':
                idx = self.graph.nodes[node]['file_index']
                labels[node] = f"{node} ({idx})"
            else:
                labels[node] = node.split('::')[-1]
                
        nx.draw_networkx_labels(self.graph, pos, labels, font_size=8)
        
        plt.title("Enhanced Codebase Dependency Graph")
        plt.axis('off')
        plt.savefig(output_path, format='png', dpi=300, bbox_inches='tight')
        plt.close()

    def export_graph_json(self, output_path: str = 'codebase_graph.json') -> None:
        """Export the enhanced graph structure to JSON."""
        graph_data = {
            'nodes': [
                {
                    'id': node,
                    'type': data['type'],
                    'file_index': data.get('file_index'),
                    'directory': data.get('directory'),
                    'symbol_type': data.get('symbol_type'),
                    'line_number': data.get('line_number')
                } 
                for node, data in self.graph.nodes(data=True)
            ],
            'links': [
                {
                    'source': source,
                    'target': target,
                    'type': data.get('edge_type'),
                    'line_number': data.get('line_number'),
                    'directory': data.get('directory')
                } 
                for source, target, data in self.graph.edges(data=True)
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(graph_data, f, indent=2)

# Example usage
visualizer = CodebaseVisualizer("../flask")
visualizer.parse_files()
visualizer.build_graph()
visualizer.visualize()
visualizer.export_graph_json()