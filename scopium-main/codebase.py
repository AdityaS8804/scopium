import os
import ast
import networkx as nx
import matplotlib.pyplot as plt
from typing import Dict, Set, List, Tuple
import json

class CodebaseVisualizer:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.graph = nx.DiGraph()
        self.file_contents: Dict[str, str] = {}
        self.import_relations: Dict[str, Set[str]] = {}
        self.module_symbols: Dict[str, Set[str]] = {}

    def parse_files(self) -> None:
        """Parse all Python files in the directory and build import relationships."""
        for root, _, files in os.walk(self.root_dir):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.root_dir)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            self.file_contents[rel_path] = content
                            self._analyze_file(rel_path, content)
                    except Exception as e:
                        print(f"Error parsing {file_path}: {e}")

    def _analyze_file(self, file_path: str, content: str) -> None:
        """Analyze a single file for imports and symbols."""
        try:
            tree = ast.parse(content)
            imports = set()
            symbols = set()

            for node in ast.walk(tree):
                # Track imports
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            imports.add(name.name)
                    else:  # ImportFrom
                        module = node.module if node.module else ''
                        imports.add(module)

                # Track defined symbols (functions, classes)
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    symbols.add(node.name)

            self.import_relations[file_path] = imports
            self.module_symbols[file_path] = symbols

        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")

    def build_graph(self) -> None:
        """Build the NetworkX graph from parsed information."""
        # Add nodes for all files
        for file_path in self.file_contents.keys():
            self.graph.add_node(file_path, type='file')
            
            # Add nodes for symbols in this file
            for symbol in self.module_symbols.get(file_path, set()):
                symbol_node = f"{file_path}::{symbol}"
                self.graph.add_node(symbol_node, type='symbol')
                self.graph.add_edge(file_path, symbol_node)

        # Add edges for imports
        for file_path, imports in self.import_relations.items():
            for imp in imports:
                # Look for matching files or symbols
                for target_file, symbols in self.module_symbols.items():
                    if imp in symbols:
                        self.graph.add_edge(file_path, f"{target_file}::{imp}")
                    elif target_file.replace('.py', '').endswith(imp):
                        self.graph.add_edge(file_path, target_file)

    def visualize(self, output_path: str = 'codebase_graph.png') -> None:
        """Generate a visualization of the codebase graph."""
        plt.figure(figsize=(20, 20))
        
        # Create layout
        pos = nx.spring_layout(self.graph, k=1, iterations=50)
        
        # Draw nodes
        file_nodes = [n for n, d in self.graph.nodes(data=True) if d['type'] == 'file']
        symbol_nodes = [n for n, d in self.graph.nodes(data=True) if d['type'] == 'symbol']
        
        nx.draw_networkx_nodes(self.graph, pos, nodelist=file_nodes, 
                             node_color='lightblue', node_size=3000, alpha=0.7)
        nx.draw_networkx_nodes(self.graph, pos, nodelist=symbol_nodes,
                             node_color='lightgreen', node_size=2000, alpha=0.7)
        
        # Draw edges
        nx.draw_networkx_edges(self.graph, pos, edge_color='gray', arrows=True)
        
        # Add labels
        labels = {node: node.split('::')[-1] for node in self.graph.nodes()}
        nx.draw_networkx_labels(self.graph, pos, labels, font_size=8)
        
        plt.title("Codebase Dependency Graph")
        plt.axis('off')
        plt.savefig(output_path, format='png', dpi=300, bbox_inches='tight')
        plt.close()

    def export_graph_json(self, output_path: str = 'codebase_graph.json') -> None:
        """Export the graph structure to JSON for external visualization."""
        graph_data = {
            'nodes': [{'id': node, 'type': data['type']} 
                     for node, data in self.graph.nodes(data=True)],
            'links': [{'source': source, 'target': target} 
                     for source, target in self.graph.edges()]
        }
        
        with open(output_path, 'w') as f:
            json.dump(graph_data, f, indent=2)

    def get_file_content(self, file_path: str) -> str:
        """Retrieve the content of a specific file."""
        return self.file_contents.get(file_path, '')

    def get_dependencies(self, file_path: str) -> List[str]:
        """Get all dependencies for a specific file."""
        dependencies = []
        if file_path in self.graph:
            dependencies = list(self.graph.successors(file_path))
        return dependencies

    def analyze_complexity(self) -> Dict[str, int]:
        """Analyze complexity based on number of dependencies."""
        return {node: len(list(self.graph.successors(node))) 
                for node in self.graph.nodes() 
                if self.graph.nodes[node]['type'] == 'file'}
    
# Initialize and use the visualizer
visualizer = CodebaseVisualizer("../flask")
visualizer.parse_files()
visualizer.build_graph()
visualizer.visualize()
visualizer.export_graph_json()

# Get specific file analysis
dependencies = visualizer.get_dependencies("updated_clientf.py")
complexity = visualizer.analyze_complexity()