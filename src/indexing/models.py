#!/usr/bin/env python3
"""
Data models for the Code Index SDK.
Dataclasses representing code entities stored in the SQLite index.
"""

import json
import sqlite3
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class Location:
    """Source code location."""
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_byte: Optional[int] = None
    end_byte: Optional[int] = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Location':
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Function:
    """Function or method definition."""
    id: int
    name: str
    type: str  # 'function' or 'method'
    file_id: int
    file_path: str
    location: Location
    parameters: List[Dict]
    return_type: Optional[str]
    docstring: Optional[str]
    description: Optional[str] = None
    receiver: Optional[str] = None
    parent_id: Optional[int] = None
    parent_type: Optional[str] = None
    branch_count: int = 0
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Function':
        return cls(
            id=row['id'],
            name=row['name'],
            type=row['type'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            parameters=json.loads(row['parameters']),
            return_type=row['return_type'],
            docstring=row['docstring'],
            description=row['description'] if 'description' in row.keys() else None,
            receiver=row['receiver'],
            parent_id=row['parent_id'],
            parent_type=row['parent_type'],
            branch_count=row['branch_count'] if 'branch_count' in row.keys() else 0
        )


@dataclass
class Class:
    """Class definition."""
    id: int
    name: str
    file_id: int
    file_path: str
    location: Location
    base_classes: List[str]
    docstring: Optional[str]
    description: Optional[str] = None
    parent_id: Optional[int] = None
    namespace: Optional[str] = None
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Class':
        return cls(
            id=row['id'],
            name=row['name'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            base_classes=json.loads(row['base_classes']),
            docstring=row['docstring'],
            description=row['description'] if 'description' in row.keys() else None,
            parent_id=row['parent_id'],
            namespace=row['namespace'] if 'namespace' in row.keys() else None
        )


@dataclass
class Variable:
    """Variable or attribute definition."""
    id: int
    name: str
    type: str  # 'variable' or 'attribute'
    file_id: int
    file_path: str
    location: Location
    field_type: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None
    parent_type: Optional[str] = None
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Variable':
        return cls(
            id=row['id'],
            name=row['name'],
            type=row['type'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            field_type=row['field_type'],
            description=row['description'] if 'description' in row.keys() else None,
            parent_id=row['parent_id'],
            parent_type=row['parent_type']
        )


@dataclass
class TypeAlias:
    """Type alias definition."""
    id: int
    name: str
    file_id: int
    file_path: str
    location: Location
    type_definition: Optional[str]
    description: Optional[str] = None
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'TypeAlias':
        return cls(
            id=row['id'],
            name=row['name'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            type_definition=row['type_definition'],
            description=row['description'] if 'description' in row.keys() else None
        )


@dataclass
class Struct:
    """Struct definition (Go, Rust, C, etc.)."""
    id: int
    name: str
    file_id: int
    file_path: str
    location: Location
    description: Optional[str] = None
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Struct':
        return cls(
            id=row['id'],
            name=row['name'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            description=row['description'] if 'description' in row.keys() else None
        )


@dataclass
class Interface:
    """Interface/trait definition (Go, Rust, TypeScript, etc.)."""
    id: int
    name: str
    file_id: int
    file_path: str
    location: Location
    description: Optional[str] = None
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Interface':
        return cls(
            id=row['id'],
            name=row['name'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            description=row['description'] if 'description' in row.keys() else None
        )


@dataclass
class Enum:
    """Enum definition (Rust, etc.)."""
    id: int
    name: str
    file_id: int
    file_path: str
    location: Location
    description: Optional[str] = None
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Enum':
        return cls(
            id=row['id'],
            name=row['name'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            description=row['description'] if 'description' in row.keys() else None
        )


@dataclass
class Namespace:
    """Namespace definition (C#, etc.)."""
    id: int
    name: str
    file_id: int
    file_path: str
    location: Location
    description: Optional[str] = None
    
    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Namespace':
        return cls(
            id=row['id'],
            name=row['name'],
            file_id=row['file_id'],
            file_path=file_path,
            location=Location.from_dict(json.loads(row['location'])),
            description=row['description'] if 'description' in row.keys() else None
        )


@dataclass
class File:
    """File information."""
    id: int
    path: str
    absolute_path: str
    language: str
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'File':
        return cls(
            id=row['id'],
            path=row['path'],
            absolute_path=row['absolute_path'],
            language=row['language']
        )


@dataclass
class Dependency:
    """Dependency information (imports and function calls)."""
    id: int
    file_id: int
    file_path: str
    dependency_type: str  # 'import' or 'function_call'
    name: str
    source_function_id: Optional[int] = None
    target_function_id: Optional[int] = None
    target_class_id: Optional[int] = None
    location: Optional[Location] = None
    is_external: bool = True  # True for external dependencies, False for internal

    @classmethod
    def from_row(cls, row: sqlite3.Row, file_path: str) -> 'Dependency':
        return cls(
            id=row['id'],
            file_id=row['file_id'],
            file_path=file_path,
            dependency_type=row['dependency_type'],
            name=row['name'],
            source_function_id=row['source_function_id'],
            target_function_id=row['target_function_id'] if 'target_function_id' in row.keys() else None,
            target_class_id=row['target_class_id'] if 'target_class_id' in row.keys() else None,
            location=Location.from_dict(json.loads(row['location'])) if row['location'] else None,
            is_external=bool(row['is_external']) if 'is_external' in row.keys() else True
        )
