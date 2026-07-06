#!/usr/bin/env python3
"""
Examples demonstrating the Code Index SDK for AI Agents.
"""

from indexing.code_index_sdk import CodeIndexSDK


def example_basic_queries():
    """Basic query examples."""
    print("=== Basic Queries ===\n")
    
    with CodeIndexSDK("code_index.db") as sdk:
        # Get all files
        files = sdk.get_files()
        print(f"Total files: {len(files)}")
        for file in files[:5]:
            print(f"  - {file.path} ({file.language})")
        
        # Get statistics
        stats = sdk.get_statistics()
        print(f"\nStatistics: {stats}")
        
        # Get language breakdown
        lang_stats = sdk.get_language_statistics()
        print(f"Language breakdown: {lang_stats}")


def example_function_search():
    """Function search examples."""
    print("\n=== Function Search ===\n")
    
    with CodeIndexSDK("code_index.db") as sdk:
        # Search for functions by pattern
        render_funcs = sdk.search_functions("render")
        print(f"Functions matching 'render': {len(render_funcs)}")
        for func in render_funcs[:3]:
            print(f"  - {func.name} in {func.file_path}")
            print(f"    Parameters: {[p['name'] for p in func.parameters]}")
        
        # Get specific function by name
        main_funcs = sdk.get_function_by_name("main")
        print(f"\nFunctions named 'main': {len(main_funcs)}")
        for func in main_funcs:
            print(f"  - {func.file_path}:{func.location.start_line}")


def example_class_exploration():
    """Class exploration examples."""
    print("\n=== Class Exploration ===\n")
    
    with CodeIndexSDK("code_index.db") as sdk:
        # Search for classes
        classes = sdk.search_classes("Service")
        print(f"Classes matching 'Service': {len(classes)}")
        
        if classes:
            cls = classes[0]
            print(f"\nExploring class: {cls.name}")
            print(f"  File: {cls.file_path}")
            print(f"  Base classes: {cls.base_classes}")
            
            # Get class methods
            methods = sdk.get_class_methods(cls.id)
            print(f"  Methods ({len(methods)}):")
            for method in methods[:5]:
                print(f"    - {method.name}({', '.join(p['name'] for p in method.parameters)})")
            
            # Get class variables
            variables = sdk.get_class_variables(cls.id)
            print(f"  Variables ({len(variables)}):")
            for var in variables[:5]:
                print(f"    - {var.name}: {var.field_type or 'unknown'}")
            
            # Get nested classes
            nested = sdk.get_nested_classes(cls.id)
            if nested:
                print(f"  Nested classes: {[c.name for c in nested]}")


def example_file_analysis():
    """File analysis examples."""
    print("\n=== File Analysis ===\n")
    
    with CodeIndexSDK("code_index.db") as sdk:
        # Get a specific file
        file = sdk.get_files()[0]
        print(f"Analyzing file: {file.path}")
        
        # Get complete file summary
        summary = sdk.get_file_summary(file.id)
        print(f"\nFile summary:")
        print(f"  Functions: {len(summary['functions'])}")
        print(f"  Classes: {len(summary['classes'])}")
        print(f"  Variables: {len(summary['variables'])}")
        print(f"  Type aliases: {len(summary['type_aliases'])}")


def example_cross_reference():
    """Cross-reference examples."""
    print("\n=== Cross-Reference ===\n")
    
    with CodeIndexSDK("code_index.db") as sdk:
        # Find all usages of a pattern across different entity types
        results = sdk.search_all("auth")
        print(f"Results for 'auth' pattern:")
        print(f"  Functions: {len(results['functions'])}")
        print(f"  Classes: {len(results['classes'])}")
        print(f"  Variables: {len(results['variables'])}")
        print(f"  Type aliases: {len(results['type_aliases'])}")
        
        # Show some results
        if results['functions']:
            print(f"\n  Sample functions:")
            for func in results['functions'][:3]:
                print(f"    - {func['name']} in {func['file_path']}")


def example_ai_agent_workflow():
    """Example workflow for an AI agent."""
    print("\n=== AI Agent Workflow ===\n")
    
    with CodeIndexSDK("code_index.db") as sdk:
        # Agent wants to understand the codebase structure
        print("1. Understanding codebase structure...")
        stats = sdk.get_statistics()
        lang_stats = sdk.get_language_statistics()
        print(f"   Total files: {stats['total_files']}")
        print(f"   Languages: {list(lang_stats.keys())}")
        
        # Agent wants to find authentication-related code
        print("\n2. Finding authentication code...")
        auth_funcs = sdk.search_functions("auth")
        auth_classes = sdk.search_classes("Auth")
        print(f"   Found {len(auth_funcs)} auth-related functions")
        print(f"   Found {len(auth_classes)} auth-related classes")
        
        # Agent wants to explore a specific class
        if auth_classes:
            print(f"\n3. Exploring {auth_classes[0].name} class...")
            cls = auth_classes[0]
            methods = sdk.get_class_methods(cls.id)
            print(f"   Class has {len(methods)} methods")
            
            # Agent wants to understand method signatures
            print(f"\n4. Method signatures:")
            for method in methods[:5]:
                params = ", ".join(f"{p['name']}: {p.get('type', 'any')}" for p in method.parameters)
                return_type = method.return_type or "void"
                print(f"   {method.name}({params}) -> {return_type}")


