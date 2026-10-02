def greet(name: str = "World") -> str:
    """Return a simple greeting for the given name."""
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(greet())
