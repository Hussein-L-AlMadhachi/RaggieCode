#!/usr/bin/env python3
"""
Export SQLite code index to JSON format.
"""

import json
import sqlite3
from pathlib import Path


def export_to_json(db_path, output_file):
    """Export SQLite database to JSON format."""
    print(f"Reading database from {db_path}...")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Initialize JSON structure
    json_index = {
        "files": {},
        "total_functions": 0,
        "total_classes": 0,
        "total_variables": 0,
        "total_methods": 0,
        "total_type_defs": 0,
        "total_structs": 0,
        "total_interfaces": 0
    }
    
    cursor = conn.cursor()
    
    # Get all files
    cursor.execute("SELECT * FROM files ORDER BY id")
    files = cursor.fetchall()
    
    print(f"Exporting {len(files)} files...")
    
    for file_row in files:
        file_id = file_row['id']
        relative_path = file_row['path']
        
        file_info = {
            "path": relative_path,
            "absolute_path": file_row['absolute_path'],
            "language": file_row['language'],
            "functions": [],
            "classes": [],
            "variables": [],
            "type_aliases": [],
            "structs": [],
            "interfaces": []
        }
        
        # Get top-level functions (no parent)
        cursor.execute(
            """SELECT * FROM functions 
               WHERE file_id = ? AND parent_id IS NULL 
               ORDER BY id""",
            (file_id,)
        )
        for func_row in cursor.fetchall():
            func_info = {
                "type": func_row['type'],
                "name": func_row['name'],
                "location": json.loads(func_row['location']),
                "parameters": json.loads(func_row['parameters']),
                "return_type": func_row['return_type'],
                "docstring": func_row['docstring']
            }
            if func_row['receiver']:
                func_info['receiver'] = func_row['receiver']
            file_info["functions"].append(func_info)
            json_index["total_functions"] += 1
        
        # Get classes (top-level only)
        cursor.execute(
            """SELECT * FROM classes 
               WHERE file_id = ? AND parent_id IS NULL 
               ORDER BY id""",
            (file_id,)
        )
        classes_map = {}  # Map class_id to class info for method lookup
        
        for class_row in cursor.fetchall():
            class_id = class_row['id']
            class_info = {
                "type": "class",
                "name": class_row['name'],
                "location": json.loads(class_row['location']),
                "base_classes": json.loads(class_row['base_classes']),
                "docstring": class_row['docstring'],
                "methods": [],
                "nested_classes": [],
                "variables": []
            }
            classes_map[class_id] = class_info
            file_info["classes"].append(class_info)
            json_index["total_classes"] += 1
        
        # Get nested classes
        cursor.execute(
            """SELECT * FROM classes 
               WHERE file_id = ? AND parent_id IS NOT NULL 
               ORDER BY id""",
            (file_id,)
        )
        for class_row in cursor.fetchall():
            class_id = class_row['id']
            parent_id = class_row['parent_id']
            
            class_info = {
                "type": "class",
                "name": class_row['name'],
                "location": json.loads(class_row['location']),
                "base_classes": json.loads(class_row['base_classes']),
                "docstring": class_row['docstring'],
                "methods": [],
                "nested_classes": [],
                "variables": []
            }
            
            # Add to parent's nested_classes
            if parent_id in classes_map:
                classes_map[parent_id]["nested_classes"].append(class_info)
                classes_map[class_id] = class_info
                json_index["total_classes"] += 1
        
        # Get methods (functions with parent)
        cursor.execute(
            """SELECT * FROM functions 
               WHERE file_id = ? AND parent_id IS NOT NULL 
               ORDER BY id""",
            (file_id,)
        )
        for func_row in cursor.fetchall():
            parent_id = func_row['parent_id']
            parent_type = func_row['parent_type']
            
            method_info = {
                "type": func_row['type'],
                "name": func_row['name'],
                "location": json.loads(func_row['location']),
                "parameters": json.loads(func_row['parameters']),
                "return_type": func_row['return_type'],
                "docstring": func_row['docstring']
            }
            if func_row['receiver']:
                method_info['receiver'] = func_row['receiver']
            
            # Add to parent class's methods
            if parent_type == 'class' and parent_id in classes_map:
                classes_map[parent_id]["methods"].append(method_info)
                json_index["total_methods"] += 1
        
        # Get top-level variables (no parent)
        cursor.execute(
            """SELECT * FROM variables 
               WHERE file_id = ? AND parent_id IS NULL 
               ORDER BY id""",
            (file_id,)
        )
        for var_row in cursor.fetchall():
            var_info = {
                "type": var_row['type'],
                "name": var_row['name'],
                "location": json.loads(var_row['location'])
            }
            if var_row['field_type']:
                var_info['field_type'] = var_row['field_type']
            file_info["variables"].append(var_info)
            json_index["total_variables"] += 1
        
        # Get class attributes (variables with parent)
        cursor.execute(
            """SELECT * FROM variables 
               WHERE file_id = ? AND parent_id IS NOT NULL 
               ORDER BY id""",
            (file_id,)
        )
        for var_row in cursor.fetchall():
            parent_id = var_row['parent_id']
            parent_type = var_row['parent_type']
            
            var_info = {
                "type": var_row['type'],
                "name": var_row['name'],
                "location": json.loads(var_row['location'])
            }
            if var_row['field_type']:
                var_info['field_type'] = var_row['field_type']
            
            # Add to parent class's variables
            if parent_type == 'class' and parent_id in classes_map:
                classes_map[parent_id]["variables"].append(var_info)
                json_index["total_variables"] += 1
        
        # Get type aliases
        cursor.execute(
            "SELECT * FROM type_aliases WHERE file_id = ? ORDER BY id",
            (file_id,)
        )
        for type_row in cursor.fetchall():
            type_info = {
                "type": "type_alias",
                "name": type_row['name'],
                "location": json.loads(type_row['location']),
                "type_definition": type_row['type_definition']
            }
            file_info["type_aliases"].append(type_info)
            json_index["total_type_defs"] += 1
        
        # Get structs
        cursor.execute(
            "SELECT * FROM structs WHERE file_id = ? ORDER BY id",
            (file_id,)
        )
        for struct_row in cursor.fetchall():
            struct_info = {
                "type": "struct",
                "name": struct_row['name'],
                "location": json.loads(struct_row['location']),
                "methods": [],
                "fields": []
            }
            file_info["structs"].append(struct_info)
            json_index["total_structs"] += 1
        
        # Get interfaces
        cursor.execute(
            "SELECT * FROM interfaces WHERE file_id = ? ORDER BY id",
            (file_id,)
        )
        for interface_row in cursor.fetchall():
            interface_info = {
                "type": "interface",
                "name": interface_row['name'],
                "location": json.loads(interface_row['location']),
                "methods": []
            }
            file_info["interfaces"].append(interface_info)
            json_index["total_interfaces"] += 1
        
        json_index["files"][relative_path] = file_info
    
    conn.close()
    
    # Write to JSON file
    print(f"Writing JSON to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(json_index, f, indent=2)
    
    print(f"\nExport complete!")
    print(f"JSON saved to {output_file}")
    
    # Print summary
    print("\n--- Export Summary ---")
    print(f"Total files: {len(json_index['files'])}")
    print(f"Total functions: {json_index['total_functions']}")
    print(f"Total methods: {json_index['total_methods']}")
    print(f"Total classes: {json_index['total_classes']}")
    print(f"Total structs: {json_index['total_structs']}")
    print(f"Total interfaces: {json_index['total_interfaces']}")
    print(f"Total variables: {json_index['total_variables']}")
    print(f"Total type aliases: {json_index['total_type_defs']}")


def main():
    """Main entry point for CLI usage."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python export_to_json.py <db_file> [output_json]")
        print("Example: python export_to_json.py code_index.db code_index.json")
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else db_path.rsplit('.', 1)[0] + '.json'
    
    if not Path(db_path).exists():
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    try:
        export_to_json(db_path, output_file)
    except Exception as e:
        print(f"Error during export: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