def example_context_manager():
    """Context manager usage example."""
    print("\n=== Context Manager ===\n")
    
    # Using context manager for automatic cleanup
    with CodeIndexSDK("code_index.db") as sdk:
        files = sdk.get_files()
        print(f"Files in context: {len(files)}")
    
    # Connection is automatically closed here
    print("Connection closed automatically.")


def example_manual_connection():
    """Manual connection management example."""
    print("\n=== Manual Connection ===\n")
    
    sdk = CodeIndexSDK("code_index.db")
    try:
        files = sdk.get_files()
        print(f"Files: {len(files)}")
    finally:
        sdk.close()
    print("Connection closed manually.")


def example_internal_external_imports():
    """Example of filtering imports by internal/external dependencies."""
    print("\n=== Internal vs External Imports ===\n")
    
    with CodeIndexSDK("code_index.db") as sdk:
        # Get all files
        files = sdk.get_files()
        if not files:
            print("No files in database. Please run indexing first.")
            return
        
        # Analyze first file
        file = files[0]
        print(f"Analyzing file: {file.path}")
        
        # Get all imports
        all_imports = sdk.get_file_imports(file.id)
        print(f"\nTotal imports: {len(all_imports)}")
        
        # Get external imports
        external_imports = sdk.get_external_imports(file.id)
        print(f"External (third-party) imports: {len(external_imports)}")
        for imp in external_imports[:5]:
            print(f"  - {imp.name}")
        
        # Get internal imports
        internal_imports = sdk.get_internal_imports(file.id)
        print(f"\nInternal (project) imports: {len(internal_imports)}")
        for imp in internal_imports[:5]:
            print(f"  - {imp.name}")
        
        # Get all external imports across the entire codebase
        print("\n--- All External Dependencies in Codebase ---")
        all_external = sdk.get_external_imports()
        # Group by import name to show unique external dependencies
        unique_external = {}
        for imp in all_external:
            if imp.name not in unique_external:
                unique_external[imp.name] = []
            unique_external[imp.name].append(imp.file_path)
        
        print(f"Unique external dependencies: {len(unique_external)}")
        for dep_name, files in list(unique_external.items())[:10]:
            print(f"  - {dep_name} (used in {len(files)} file(s))")


def example_source_body_reading():
    """Source body reading examples."""
    print("\n=== Source Body Reading ===\n")

    with CodeIndexSDK("code_index.db") as sdk:
        # Read a function body by name
        funcs = sdk.get_functions()
        if not funcs:
            print("No functions in database. Please run indexing first.")
            return

        func_name = funcs[0].name
        print(f"Reading body of function: {func_name}")
        body = sdk.get_function_body(func_name)
        if body:
            preview = body[:200] + "..." if len(body) > 200 else body
            print(f"\n{preview}")
        else:
            print("  (source file not resolvable)")

        # Disambiguate by file path when the same name appears in multiple files
        matches = sdk.get_function_by_name(func_name)
        if len(matches) > 1:
            print(f"\n'{func_name}' appears in {len(matches)} files — reading from first:")
            body = sdk.get_function_body(func_name, file_path=matches[0].file_path)
            if body:
                print(body[:200])

        # Read a class body
        classes = sdk.get_classes()
        if classes:
            cls_name = classes[0].name
            print(f"\nReading body of class: {cls_name}")
            body = sdk.get_class_body(cls_name)
            if body:
                preview = body[:200] + "..." if len(body) > 200 else body
                print(f"\n{preview}")
            else:
                print("  (source file not resolvable)")


def example_complexity_filtering():
    """Filter symbols by complexity (branches and lines of code)."""
    print("\n=== Complexity Filtering ===\n")

    with CodeIndexSDK("code_index.db") as sdk:
        # Find functions with high branching complexity (5+ branches)
        high_branch_funcs = sdk.get_functions_by_complexity(min_branches=5)
        print(f"Functions with 5+ branches: {len(high_branch_funcs)}")
        for func in high_branch_funcs[:5]:
            lines = func.location.end_line - func.location.start_line + 1
            print(f"  - {func.name}: {func.branch_count} branches, {lines} LOC")

        # Find long functions (30+ lines)
        long_funcs = sdk.get_functions_by_complexity(min_lines=30)
        print(f"\nFunctions with 30+ lines: {len(long_funcs)}")
        for func in long_funcs[:5]:
            lines = func.location.end_line - func.location.start_line + 1
            print(f"  - {func.name}: {lines} lines, {func.branch_count} branches")

        # LOGICAL OR: Find functions that are EITHER high-branch OR long
        # (good for finding "suspicious" code to review)
        complex_funcs = sdk.get_functions_by_complexity(
            min_branches=5,
            min_lines=30,
            match_any=True  # LOGICAL OR
        )
        print(f"\nComplex functions (5+ branches OR 30+ lines): {len(complex_funcs)}")

        # LOGICAL AND: Find functions that are BOTH high-branch AND long
        # (the truly complex functions)
        very_complex_funcs = sdk.get_functions_by_complexity(
            min_branches=5,
            min_lines=30,
            match_any=False  # LOGICAL AND
        )
        print(f"Very complex functions (5+ branches AND 30+ lines): {len(very_complex_funcs)}")

        # Range filtering: medium complexity functions
        medium_funcs = sdk.get_functions_by_complexity(
            min_branches=2,
            max_branches=5,
            min_lines=10,
            max_lines=30
        )
        print(f"\nMedium complexity functions (2-5 branches, 10-30 lines): {len(medium_funcs)}")

        # Filter by file
        files = sdk.get_files()
        if files:
            file_funcs = sdk.get_functions_by_complexity(
                min_branches=3,
                file_id=files[0].id
            )
            print(f"\nComplex functions in {files[0].path}: {len(file_funcs)}")

        # Convenience method for finding complex code
        complex_symbols = sdk.get_complex_symbols(min_branches=5, min_lines=30)
        print(f"\nAll complex symbols: {len(complex_symbols)}")

        # Filter class methods by complexity
        classes = sdk.get_classes()
        if classes:
            complex_methods = sdk.get_methods_by_complexity(
                class_id=classes[0].id,
                min_branches=3,
                match_any=True
            )
            print(f"\nComplex methods in class '{classes[0].name}': {len(complex_methods)}")


def example_description_management():
    """Description management examples for AI-generated documentation."""
    print("\n=== Description Management ===\n")

    with CodeIndexSDK("code_index.db") as sdk:
        # Get a function to work with
        funcs = sdk.get_functions()
        if funcs:
            func = funcs[0]
            print(f"Setting description for function: {func.name}")

            # Set description by ID
            success = sdk.set_function_description(func.id, "Handles user authentication flow")
            print(f"  Updated: {success}")

            # Verify the description was set
            updated_func = sdk.get_function_by_id(func.id)
            print(f"  Description: {updated_func.description}")

        # Set description by name (with optional file path disambiguation)
        success = sdk.set_function_description_by_name(
            "main",
            "Application entry point",
            file_path="src/main.py"  # Optional: disambiguate if multiple "main" functions exist
        )
        print(f"\nSet 'main' function description: {success}")

        # Set description for a class
        classes = sdk.get_classes()
        if classes:
            cls = classes[0]
            print(f"\nSetting description for class: {cls.name}")
            sdk.set_class_description(cls.id, "Service class for managing user accounts")

            # Set by name
            sdk.set_class_description_by_name("UserService", "Handles user operations")

        # Set description for a variable
        variables = sdk.get_variables()
        if variables:
            var = variables[0]
            print(f"\nSetting description for variable: {var.name}")
            sdk.set_variable_description(var.id, "Configuration timeout in seconds")

        # Set description for a type alias
        type_aliases = sdk.get_type_aliases()
        if type_aliases:
            alias = type_aliases[0]
            print(f"\nSetting description for type alias: {alias.name}")
            sdk.set_type_alias_description(alias.id, "User ID type alias for clarity")

        # Set description for a struct (Go)
        structs = sdk.get_structs()
        if structs:
            struct = structs[0]
            print(f"\nSetting description for struct: {struct.name}")
            sdk.set_struct_description(struct.id, "Represents a database connection pool")

        # Set description for an interface (Go)
            interfaces = sdk.get_interfaces()
            if interfaces:
                interface = interfaces[0]
                print(f"\nSetting description for interface: {interface.name}")
                sdk.set_interface_description(interface.id, "Defines storage backend interface")

        # Generic method for any symbol type
        if funcs:
            print(f"\nUsing generic set_symbol_description for function {funcs[0].name}")
            sdk.set_symbol_description(
                symbol_type='function',
                symbol_id=funcs[0].id,
                description="Updated via generic method"
            )


if __name__ == "__main__":
    # Run all examples
    example_basic_queries()
    example_function_search()
    example_class_exploration()
    example_file_analysis()
    example_cross_reference()
    example_ai_agent_workflow()
    example_context_manager()
    example_manual_connection()
    example_internal_external_imports()
    example_source_body_reading()
    example_complexity_filtering()
    example_description_management()

    print("\n=== All examples completed ===")
